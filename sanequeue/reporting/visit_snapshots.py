"""Pinned versions without a long SQLite read transaction or full DB copy."""
import math
import re

from .queries import _where
from .snapshot_schema import FIELDS


class SnapshotUnavailable(RuntimeError):
    pass


def validate_token(token):
    if (not isinstance(token,dict) or set(token)!={'generation','sequence'}
            or not isinstance(token['generation'],str) or not re.fullmatch('[0-9a-f]{32}',token['generation'])
            or not isinstance(token['sequence'],int) or isinstance(token['sequence'],bool)
            or token['sequence']<0):
        raise ValueError('invalid_report_snapshot')


def validate(db, pbx, token):
    validate_token(token)
    state = db.execute('SELECT generation,ready FROM report_snapshot_meta WHERE pbx=?', (pbx,)).fetchone()
    if state is None or not state[1] or state[0]!=token['generation']:
        raise SnapshotUnavailable('report_snapshot_unavailable')
    latest = db.execute('SELECT MAX(seq) FROM report_visit_versions').fetchone()[0] or 0
    if latest<token['sequence']:
        raise SnapshotUnavailable('report_snapshot_unavailable')


def capture(archive):
    with archive.reader() as db:
        state = db.execute('SELECT generation,ready FROM report_snapshot_meta WHERE pbx=?', (archive.pbx,)).fetchone()
        if state is None or not state[1]:
            raise SnapshotUnavailable('report_snapshot_initializing')
        sequence = db.execute('SELECT MAX(seq) FROM report_visit_versions').fetchone()[0] or 0
    return dict(generation=state[0],sequence=sequence)


def page(db, pbx, token, scope, start, end, *, before=None, outcome=None, limit=200):
    validate(db,pbx,token)
    clause,args = _where(pbx,scope,start,end)
    # Scope and range refer to the historical version. A newer version outside
    # that range must still supersede an older one for the same identity.
    if outcome is not None:
        if outcome not in ('answered','abandoned','waiting','connected','transferred',
                           'exitwithtimeout','exitempty','exitwithkey','unknown','reentered_without_end'):
            raise ValueError('invalid_report_outcome')
        clause+=' AND outcome=?';args.append(outcome)
    if before:
        if (not isinstance(before,(list,tuple)) or len(before)!=2
                or not math.isfinite(float(before[0])) or not re.fullmatch('[0-9a-f]{64}',str(before[1]))):
            raise ValueError('invalid_report_cursor')
        clause+=' AND (entered<? OR (entered=? AND id<?))'
        args.extend((float(before[0]),float(before[0]),str(before[1])))
    fields=','.join('v.'+field for field in FIELDS)
    return [dict(row) for row in db.execute('SELECT '+fields+' FROM report_visit_versions v WHERE '+clause+'''
      AND v.seq<=? AND v.deleted=0 AND NOT EXISTS (
        SELECT 1 FROM report_visit_versions newer WHERE newer.pbx=v.pbx AND newer.id=v.id
        AND newer.seq>v.seq AND newer.seq<=?)
      ORDER BY v.entered DESC,v.id DESC LIMIT ?''',(*args,token['sequence'],token['sequence'],max(1,min(200,int(limit)))))]
