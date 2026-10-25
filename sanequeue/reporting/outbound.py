"""Scoped evidence for outbound CDR segments started during an observed pause."""
import math
from .queries import _scope, _where
from .store import QueryDeadline


def page(archive,scope,start,end,*,before=None,limit=100,ident=None,direction='outbound'):
    _where(archive.pbx,scope,start,end)
    if direction not in ('outbound','internal'):raise ValueError('invalid_pause_call_direction')
    start=max(float(start),scope.not_before)
    observed=float(archive.checkpoint('activity_cache').get('observed',0))
    if not observed:return dict(rows=[],next=None,coverage='activity_unavailable')
    clause,args=_scope(archive.pbx,scope)
    # Qualify scope fields inside the correlated activity subquery.
    clause=clause.replace('pbx=','a.pbx=').replace('queue IN','a.queue IN').replace('agent IN','a.agent IN')
    predicate=clause+" AND a.state='paused' AND a.canonical_agent=p.agent AND a.starts<=c.ts AND COALESCE(a.ends,?)>c.ts"
    match_args=[*args,observed]
    where="c.pbx=? AND c.ts>=? AND c.ts<? AND p.direction=? AND EXISTS (SELECT 1 FROM report_activity a WHERE "+predicate+')'
    values=[archive.pbx,start,float(end),direction,*match_args]
    if ident is not None:
        if not isinstance(ident,str) or not 1<=len(ident)<=512:raise ValueError('invalid_outbound_identity')
        where+=' AND c.source_key=?'
        values.append(ident)
    if before:
        if len(before)!=2 or not math.isfinite(float(before[0])) or len(str(before[1]))>256:
            raise ValueError('invalid_outbound_cursor')
        where+=' AND (c.ts<? OR (c.ts=? AND c.source_key<?))'
        values.extend((float(before[0]),float(before[0]),str(before[1])))
    limit=max(1,min(200,int(limit)))
    with archive.reader() as db:
        rows=[dict(row) for row in db.execute('''SELECT c.source_key id,c.ts,c.dst destination,c.duration,
          c.billsec,c.disposition,c.uid,c.linkedid,p.agent,p.inventory_observed,
          CASE WHEN c.recording<>'' THEN 1 ELSE 0 END has_recording
          FROM report_cdr c JOIN report_cdr_parties p ON p.pbx=c.pbx AND p.source_key=c.source_key
          WHERE '''+where+' ORDER BY c.ts DESC,c.source_key DESC LIMIT ?',(*values,limit+1))]
        more=len(rows)>limit;rows=rows[:limit]
        if rows:
            candidates=','.join('(?,?,?)' for _ in rows)
            params=[value for row in rows for value in (row['id'],row['agent'],row['ts'])]
            matches=db.execute('WITH candidates(id,agent,ts) AS (VALUES '+candidates+''')
              SELECT c.id,a.queue,a.reason,a.starts,MIN(COALESCE(a.ends,?),?) ends
              FROM candidates c JOIN report_activity a ON a.canonical_agent=c.agent
              WHERE '''+clause+" AND a.state='paused' AND a.starts<=c.ts AND COALESCE(a.ends,?)>c.ts LIMIT 4001",
                               (*params,observed,observed,*args,observed)).fetchall()
            if len(matches)>4000:raise QueryDeadline('outbound_membership_limit_narrow_scope')
            memberships={row['id']:[] for row in rows}
            for match in matches:
                memberships[match['id']].append({key:match[key] for key in ('queue','reason','starts','ends')})
            for row in rows:
                row['memberships']=memberships[row['id']]
                # Raw identifiers are not needed by the presentation layer.
                row.pop('uid');row.pop('linkedid')
    return dict(rows=rows,next=[rows[-1]['ts'],rows[-1]['id']] if more and rows else None,
                coverage='known_endpoint_pair_and_observed_pause',unit='cdr_segment',direction=direction,
                duration_definition='full_segment_billsec_not_pause_overlap',observed_until=observed)
