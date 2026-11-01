#!/usr/bin/env python3
"""Measure a synthetic 30,000-segment CDR aggregation in an isolated database."""
from pathlib import Path
import sys
import tempfile
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sanequeue.reporting.store import Archive
from sanequeue.reporting.facts import project_batch
from sanequeue.reporting.cdr_builder import report


def main():
    with tempfile.TemporaryDirectory(prefix='sanequeue-cdr-benchmark-') as tmp:
        archive=Archive(Path(tmp)/'synthetic.db',min_free_bytes=0);archive.initialize()
        project_batch(archive,inventory={})
        start=1790812800
        with archive.writer() as db:
            db.executemany('INSERT INTO report_cdr VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                [('primary',f'synthetic-{i}',i+1,start+i*60,'','','100','09120000000','','',60,30,'ANSWERED','') for i in range(30000)])
            db.executemany('INSERT INTO report_cdr_parties VALUES(?,?,?,?,?)',
                [('primary',f'synthetic-{i}','PJSIP/100','outbound',start) for i in range(30000)])
        wall=time.monotonic();cpu=time.process_time()
        data=report(archive,start,start+31*86400,{},dict(columns=['src'],group_by=['direction']),numbers=False,secret=b'x'*32)
        wall=time.monotonic()-wall;cpu=time.process_time()-cpu
        assert data['source_segments']==30000 and data['rows'][0]['segments']==30000
        assert data['rows'][0]['average_billsec_seconds']==30
        print({'synthetic_segments':data['source_segments'],'groups':len(data['rows']),
               'wall_seconds':round(wall,3),'cpu_seconds':round(cpu,3),'database':'isolated'})


if __name__=='__main__':main()

