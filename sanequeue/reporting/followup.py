"""Later queue contact after abandonment; never infer an outbound callback.

One row is one abandoned visit. Several abandoned visits can reference the same
later answered visit, so rows must not be summed as unique recovered customers.
Only identical recorded caller identities inside the authorised queue scope
are compared. A returned call does not prove that an employee called back.
"""
import math
import time

from .queries import _where, _scope
from .store import QueryDeadline

_UNKNOWN={'unknown','<unknown>','anonymous','restricted','unavailable','private','withheld','blocked','none','null'}


def _known_caller(value):
    return bool(value and str(value).strip() and str(value).strip().lower() not in _UNKNOWN)


def report(archive, scope, start, end, *, window_days=7, before=None, limit=100, now=None):
    if isinstance(window_days,bool) or not isinstance(window_days,int) or not 1<=window_days<=30:
        raise ValueError('invalid_followup_window')
    if isinstance(limit,bool) or not isinstance(limit,int) or not 1<=limit<=200:
        raise ValueError('invalid_followup_limit')
    clause,args=_where(archive.pbx,scope,start,end)
    if scope.self_only:raise ValueError('followup_requires_supervisor_scope')
    if before:
        stamp,ident=float(before[0]),str(before[1])
        if not math.isfinite(stamp) or len(ident)!=64:raise ValueError('invalid_followup_cursor')
        clause+=' AND (entered<? OR (entered=? AND id<?))';args.extend((stamp,stamp,ident))
    seen_until=time.time() if now is None else float(now)
    if not math.isfinite(seen_until) or seen_until<0:raise ValueError('invalid_followup_time')
    clause+=' AND entered<?';args.append(seen_until)
    peer_clause,peer_args=_scope(archive.pbx,scope)
    deadline=time.monotonic()+archive.read_seconds
    if time.monotonic()>=deadline:raise QueryDeadline('followup_query_deadline')
    with archive.reader() as db:
        candidates=[dict(r) for r in db.execute('''SELECT id,queue,entered,ended,caller,wait_seconds,coverage
          FROM report_visits WHERE '''+clause+''' AND outcome='abandoned' AND (ended IS NULL OR ended<=?)
          ORDER BY entered DESC,id DESC LIMIT ?''',(*args,seen_until,limit+1))]
        more=len(candidates)>limit;rows=[]
        for item in candidates[:limit]:
            if time.monotonic()>=deadline:raise QueryDeadline('followup_query_deadline')
            boundary=item['ended'];caller=item['caller']
            anchor=boundary if boundary is not None else item['entered']
            cutoff=min(seen_until,anchor+window_days*86400)
            # Empty identities and unproven abandonment boundaries cannot be
            # matched. Query only a small indexed successor, never all legs.
            peers=[]
            matchable=_known_caller(caller) and boundary is not None and boundary>=item['entered'] and item['coverage']=='observed'
            if matchable and cutoff>boundary:
                peers=[dict(r) for r in db.execute('''SELECT id,queue,entered,answered,outcome
                  FROM report_visits INDEXED BY rv_caller_time WHERE '''+peer_clause+'''
                  AND caller=? AND entered>? AND entered<? AND entered>=? AND coverage IN ('observed','missing_end')
                  ORDER BY entered,id LIMIT 1''',(*peer_args,caller,boundary,cutoff,scope.not_before))]
            first=peers[0] if peers else None
            answered=None
            if first:
                hit=db.execute('''SELECT id,queue,entered,answered FROM report_visits INDEXED BY rv_caller_time
                  WHERE '''+peer_clause+''' AND caller=? AND entered>? AND entered<? AND entered>=?
                  AND coverage IN ('observed','missing_end') AND answered IS NOT NULL AND answered>=entered AND answered<?
                  ORDER BY entered,id LIMIT 1''',
                  (*peer_args,caller,boundary,cutoff,scope.not_before,cutoff)).fetchone()
                answered=dict(hit) if hit else None
            item.update(first_reentry=first,later_answered=answered,
                observation_end=cutoff,window_elapsed=seen_until>=anchor+window_days*86400,
                matchable=bool(matchable))
            rows.append(item)
    return dict(rows=rows,next=[rows[-1]['entered'],rows[-1]['id']] if more and rows else None,
        window_days=window_days,unit='abandoned_queue_visit',complete_conversation=False,
        attribution='same_recorded_identity_later_authorised_queue_visit',outbound_callback_proven=False,
        window_anchor='observed_abandonment_end',
        complete_history=False)
