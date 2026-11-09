from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from sanequeue.security.unit_scope import ScopeConflict, ScopeUnavailable, UnitScopeStore


class UnitScopeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'units.sqlite3';self.store=UnitScopeStore(self.path)
        self.store.initialize()
        self.org=self.store.create_unit('سازمان','organization')
        self.dept=self.store.create_unit('خدمات پس از فروش','department',self.org)
        self.unit=self.store.create_unit('خدمات','unit',self.dept)
        self.customer=self.store.create_unit('امور مشتریان','subunit',self.unit)
        self.agents=self.store.create_unit('امور نمایندگان','subunit',self.unit)

    def test_explicit_descendants_and_separate_capabilities(self):
        self.store.assign_endpoint(self.customer,'PJSIP/101',10,100)
        self.store.assign_endpoint(self.agents,'PJSIP/102',10,100)
        self.store.grant('manager',self.unit,'summary')
        self.assertEqual(self.store.resolve('manager','summary',10,100)['assignments'],[])
        self.store.grant('manager',self.unit,'summary',descendants=True)
        scoped=self.store.resolve('manager','summary',10,100)
        self.assertEqual({r['endpoint'] for r in scoped['assignments']},{'PJSIP/101','PJSIP/102'})
        self.assertEqual(self.store.resolve('manager','full_numbers',10,100)['assignments'],[])
        self.assertEqual(self.store.resolve('other','summary',10,100)['assignments'],[])

    def test_access_workflow_is_atomic_and_retry_safe(self):
        self.store.assign_endpoint(self.customer,'PJSIP/100',10,40)
        before=self.store.inventory()
        args=dict(username='employee',unit_id=None,
                  new_unit=dict(name='Field support',kind='subunit',parent=self.unit),
                  endpoint='PJSIP/100',queue='8001',start=10,end=40,
                  capabilities=['call_details','recording_play'],actor='admin')
        with self.assertRaises(ScopeConflict):
            self.store.configure_access(**args)
        self.assertEqual(self.store.inventory(),before)
        args['endpoint']='SIP/200'
        unit=self.store.configure_access(**args)
        self.assertEqual([row['endpoint'] for row in self.store.resolve('employee','recording_play',10,40)['assignments']],['SIP/200'])
        self.assertEqual(self.store.resolve('employee','recording_download',10,40)['assignments'],[])
        after=self.store.inventory()
        self.assertEqual(self.store.configure_access(**dict(args,unit_id=unit,new_unit=None)),unit)
        self.assertEqual(self.store.inventory(),after)

    def test_historical_assignment_is_half_open_and_cannot_overlap(self):
        first=self.store.assign_endpoint(self.customer,'PJSIP/101',10)
        with self.assertRaises(ScopeConflict):self.store.assign_endpoint(self.agents,'PJSIP/101',20)
        self.store.close_interval(first,30)
        self.store.assign_endpoint(self.agents,'PJSIP/101',30,60)
        self.store.grant('manager',self.customer,'call_details')
        self.assertEqual(len(self.store.resolve('manager','call_details',10,30)['assignments']),1)
        self.assertEqual(self.store.resolve('manager','call_details',30,40)['assignments'],[])
        with self.assertRaises(ScopeConflict):self.store.assign_endpoint(self.unit,'PJSIP/101',29,31)

    def test_revocation_invalidates_scope_and_membership_does_not_authorize(self):
        self.store.assign_endpoint(self.customer,'PJSIP/101',10,100)
        self.store.add_member(self.customer,'employee',10,100)
        self.assertEqual(self.store.resolve('employee','summary',10,100)['assignments'],[])
        grant=self.store.grant('employee',self.customer,'summary')
        issued=self.store.resolve('employee','summary',10,100)
        self.assertTrue(self.store.still_current(issued))
        self.store.revoke(grant)
        self.assertFalse(self.store.still_current(issued))
        self.assertEqual(self.store.resolve('employee','summary',10,100)['assignments'],[])
        with self.assertRaises(ScopeConflict):self.store.revoke(grant)

    def test_recording_reference_is_owner_bound_expires_and_follows_revision(self):
        self.store.assign_endpoint(self.customer,'PJSIP/101',10,100)
        grant=self.store.grant('manager',self.customer,'call_details')
        scope=self.store.resolve('manager','call_details',10,100)
        with patch('sanequeue.security.unit_scope.time.time',return_value=1000):
            token=self.store.issue_recording_refs('manager',scope,[('private-id',20)])[0]
            self.assertEqual(self.store.issue_recording_refs('manager',scope,[('private-id',20)]),[token])
            self.assertEqual(self.store.load_recording_ref('manager',token)['source_key'],'private-id')
            with self.assertRaises(ScopeConflict):self.store.load_recording_ref('someone',token)
        with patch('sanequeue.security.unit_scope.time.time',return_value=1900):
            with self.assertRaises(ScopeConflict):self.store.load_recording_ref('manager',token)
        self.store.revoke(grant)
        with patch('sanequeue.security.unit_scope.time.time',return_value=1001):
            with self.assertRaises(ScopeConflict):self.store.load_recording_ref('manager',token)

    def test_rejects_invalid_parent_times_capabilities_and_endpoints(self):
        with self.assertRaises(ValueError):self.store.create_unit('نام','subunit',self.dept)
        with self.assertRaises(ValueError):self.store.create_unit('نام','organization',self.org)
        with self.assertRaises(ValueError):self.store.grant('manager',self.unit,'all')
        with self.assertRaises(ValueError):self.store.assign_endpoint(self.customer,'09120000000',10)
        for start,end in [(10,10),(10,9),(float('nan'),20)]:
            with self.assertRaises(ValueError):self.store.assign_endpoint(self.customer,'PJSIP/101',start,end)

    def test_pbx_isolation_and_uninitialized_store_fail_closed(self):
        self.store.assign_endpoint(self.customer,'SIP/101',10,100)
        self.store.grant('manager',self.customer,'summary')
        other=UnitScopeStore(self.path,pbx='other');other.initialize()
        self.assertEqual(other.resolve('manager','summary',10,100)['assignments'],[])
        missing=UnitScopeStore(Path(self.tmp.name)/'missing.sqlite3')
        with self.assertRaises(ScopeUnavailable):missing.resolve('manager','summary',10,100)

    def test_api_tokens_are_hashed_expire_and_die_with_identity(self):
        with patch('sanequeue.security.unit_scope.time.time',return_value=1000):
            item=self.store.issue_token('manager',1)
            self.assertEqual(self.store.authenticate_token(item['token'])['username'],'manager')
            with self.store._db() as db:
                row=db.execute('SELECT * FROM unit_api_tokens').fetchone()
                self.assertNotIn(item['token'],tuple(row))
            for _ in range(120):self.assertIsNotNone(self.store.authenticate_token(item['token'],consume=True))
            with self.assertRaises(ScopeConflict):self.store.authenticate_token(item['token'],consume=True)
        with patch('sanequeue.security.unit_scope.time.time',return_value=1000+86401):
            self.assertIsNone(self.store.authenticate_token(item['token']))
        with patch('sanequeue.security.unit_scope.time.time',return_value=1001):
            self.store.revoke_subject('manager')
            self.assertIsNone(self.store.authenticate_token(item['token']))


if __name__=='__main__':unittest.main()
