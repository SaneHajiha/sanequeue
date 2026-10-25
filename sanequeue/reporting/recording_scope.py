"""Authorize whole recordings, never only the queue that supplied a link.

A MixMonitor file can cover several queue visits. Transferred or incomplete
conversations remain unavailable until complete recording ownership is known.
This deliberately prefers missing audio over disclosing another queue's audio.
"""
from pathlib import PurePosixPath
import json
import time


def ownership(archive, recording_id, *, fallback_queues=()):
    with archive.reader() as db:
        now=time.time()
        # Never authorize from a partly rebuilt projection or while SQL/CEL
        # is behind. Playback waits for the post-call CDR/CEL settling window.
        for source in ('sql','queue_log'):
            health=db.execute('SELECT value FROM checkpoints WHERE pbx=? AND source=?',
                              (archive.pbx,'health:'+source)).fetchone()
            if not health:return False
            health=json.loads(health[0])
            if not health.get('ok') or not 0<=now-health.get('checked',0)<=90:return False
            progress=health.get('progress',{})
            required=('cel_caught_up','cdr_caught_up') if source=='sql' else ('caught_up',)
            if not all(progress.get(key) is True for key in required):return False
        projection=db.execute('SELECT after_id FROM report_projection WHERE pbx=?',(archive.pbx,)).fetchone()
        latest=db.execute('SELECT MAX(id) FROM events WHERE pbx=?',(archive.pbx,)).fetchone()[0]
        if not projection or projection[0]<(latest or 0):return False
        row = db.execute('SELECT * FROM report_cdr WHERE pbx=? AND source_key=?',
                         (archive.pbx, recording_id)).fetchone()
        if not row or not row['recording']:
            return False
        # Basenames and dated references can resolve to the same file. The
        # conservative basename match also denies ambiguous reused filenames.
        basename = PurePosixPath(row['recording']).name
        same = db.execute('''SELECT c.* FROM report_recording_refs r JOIN report_cdr c
          ON c.pbx=r.pbx AND c.source_key=r.source_key WHERE r.pbx=? AND r.basename=? LIMIT 501''',
          (archive.pbx, basename)).fetchall()
        if not same or len(same) > 500:
            return False
        identities = {value for item in same for value in (item['uid'], item['linkedid']) if value}
        if not identities or len(identities) > 200:
            return False
        marks = ','.join('?' for _ in identities)
        chain = db.execute('SELECT * FROM report_cdr WHERE pbx=? AND (uid IN (' + marks +
                           ') OR linkedid IN (' + marks + ')) LIMIT 1001',
                           (archive.pbx, *identities, *identities)).fetchall()
        if len(chain) > 1000:
            return False
        if any(c['duration'] is None or c['ts']+c['duration']>now-120 for c in chain):return False
        checkpoint=db.execute('SELECT value FROM checkpoints WHERE pbx=? AND source=?',
                              (archive.pbx,'queue_log')).fetchone()
        checkpoint=json.loads(checkpoint[0]) if checkpoint else {}
        gaps=checkpoint.get('coverage_gaps',[])
        if not gaps and checkpoint.get('last_rotation_detected'):
            gaps=[[0,checkpoint['last_rotation_detected']]]
        # The file can begin before the selected queue visit (for example in
        # IVR). Check its entire observed CDR span, not only that queue span.
        if any(c['ts']<=right and c['ts']+c['duration']>=left for c in chain for left,right in gaps):return False
        expanded = {value for item in chain for value in (item['uid'], item['linkedid']) if value}
        if expanded - identities:
            # A second identity hop requires a complete conversation ownership
            # model. Do not authorize only the visible prefix of that graph.
            return False
        if len(identities) > 200:
            return False
        visits = db.execute('SELECT callid,queue,coverage,outcome,entered,ended FROM report_visits WHERE pbx=? AND callid IN (' +
                            ','.join('?' for _ in identities) + ') LIMIT 1001',
                            (archive.pbx, *identities)).fetchall()
        if len(visits) > 1000 or any(v['coverage'] != 'observed' or v['outcome'] == 'transferred' for v in visits):
            return False
        queues = {v['queue'] for v in visits}
        if visits:
            observed={v['callid'] for v in visits}
            if any(not {item['uid'],item['linkedid']}.intersection(observed) for item in same):return False
            if any(v['ended'] is None or v['ended']>now-120 for v in visits):return False
            end=max(v['ended'] for v in visits)
            # An unobserved downstream leg must not ride on the original
            # queue's permission while a transfer CEL event is still late.
            if any(c['duration'] is None or c['ts']+c['duration']>end+2 for c in chain):return False
            if any(v['entered']<=right and v['ended']>=left for v in visits for left,right in gaps):return False
        if not visits:
            # Non-queue survey calls require one proven CDR leg and its
            # observed pause memberships. Multi-leg ownership is ambiguous.
            if len(chain) != 1 or len(same) != 1:
                return False
            if row['duration'] is None or row['ts']+row['duration']>now-120:return False
            memberships=db.execute('''SELECT a.queue FROM report_activity a JOIN report_cdr_parties p
              ON p.pbx=a.pbx AND p.agent=a.canonical_agent WHERE p.pbx=? AND p.source_key=?
              AND a.state='paused' AND a.starts<=? AND (a.ends IS NULL OR a.ends>?) LIMIT 1001''',
              (archive.pbx,recording_id,row['ts'],row['ts'])).fetchall()
            if len(memberships)>1000:return False
            queues.update(item['queue'] for item in memberships)
            queues.update(fallback_queues)
        return frozenset(queues)


def permitted(archive, recording_id, capability, can_queue, *, fallback_queues=()):
    queues=ownership(archive,recording_id,fallback_queues=fallback_queues)
    return bool(queues) and all(can_queue(queue,capability) for queue in queues)
