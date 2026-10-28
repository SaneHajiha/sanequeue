from datetime import datetime
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from sanequeue.reporting.store import Archive, Event, QueryDeadline
from sanequeue.reporting.facts import project_batch
from sanequeue.reporting.cdr_queries import page, summary


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
