import csv
from datetime import datetime
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from sanequeue.reporting.store import Archive, Event, QueryDeadline
from sanequeue.reporting.facts import project_batch
from sanequeue.reporting.cdr_queries import page, summary, unique_inbound, unique_inbound_csv, unique_inbound_document
from sanequeue.reporting.cdr_trend import report as trend


class CDRTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.archive = Archive(Path(self.temp.name) / 'history.db', min_free_bytes=0)
        self.archive.initialize()
        self.inventory = dict(observed_at=100, endpoints=[
            dict(technology='PJSIP', endpoint='100', category='extension'),
            dict(technology='SIP', endpoint='200', category='extension'),
            dict(technology='PJSIP', endpoint='provider-main', category='trunk')])

    def event(self, key, stamp=150, **values):
        row = dict(uniqueid='private-'+key, linkedid='same-private-conversation',
                   src='02199999999', dst='09123456789', channel='PJSIP/100-000000ab',
                   dstchannel='PJSIP/provider-main-000000ac', duration=40, billsec=30,
                   disposition='ANSWERED', recordingfile='private/audio.wav')
        row.update(values)
        return Event('cdr', key, stamp, 'CDR', row)

    def seed(self, *events, inventory=None):
        self.archive.append(list(events))
        while project_batch(self.archive, inventory=inventory or self.inventory)['processed']:
            pass

    def test_metadata_uses_channels_and_explicit_fields_only(self):
        self.seed(self.event('a', outbound_cid='Sales <+982199999999>', did='۰۲۱۱۲۳۴۵۶۷۸'),
                  self.event('b', 160), self.event('c', 170,
                  channel='PJSIP/provider-main-000000af', dstchannel='SIP/200-000000ae'))
        rows = {r['id']: r for r in page(self.archive, 100, 200)['rows']}
        self.assertEqual(rows['a']['internal_caller_ext'], '100')
        self.assertEqual(rows['a']['outbound_cid'], '+982199999999')
        self.assertEqual(rows['a']['did'], '02112345678')
        self.assertIsNone(rows['b']['outbound_cid'])
        self.assertEqual(rows['c']['direction'], 'inbound')
        self.assertIsNone(rows['c']['internal_caller_ext'])
        self.assertEqual(rows['a']['trunk'], 'PJSIP/provider-main')
        encoded = str(rows)
        for secret in ('private/audio', 'same-private-conversation', 'private-a', '000000ab'):
            self.assertNotIn(secret, encoded)
        self.assertFalse(page(self.archive, 100, 200)['audio_granted'])

    def test_summary_endpoint_uses_observed_inventory_and_keeps_unknown(self):
        self.seed(self.event('known'), self.event('unknown', 160,
                  channel='PJSIP/not-in-inventory-000000ab', dstchannel=''))
        data = summary(self.archive, 100, 200)
        endpoints = {row['endpoint']: row for row in data['endpoints']}
        self.assertEqual(endpoints['PJSIP/100']['segments_started'], 1)
        self.assertEqual(endpoints['PJSIP/100']['answered_segments'], 1)
        self.assertEqual(endpoints[None]['segments_started'], 1)
        self.assertEqual(sum(row['segments_started'] for row in data['endpoints']),
                         data['totals']['segments_started'])

    def test_endpoint_performance_dispositions_remain_distinct(self):
        self.seed(self.event('answered'),self.event('busy',151,disposition='BUSY'),
                  self.event('no-answer',152,disposition='NO ANSWER'),
                  self.event('failed',153,disposition='FAILED'),self.event('unknown',154,disposition='UNKNOWN'))
        data=summary(self.archive,100,200);row=data['endpoints'][0]
        self.assertEqual(row['segments_started'],5)
        self.assertEqual((row['answered_segments'],row['unanswered_segments'],row['unknown_disposition_segments']),(1,3,1))
        self.assertEqual((row['no_answer_segments'],row['busy_segments'],row['other_failed_segments']),(1,1,1))

    def test_multiple_observed_endpoints_are_bounded_and_do_not_include_unknown(self):
        self.seed(self.event('one'),self.event('two',151,channel='SIP/200-000000ab'),
                  self.event('unknown',152,channel='SIP/300-000000ab'))
        data=summary(self.archive,100,200,{'endpoint':'PJSIP/100, SIP/200'})
        self.assertEqual(data['totals']['segments_started'],2)
        self.assertEqual({row['endpoint'] for row in data['endpoints']},{'PJSIP/100','SIP/200'})
        for bad in ('PJSIP/100,',','.join(['SIP/200']*21),'PJSIP/100,SIP/200\' OR 1'):
            with self.assertRaises(ValueError):summary(self.archive,100,200,{'endpoint':bad})

    def test_unique_inbound_counts_numbers_not_segments_or_people(self):
        stamp=datetime(2026,10,24,9,tzinfo=ZoneInfo('Asia/Tehran')).timestamp()
        inbound=dict(channel='PJSIP/provider-main-000000af',dstchannel='SIP/200-000000ae')
        self.seed(self.event('one',stamp,src='09123456789',**inbound),
                  self.event('two',stamp+10,src='۰۹۱۲۳۴۵۶۷۸۹',**inbound),
                  self.event('three',stamp+86400,src='09123456789',**inbound),
                  self.event('unknown',stamp+20,src='anonymous',**inbound),
                  self.event('outbound',stamp+30,src='09999999999'))
        data=unique_inbound(self.archive,stamp,stamp+2*86400)
        self.assertEqual((data['total_unique'],data['known_number_segments'],data['unknown_number_segments']),(1,3,1))
        self.assertEqual([row['unique_numbers'] for row in data['by_day']],[1,1])
        self.assertEqual((data['repeat_numbers'],data['repeat_number_percent']),(1,100.0))
        self.assertEqual([row['repeat_numbers'] for row in data['by_day']],[1,0])
        self.assertEqual(data['contract']['repeat_percent_denominator'],'known_distinct_inbound_source_numbers')
        self.assertNotIn('09123456789',str(data));self.assertFalse(data['contract']['unique_conversations_proven'])
        self.assertEqual(unique_inbound(self.archive,stamp,stamp+2*86400,{'hour_from':9,'hour_to':9})['total_unique'],1)
        with self.assertRaises(ValueError):unique_inbound(self.archive,stamp,stamp+2*86400,{'direction':'outbound'})
        with patch('sanequeue.reporting.cdr_queries.MAX_UNIQUE_INBOUND_SEGMENTS',2):
            limited=unique_inbound(self.archive,stamp,stamp+2*86400)
        self.assertEqual(limited['state'],'limited');self.assertNotIn('total_unique',limited)

    def test_repeat_number_share_counts_segments_not_proven_calls(self):
        stamp=datetime(2026,10,24,9,tzinfo=ZoneInfo('Asia/Tehran')).timestamp()
        inbound=dict(channel='PJSIP/provider-main-000000af',dstchannel='SIP/200-000000ae')
        self.seed(self.event('a',stamp,src='09120000001',**inbound),
                  self.event('b',stamp+1,src='09120000001',**inbound),
                  self.event('c',stamp+2,src='09120000002',**inbound),
                  self.event('d',stamp+3,src='anonymous',**inbound))
        data=unique_inbound(self.archive,stamp,stamp+86400)
        self.assertEqual((data['total_unique'],data['repeat_numbers'],data['repeat_number_percent']),(2,1,50.0))
        self.assertEqual(data['by_day'][0]['repeat_numbers'],1)
        self.assertNotIn('09120000001',str(data))
        self.assertIn('not_proven_repeat_calls',data['contract']['repeat'])
        empty=unique_inbound(self.archive,stamp+86400,stamp+172800)
        self.assertEqual(empty['repeat_numbers'],0)
        self.assertIsNone(empty['repeat_number_percent'])
        rows=list(csv.DictReader(io.StringIO(unique_inbound_csv(empty,'en').decode('utf-8-sig'))))
        self.assertEqual(rows[0]['period_distinct_numbers'],'0')
        self.assertEqual(rows[0]['period_multi_segment_percent'],'')
        self.assertEqual(rows[0]['day'],'')
        with self.assertRaises(ValueError):unique_inbound_csv({'state':'limited'},'fa')
        from sanequeue.reporting.pdf_stream import PdfFailure
        limited=dict(data,by_day=data['by_day']*101)
        with self.assertRaises(PdfFailure):unique_inbound_document(limited,'en','pdf')

    def test_organizational_cdr_scope_is_historical_and_fails_closed(self):
        from sanequeue.security.unit_scope import UnitScopeStore
        store=UnitScopeStore(Path(self.temp.name)/'units.db');store.initialize()
        org=store.create_unit('Org','organization');dept=store.create_unit('Dept','department',org)
        unit=store.create_unit('Sales','unit',dept);other=store.create_unit('Support','unit',dept)
        store.assign_endpoint(unit,'PJSIP/100',100,160)
        store.assign_endpoint(other,'PJSIP/100',160,300)
        store.assign_endpoint(other,'SIP/200',100,300)
        store.grant('manager',unit,'call_details');store.grant('manager',unit,'summary')
        self.seed(self.event('allowed',150),self.event('after-transfer',160),
                  self.event('other',155,channel='PJSIP/provider-main-000000aa',dstchannel='SIP/200-000000ab'),
                  self.event('unknown',156,channel='unknown',dstchannel=''))
        detailed=store.resolve('manager','call_details',100,300)
        self.assertEqual([r['id'] for r in page(self.archive,100,300,unit_scope=detailed)['rows']],['allowed'])
        aggregate=summary(self.archive,100,300,unit_scope=store.resolve('manager','summary',100,300))
        self.assertEqual(aggregate['totals']['segments_started'],1)
        self.assertEqual(aggregate['scope'],'organization_unit')
        empty=store.resolve('other','call_details',100,300)
        self.assertEqual(page(self.archive,100,300,unit_scope=empty)['rows'],[])
        with self.assertRaises(ValueError):summary(self.archive,100,300,unit_scope=detailed)
        with self.assertRaises(ValueError):page(self.archive,100,301,unit_scope=detailed)

    def test_unit_summary_resolves_scope_and_rechecks_revocation(self):
        from sanequeue.security.unit_scope import UnitScopeStore, ScopeConflict
        from sanequeue.reporting.unit_cdr import summary as scoped_summary, UnitAccessDenied
        store=UnitScopeStore(Path(self.temp.name)/'units.db');store.initialize()
        org=store.create_unit('Org','organization');dept=store.create_unit('Dept','department',org)
        unit=store.create_unit('Sales','unit',dept)
        store.assign_endpoint(unit,'PJSIP/100',100,200)
        grant=store.grant('manager',unit,'summary')
        self.seed(self.event('allowed',150),self.event('out-of-period',210))
        data=scoped_summary(self.archive,store,'manager',100,300,{'direction':'outbound'})
        self.assertEqual(data['totals']['segments_started'],1)
        self.assertNotIn('trunk_traffic',data);self.assertNotIn('endpoints',data)
        self.assertNotIn('09123456789',str(data))
        with self.assertRaises(ValueError):
            scoped_summary(self.archive,store,'manager',100,300,{'src':'09123456789'})
        with self.assertRaises(UnitAccessDenied):
            scoped_summary(self.archive,store,'other',100,300)
        original=summary
        def revoke_during_query(*args,**kwargs):
            result=original(*args,**kwargs);store.revoke(grant);return result
        with patch('sanequeue.reporting.unit_cdr.cdr_queries.summary',side_effect=revoke_during_query):
            with self.assertRaises(ScopeConflict):scoped_summary(self.archive,store,'manager',100,300)
        with self.assertRaises(UnitAccessDenied):
            scoped_summary(self.archive,store,'manager',100,300)

    def test_trend_buckets_directions_and_limits(self):
        stamp=datetime(2026,10,24,9,tzinfo=ZoneInfo('Asia/Tehran')).timestamp()
        self.seed(self.event('out',stamp),self.event('in',stamp+3600,
            channel='PJSIP/provider-main-000000af',dstchannel='SIP/200-000000ae'),
            self.event('unclassified',stamp+86400,channel='unknown',dstchannel=''))
        hourly=trend(self.archive,stamp,stamp+2*86400,bucket='hour')
        self.assertEqual([row['outbound'] for row in hourly['rows']],[1,0,0])
        self.assertEqual([row['inbound'] for row in hourly['rows']],[0,1,0])
        self.assertEqual(hourly['rows'][-1]['unknown'],1)
        self.assertEqual(len(trend(self.archive,stamp,stamp+2*86400,bucket='day')['rows']),2)
        self.assertEqual(trend(self.archive,stamp,stamp+2*86400,bucket='week')['rows'][0]['period'],'2026-10-24')
        self.assertEqual(trend(self.archive,stamp,stamp+2*86400,bucket='month')['rows'][0]['period'],'2026-10')
        self.assertEqual(trend(self.archive,stamp,stamp+2*86400,bucket='month',calendar='persian')['rows'][0]['period'],'1405/08')
        with self.assertRaises(ValueError):trend(self.archive,stamp,stamp+86400,bucket='year')
        with patch('sanequeue.reporting.cdr_trend.MAX_SEGMENTS',2),self.assertRaises(QueryDeadline):
            trend(self.archive,stamp,stamp+2*86400)
        with patch('sanequeue.reporting.cdr_trend.MAX_BUCKETS',1),self.assertRaises(QueryDeadline):
            trend(self.archive,stamp,stamp+2*86400,bucket='hour')

    def test_numeric_filters_normalize_unicode_and_never_interpolate(self):
        self.seed(self.event('a', outbound_cnum='02177777777', did='8001'),
                  self.event('b', 160, src='123', dst='444'))
        self.assertEqual(len(page(self.archive, 100, 200, dict(origin='۱۰۰'))['rows']), 2)
        self.assertEqual(len(page(self.archive, 100, 200, dict(party='۰۲۱۷۷۷۷۷۷۷۷'))['rows']), 1)
        self.assertEqual(len(page(self.archive, 100, 200, dict(dst='912', match='partial'))['rows']), 1)
        self.assertEqual(len(page(self.archive, 100, 200, dict(src_length=3, dst_length=3))['rows']), 1)
        self.assertEqual(len(page(self.archive, 100, 200, dict(did='8001'))['rows']), 1)
        for filters in (dict(src="123' OR 1=1"), dict(dst='%'), dict(dst='12', match='partial'),
                        dict(src_length=0), dict(duration_min=5, duration_max=4), dict(weekdays=[7])):
            with self.subTest(filters=filters), self.assertRaises(ValueError):
                page(self.archive, 100, 200, filters)

    def test_keyset_full_range_summary_and_unknown_samples(self):
        self.seed(*(self.event('%03d' % n, billsec=None if n == 0 else 0,
                              duration=None if n == 0 else 10) for n in range(205)))
        one = page(self.archive, 100, 200, limit=999)
        two = page(self.archive, 100, 200, before=one['next'])
        three = page(self.archive, 100, 200, before=two['next'])
        self.assertEqual([len(x['rows']) for x in (one,two,three)], [100,100,5])
        self.assertEqual(len({r['id'] for x in (one,two,three) for r in x['rows']}), 205)
        totals = summary(self.archive, 100, 200)['totals']
        self.assertEqual(totals['segments_started'], 205)
        self.assertEqual(totals['unknown_billsec_count'], 1)
        self.assertEqual(totals['known_billsec_count'], 204)
        self.assertEqual(totals['known_billsec_sum'], 0)
        self.assertEqual(totals['average_answered_billsec'], 0)

    def test_all_unknown_is_not_zero_and_filter_excludes_unknown(self):
        self.seed(self.event('a', duration=None, billsec=None, disposition=None))
        totals = summary(self.archive, 100, 200)['totals']
        self.assertIsNone(totals['known_duration_sum'])
        self.assertIsNone(totals['average_billsec_seconds'])
        self.assertEqual(totals['unknown_disposition_segments'], 1)
        self.assertEqual(page(self.archive, 100, 200, dict(billsec_min=0))['rows'], [])

    def test_tehran_hours_wrap_weekdays_and_half_open_range(self):
        stamp = datetime(2026,10,24,23,30,tzinfo=ZoneInfo('Asia/Tehran')).timestamp()
        self.seed(self.event('saturday', stamp), self.event('sunday', stamp+7200))
        result = page(self.archive, stamp, stamp+86400, dict(hour_from=23,hour_to=2,weekdays=[0]))
        self.assertEqual([r['id'] for r in result['rows']], ['saturday'])
        self.assertEqual(page(self.archive, stamp, stamp+7200)['rows'][0]['id'], 'saturday')

    def test_daily_time_filter_is_inclusive_and_handles_overnight(self):
        stamp=datetime(2026,10,24,9,30,0,tzinfo=ZoneInfo('Asia/Tehran')).timestamp()
        self.seed(self.event('first',stamp),self.event('later',stamp+90),self.event('night',stamp+14*3600))
        result=page(self.archive,stamp,stamp+86400,dict(time_from='09:30',time_to='09:30'))
        self.assertEqual([r['id'] for r in result['rows']],['first'])
        result=page(self.archive,stamp,stamp+86400,dict(time_from='23:00',time_to='09:30'))
        self.assertEqual({r['id'] for r in result['rows']},{'first','night'})
        with self.assertRaises(ValueError):page(self.archive,stamp,stamp+86400,dict(time_from='25:00'))

    def test_exact_inventory_frozen_across_replay_and_late_version(self):
        first = self.event('a')
        self.seed(first, self.event('b', 160, dstchannel='PJSIP/provider-main-other-000000af'))
        changed = dict(observed_at=999, endpoints=[])
        with self.archive.writer() as db:
            db.execute('DELETE FROM report_projection')
        self.seed(first, inventory=changed)
        self.assertEqual(page(self.archive,100,200)['rows'][1]['trunk'], 'PJSIP/provider-main')
        self.seed(self.event('a', billsec=35), inventory=changed)
        rows = {r['id']:r for r in page(self.archive,100,200)['rows']}
        self.assertEqual(rows['a']['trunk'], 'PJSIP/provider-main')
        self.assertEqual(rows['a']['inventory_observed'], 100)
        self.assertIsNone(rows['b']['trunk'])
        self.assertEqual(rows['a']['billsec'], 35)

    def test_group_and_read_limits_fail_explicitly(self):
        self.seed(self.event('a'))
        with patch('sanequeue.reporting.cdr_queries.MAX_GROUPS', 1), self.assertRaises(QueryDeadline):
            summary(self.archive,100,200)
        with patch.object(self.archive,'reader',side_effect=QueryDeadline('deadline')), self.assertRaises(QueryDeadline):
            page(self.archive,100,200)

    def test_upgrade_cannot_classify_old_identity_using_new_inventory_epoch(self):
        self.seed(self.event('a'))
        with self.archive.writer() as db:
            db.execute('DELETE FROM report_cdr_extra')
            db.execute('DELETE FROM report_projection')
        changed=dict(self.inventory,observed_at=999)
        self.seed(self.event('a'),inventory=changed)
        row=page(self.archive,100,200)['rows'][0]
        self.assertIsNone(row['trunk'])
        self.assertEqual(row['trunk_provenance'],'inventory_epoch_mismatch')


if __name__ == '__main__':
    unittest.main()
