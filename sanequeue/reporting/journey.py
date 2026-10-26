"""Conservative, bounded semantic journey. A graph is never an audio grant.

Shared linkedid/bridge membership does not establish ownership or a single
conversation. Unowned downstream legs are intentionally omitted. Number values
exist only in ``numbers`` and must be masked by the authenticated HTTP adapter.
"""
import json
import math
import re
import time

from . import queries
from .store import Archive, QueryDeadline

MAX_UIDS=100
MAX_EVENTS=1000
MAX_EVIDENCE_BYTES=4*1024*1024
_KINDS={'CHAN_START','ANSWER','HANGUP','CHAN_END','BRIDGE_ENTER','BRIDGE_EXIT',
        'LOCAL_OPTIMIZE','LOCAL_OPTIMIZE_BEGIN','LOCAL_OPTIMIZE_END',
        'ATTENDEDTRANSFER','BLINDTRANSFER','APP_START','APP_END','USER_DEFINED'}
_RELATIONS={'local_optimize','local_optimize_begin','local_optimize_end',
            'blindtransfer','attendedtransfer','transfer_second_channel','bridge_enter','bridge_exit','direct_peer','queue_connect_peer'}
_QUEUE_KINDS={'ENTERQUEUE','CONNECT','COMPLETECALLER','COMPLETEAGENT','ABANDON',
    'TRANSFER','BLINDTRANSFER','ATTENDEDTRANSFER','EXITWITHTIMEOUT','EXITEMPTY',
    'EXITWITHKEY','RINGNOANSWER','RINGCANCELED','SYSCOMPAT','AGENTDUMP'}


def _object(value):
    if isinstance(value,str):
        try:value=json.loads(value)
        except (ValueError,TypeError):return {}
    return value if isinstance(value,dict) else {}


