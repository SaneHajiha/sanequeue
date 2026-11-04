from pathlib import Path
import sqlite3
import tempfile
import unittest
from contextlib import closing
from sanequeue.reporting.cdr_reasons import Reasons
from sanequeue.reporting.store import QueryDeadline


class CDRReasonTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'labels.sqlite3';self.store=Reasons(self.path);self.store.initialize()

    def test_unlabeled_is_distinct_and_pbx_isolated(self):
        self.store.set('a','پشتیبانی','نصب','حل شد','admin')
        self.store.set('b','','','ارجاع','admin')
        data=self.store.summarize(['a','b','c'])
        self.assertEqual((data['segments'],data['labelled'],data['unlabelled']),(3,1,2))
        self.assertEqual(sum(row['count'] for row in data['rows']),3)
        other=Reasons(self.path,pbx='other');other.initialize()
        self.assertEqual(other.get('a')['reason'],'')
        self.assertEqual(other.summarize(['a'])['unlabelled'],1)
        with self.assertRaises(QueryDeadline):self.store.summarize(['x']*50001)
        with self.assertRaises(ValueError):self.store.set('x','','sub','','admin')

    def test_audit_failure_rolls_back_label_change(self):
        self.store.set('a','before','','','admin')
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("CREATE TRIGGER reject_cdr_audit BEFORE INSERT ON cdr_reason_audit BEGIN SELECT RAISE(ABORT,'rejected'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.store.set('a','after','','','admin')
        self.assertEqual(self.store.get('a')['reason'],'before')

    def test_timeline_groups_known_labels_and_unlabeled_without_guessing(self):
        self.store.set('a','پشتیبانی','','','admin')
        hour=self.store.summarize(['a','b'],timestamps=[1792886400,1792886400],bucket='hour')
        self.assertEqual(hour['bucket'],'hour')
        self.assertEqual({(row['period'],row['reason'],row['count']) for row in hour['timeline']},
                         {('03','پشتیبانی',1),('03','',1)})
        weekday=self.store.summarize(['a','b'],timestamps=[1792886400-86400,1792886400],bucket='weekday')
        self.assertEqual({row['period'] for row in weekday['timeline']},{'0','1'})
        day=self.store.summarize(['a'],timestamps=[1792886400],bucket='day')
        self.assertEqual(day['timeline'][0]['period'],'2026-10-25')
        month=self.store.summarize(['a'],timestamps=[1792886400],bucket='month')
        self.assertEqual(month['timeline'][0]['period'],'1405/08')
        with self.assertRaises(ValueError):self.store.summarize(['a'],timestamps=[1792886400],bucket='year')

    def test_catalog_soft_deactivation_preserves_existing_labels(self):
        self.store.set('a','پشتیبانی','نصب','حل شد','admin')
        self.assertEqual(len(self.store.set_catalog('پشتیبانی','نصب',True,'admin')),1)
        self.assertEqual(self.store.set_catalog('پشتیبانی','نصب',False,'admin'),[])
        self.assertEqual(self.store.get('a')['reason'],'پشتیبانی')
        with self.assertRaises(ValueError):self.store.set_catalog('','','yes','admin')
        with closing(self.store.connect()) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM cdr_reason_catalog_audit').fetchone()[0],2)


if __name__=='__main__':unittest.main()
