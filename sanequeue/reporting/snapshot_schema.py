"""SQLite-only version capture for immutable, short-reader report snapshots."""

FIELDS = ('pbx','id','callid','queue','entered','answered','ended','caller','agent',
          'outcome','wait_seconds','talk_seconds','segment_ended_by','coverage')
COLUMNS = ','.join(FIELDS)
SCHEMA = '''
CREATE TABLE IF NOT EXISTS report_snapshot_meta(
 pbx TEXT PRIMARY KEY,generation TEXT NOT NULL,ready INTEGER NOT NULL DEFAULT 0,
 bootstrap_after TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS report_visit_versions(
 seq INTEGER PRIMARY KEY,pbx TEXT,id TEXT,callid TEXT,queue TEXT,entered REAL,
 answered REAL,ended REAL,caller TEXT,agent TEXT,outcome TEXT,wait_seconds REAL,
 talk_seconds REAL,segment_ended_by TEXT,coverage TEXT,deleted INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS rsv_identity ON report_visit_versions(pbx,id,seq DESC);
CREATE INDEX IF NOT EXISTS rsv_range ON report_visit_versions(pbx,queue,entered DESC,id DESC,seq);
'''

for operation, prefix in (('INSERT','NEW'), ('DELETE','OLD'), ('UPDATE','NEW')):
    values = ','.join(prefix+'.'+field for field in FIELDS)
    SCHEMA += f'''CREATE TRIGGER IF NOT EXISTS report_snapshot_{operation.lower()}
      AFTER {operation} ON report_visits BEGIN
      INSERT INTO report_visit_versions({COLUMNS},deleted) VALUES({values},{int(operation=='DELETE')});
      END;'''

# Identity changes are unusual but must invalidate the old identity as well.
SCHEMA += f'''CREATE TRIGGER IF NOT EXISTS report_snapshot_identity_change
 AFTER UPDATE ON report_visits WHEN OLD.pbx<>NEW.pbx OR OLD.id<>NEW.id BEGIN
 INSERT INTO report_visit_versions({COLUMNS},deleted)
 VALUES({','.join('OLD.'+field for field in FIELDS)},1); END;'''


def bootstrap(db, pbx, *, limit=500):
    """Capture at most one indexed page of legacy facts per worker cycle."""
    db.execute('''INSERT OR IGNORE INTO report_snapshot_meta(pbx,generation)
                  VALUES(?,lower(hex(randomblob(16))))''', (pbx,))
    state = db.execute('SELECT ready,bootstrap_after FROM report_snapshot_meta WHERE pbx=?', (pbx,)).fetchone()
    if state[0]:
        return
    rows = db.execute('SELECT '+COLUMNS+' FROM report_visits WHERE pbx=? AND id>? ORDER BY id LIMIT ?',
                      (pbx,state[1],max(1,min(1000,int(limit))))).fetchall()
    for row in rows:
        # A concurrent new fact is already captured by the installed triggers.
        if not db.execute('SELECT 1 FROM report_visit_versions WHERE pbx=? AND id=? LIMIT 1',
                          (pbx,row[1])).fetchone():
            db.execute('INSERT INTO report_visit_versions('+COLUMNS+',deleted) VALUES('+
                       ','.join('?' for _ in FIELDS)+',0)',tuple(row))
    db.execute('UPDATE report_snapshot_meta SET bootstrap_after=?,ready=? WHERE pbx=?',
               (rows[-1][1] if rows else state[1],int(len(rows)<max(1,min(1000,int(limit)))),pbx))