def explain(archive,scope,start,end,visit_id):
    """Return scoped evidence, never promise complete conversation coverage.

    ``direct_peer`` edges may support final hangup only when their two uniqueid
    endpoints and CEL hangupsource UID explicitly agree; timing alone is not
    causality. Current collectors need not provide this evidence: None is valid.
    """
    deadline=time.monotonic()+min(5,archive.read_seconds)
    def check():
        if time.monotonic()>=deadline:raise QueryDeadline('journey_deadline')
    def bounded():
        check()
        return Archive(archive.path,pbx=archive.pbx,read_seconds=max(.001,min(5,deadline-time.monotonic())))
    detail=queries.detail(bounded(),scope,start,end,visit_id)
    if detail is None:return None
    visit=detail['visit'];root=visit['callid'];numbers={};nodes=[];edges=[];events=[]
    node_ids={};bridge_ids={};omitted=False;limited=False;budget=MAX_EVENTS;evidence_bytes=0
    def evidence(value,maximum):
        nonlocal evidence_bytes,limited,omitted
        if not isinstance(value,str):limited=True;omitted=True;return None
        size=len(value.encode('utf-8'))
        if size>maximum or evidence_bytes+size>MAX_EVIDENCE_BYTES:
            limited=True;omitted=True;return None
        evidence_bytes+=size
        return _object(value)
    def number(value):
        if value in (None,''):return None
        text=str(value)
        # Raw arbitrary dialplan strings or paths are not telephone numbers.
        if not re.fullmatch(r'\+?[0-9\u0660-\u0669\u06f0-\u06f9]{1,24}',text):return None
        for key,existing in numbers.items():
            if existing==text:return key
        key='n'+str(len(numbers)+1);numbers[key]=text;return key
    def node(uid):
        if uid not in node_ids:
            ident='leg'+str(len(node_ids)+1);node_ids[uid]=ident
            nodes.append(dict(id=ident,type='call_leg',status='observed',inferred=False,source='cel'))
        return node_ids[uid]
    root_node=node(root);nodes[0].update(source='queue_log',role='queue_caller')
    queue_node='queue';nodes.append(dict(id=queue_node,type='queue_visit',queue=visit['queue'],
        caller=number(visit.get('caller')),status='observed',inferred=False,source='queue_log'))
    edges.append(dict(source_node=queue_node,target_node=root_node,relation='queue_identity',
        status='observed',inferred=False,source='queue_log'))
    for item in detail['timeline'][:MAX_EVENTS]:
        # detail() may attach legacy linkedid-based CEL hints. Rebuild CEL
        # exclusively after this module's whole-UID ownership proof below.
        if item.get('source')=='cel':continue
        events.append(dict(id='event'+str(len(events)+1),node=queue_node,ts=item['ts'],
            kind=item['kind'] if item['kind'] in _QUEUE_KINDS else 'UNKNOWN',
            status='observed',inferred=False,source=item.get('source','queue_log')))
    budget-=len(events)
    if budget<=0:limited=True
    first=max(float(start),float(scope.not_before),float(visit['entered']))
    last=float(end)
    with bounded().reader() as db:
        authorized={};direct_cache={};raw_hangups={};peer_pairs=set()
        projection=db.execute('SELECT after_id FROM report_projection WHERE pbx=?',(archive.pbx,)).fetchone()
        latest=db.execute('SELECT MAX(id) FROM events WHERE pbx=?',(archive.pbx,)).fetchone()[0]
        version=db.execute('SELECT version FROM report_projection_version WHERE pbx=?',(archive.pbx,)).fetchone()
        caught_up=bool(version and version[0]>=8 and projection and projection[0]>=(latest or 0))
        if not caught_up:omitted=True
        def direct(uid):
            if uid in direct_cache:return direct_cache[uid]
            check()
            rows=db.execute('''SELECT queue,agent,entered,answered,ended,coverage FROM report_visits
                WHERE pbx=? AND callid=? LIMIT 1001''',(archive.pbx,uid)).fetchall()
            ok=bool(rows) and len(rows)<=1000 and all(row['queue'] in scope.queues
                and row['coverage']=='observed' and row['entered']>=scope.not_before
                and (not scope.self_only or row['agent'] in scope.agents) for row in rows)
            direct_cache[uid]=(ok,rows)
            return ok,rows
        def owned(uid):
            nonlocal omitted,limited,budget
            if uid in authorized:return authorized[uid]
            ok,visits=direct(uid)
            if (ok or not visits) and budget>0:
                # edge_to finds an actual agent UID without scanning raw CEL or
                # queue JSON across millions of archive events. Latest source
                # version joins invalidate superseded CONNECT identities.
                incoming=db.execute('''SELECT r.from_id,r.from_kind,r.ts,
                  CASE WHEN length(CAST(r.details AS BLOB))<=2048 THEN r.details ELSE NULL END details,
                  e.source,e.kind FROM evidence_edges r
                  JOIN events e ON e.pbx=r.pbx AND e.id=r.event_id
                  JOIN source_items s ON s.pbx=e.pbx AND s.source=e.source
                    AND s.source_key=e.source_key AND s.event_id=e.id
                  WHERE r.pbx=? AND r.to_kind='uniqueid' AND r.to_id=?
                    AND r.relation='queue_connect_peer' ORDER BY r.ts,r.event_id LIMIT ?''',
                  (archive.pbx,uid,min(1000,budget)+1)).fetchall()
                if len(incoming)>min(1000,budget):limited=True;ok=False
                else:
                    budget-=len(incoming)
                    callers={row['from_id'] for row in incoming}
                    ok=(ok if not incoming else len(callers)==1 and uid not in callers)
                    leg=db.execute('SELECT started,ended FROM legs WHERE pbx=? AND uid=?',(archive.pbx,uid)).fetchone()
                    for row in incoming:
                        check();proof=evidence(row['details'],2048)
                        if proof is None:ok=False;continue
                        caller_ok,caller_visits=direct(row['from_id'])
                        matches=[visit for visit in caller_visits if visit['queue']==proof.get('queue')
                            and visit['agent']==proof.get('agent') and visit['answered']==row['ts']
                            and visit['entered']<=row['ts'] and (visit['ended'] is None or row['ts']<=visit['ended'])]
                        # Only an already-owned caller can delegate its explicit
                        # agent leg; do not recursively bootstrap ownership from
                        # two ambiguous incoming relationships.
                        if not (caller_ok and authorized.get(row['from_id']) is True
                            and row['from_kind']=='uniqueid' and row['source'].startswith('queue_log')
                            and row['kind'].upper()=='CONNECT' and len(matches)==1
                            and proof.get('queue') in scope.queues and row['ts']>=scope.not_before
                            and (not scope.self_only or proof.get('agent') in scope.agents)):
                            ok=False
                        if leg and (leg['started'] is not None and leg['started']>row['ts']
                                    or leg['ended'] is not None and leg['ended']<row['ts']):ok=False
            elif not visits:ok=False
            authorized[uid]=ok
            if not ok:omitted=True
            return ok
        pending=[root] if caught_up else [];seen=set()
        while pending:
            check()
            uid=pending.pop(0)
            if uid in seen:continue
            if len(seen)>=MAX_UIDS or budget<=0:limited=True;break
            seen.add(uid)
            if not owned(uid):continue
            leg_node=node(uid)
            # Fetch only exact uniqueid, never linkedid expansion. SQL CDR/CEL
            # imports are append-only; source_items selects the current version.
            rows=db.execute('''SELECT e.id,e.ts,e.kind,
                CASE WHEN length(CAST(e.payload AS BLOB))<=4096 THEN e.payload ELSE NULL END payload
                FROM events e JOIN source_items s
                ON s.pbx=e.pbx AND s.event_id=e.id AND s.source=e.source AND s.source_key=e.source_key
                JOIN legs l ON l.pbx=e.pbx AND l.uid=?
                WHERE e.pbx=? AND e.source='cel' AND e.ts>=? AND e.ts<?
                AND json_extract(e.payload,'$.uniqueid')=? ORDER BY e.ts,e.id LIMIT ?''',
                (uid,archive.pbx,first,last,uid,budget+1)).fetchall()
            if len(rows)>budget:rows=rows[:budget];limited=True
            for item in rows:
                check();budget-=1
                kind=item['kind'].upper()
                if kind not in _KINDS:continue
                parsed=evidence(item['payload'],4096)
                if parsed is None:continue
                payload={str(key).lower():value for key,value in parsed.items()}
                extra=_object(payload.get('eventextra') or payload.get('extra'))
                event=dict(id='event'+str(len(events)+1),node=leg_node,ts=item['ts'],kind=kind,
                           status='observed',inferred=False,source='cel')
                if kind in ('APP_START','APP_END'):
                    app=str(payload.get('appname') or '').lower();context=str(payload.get('context') or '')
                    origin=None
                    if app in ('read','background','waitexten') and re.fullmatch(r'ivr-[0-9]+',context):origin='ivr'
                    if app=='dial' and context=='ext-group':origin='ring_group'
                    if app in ('followme','dial') and context in ('ext-findme','followme-check'):origin='follow_me'
                    if origin is None:continue
                    event['origin']=origin
                if kind=='USER_DEFINED':
                    if payload.get('userdeftype') not in ('IVRSelection','SaneQueueIVR'):continue
                    digit=str(extra.get('digit',''))
                    if not re.fullmatch(r'[0-9*#]',digit):continue
                    event.update(kind='IVR_SELECTION',digit=digit,origin='ivr')
                if kind=='HANGUP':
                    cause=extra.get('hangupsource_uniqueid')
                    if isinstance(cause,str) and cause:raw_hangups[uid]=(cause,item['ts'])
                events.append(event)
            relation_rows=db.execute('''SELECT r.relation,r.to_kind,r.to_id,r.ts,
                CASE WHEN length(CAST(r.details AS BLOB))<=2048 THEN r.details ELSE NULL END details
                FROM evidence_edges r JOIN events e
                ON e.pbx=r.pbx AND e.id=r.event_id JOIN source_items s
                ON s.pbx=e.pbx AND s.source=e.source AND s.source_key=e.source_key AND s.event_id=e.id
                WHERE r.pbx=? AND r.from_kind='uniqueid'
                AND r.from_id=? AND r.ts>=? AND r.ts<? ORDER BY r.ts,r.event_id LIMIT ?''',
                (archive.pbx,uid,first,last,budget+1)).fetchall()
            if len(relation_rows)>budget:relation_rows=relation_rows[:budget];limited=True
            for relation in relation_rows:
                if budget<=0:limited=True;break
                check();budget-=1
                kind=relation['relation']
                if kind not in _RELATIONS:continue
                relation_details=evidence(relation['details'],2048)
                if relation_details is None:continue
                target=None;target_uid=None
                if relation['to_kind']=='uniqueid':target_uid=relation['to_id']
                elif relation['to_kind']=='channel':
                    # Exact channel relation is evidence; a channel name is not
                    # exposed. Multiple UIDs sharing it are ambiguous.
                    candidates=db.execute('SELECT uid FROM legs WHERE pbx=? AND channel=? LIMIT 2',
                                          (archive.pbx,relation['to_id'])).fetchall()
                    if len(candidates)==1:target_uid=candidates[0]['uid']
                elif relation['to_kind']=='bridge':
                    key=relation['to_id']
                    if key not in bridge_ids:
                        target='bridge'+str(len(bridge_ids)+1);bridge_ids[key]=target
                        nodes.append(dict(id=target,type='bridge',status='observed',inferred=False,source='evidence_edges'))
                    else:target=bridge_ids[key]
                if target_uid:
                    if len(node_ids)>=MAX_UIDS and target_uid not in node_ids:limited=True;continue
                    if not owned(target_uid):continue
                    new_node=target_uid not in node_ids
                    target=node(target_uid);pending.append(target_uid)
                    if new_node and kind=='queue_connect_peer':nodes[-1].update(source='queue_log',role='queue_agent')
                    if kind=='direct_peer' or kind=='queue_connect_peer' and uid==root:
                        peer_pairs.add(frozenset((uid,target_uid)))
                if target is None:
                    omitted=True;continue
                edge=dict(source_node=leg_node,target_node=target,relation=kind,ts=relation['ts'],
                          status='observed',inferred=False,source='evidence_edges')
                # No inferred consultation interval from overlapping bridges.
                if kind=='attendedtransfer':
                    extra=relation_details;a=extra.get('consultation_started');b=extra.get('consultation_ended')
                    if isinstance(a,(int,float)) and isinstance(b,(int,float)) and math.isfinite(a) and math.isfinite(b) and first<=a<=b<=relation['ts']:
                        edge['consultation_seconds']=b-a
                    else:edge['consultation_seconds']=None
                if kind=='queue_connect_peer':edge['source']='queue_log'
                edges.append(edge)
            if budget<=0:limited=True;continue
            cdrs=db.execute('''SELECT src,dst,ts,duration,billsec,disposition,linkedid FROM report_cdr
                WHERE pbx=? AND uid=? AND ts>=? AND ts<? ORDER BY ts,source_key LIMIT ?''',
                (archive.pbx,uid,first,last,budget+1)).fetchall()
            if len(cdrs)>budget:cdrs=cdrs[:budget];limited=True
            for cdr in cdrs:
                if budget<=0:limited=True;break
                check();budget-=1
                if cdr['linkedid'] and cdr['linkedid']!=uid and not owned(cdr['linkedid']):continue
                # Status strings, durations and numbers only; never recording,
                # channel, source_key, accountcode or raw application payload.
                disposition=str(cdr['disposition'] or '').upper()
                if disposition not in ('ANSWERED','BUSY','NO ANSWER','FAILED','CONGESTION','CANCEL','CHANUNAVAIL'):disposition='UNKNOWN'
                events.append(dict(id='event'+str(len(events)+1),node=leg_node,ts=cdr['ts'],kind='CDR_SEGMENT',
                    caller=number(cdr['src']),destination=number(cdr['dst']),duration=cdr['duration'],
                    billsec=cdr['billsec'],disposition=disposition,status='observed',inferred=False,source='cdr'))
        final=None
        # More than two evidenced legs or more than one direct pair is a
        # conference/transfer ambiguity, not a single final hangup attribution.
        if len(node_ids)==2 and len(peer_pairs)==1 and len(raw_hangups)==2 and not omitted and not limited:
            pair=next(iter(peer_pairs));causes={value[0] for value in raw_hangups.values()}
            if len(pair)==2 and len(causes)==1 and next(iter(causes)) in pair:
                final=dict(node=node_ids[next(iter(causes))],status='observed',inferred=False,source='cel_direct_peer_causality')
    events.sort(key=lambda item:(item['ts'],item['id']))
    return dict(visit_id=visit_id,nodes=nodes,edges=edges,events=events,numbers=numbers,final_hangup=final,
                coverage=dict(status='partial',complete_conversation=False,restricted_or_unproven=omitted,
                              limit_reached=limited,linkedid_merge=False),
                limits=dict(uids=MAX_UIDS,events=MAX_EVENTS,seconds=min(5,archive.read_seconds),
                            evidence_bytes=MAX_EVIDENCE_BYTES,cel_payload_bytes=4096,edge_details_bytes=2048),audio_granted=False)
