import tempfile
from pathlib import Path
import pytest
from sanequeue.reporting.store import Archive
from sanequeue.diagnostics.health import source_health
from sanequeue.diagnostics.rules import short_after_answer


@pytest.fixture
def archive():
    with tempfile.TemporaryDirectory() as folder:
        item = Archive(Path(folder) / 'history.sqlite3'); item.initialize()
        yield item


def checkpoint(archive, source, **value):
    archive.append([], checkpoint_source='health:'+source, checkpoint=value)


def test_quiet_traffic_current_sql_is_not_an_outage_and_no_raw_errors_leak(archive):
    checkpoint(archive, 'sql', ok=True, checked=1000,
               progress={'cel_caught_up':True, 'cdr_caught_up':True, 'cdr_overlap_caught_up':True})
    result = source_health(archive, now=1010)
    assert result['sources']['cel']['state'] == 'current'
    assert result['sources']['cdr']['state'] == 'current'
    assert result['sources']['queue_log']['state'] == 'unavailable'
    assert result['live_media_coverage'] == 'unavailable'
    checkpoint(archive, 'sql', ok=False, checked=1000, error='private password/raw SQL')
    result = source_health(archive, now=1010)
    assert result['sources']['cel']['state'] == 'error'
    assert 'private' not in str(result)


def test_missing_stale_backlog_clock_and_snapshot_are_distinct(archive):
    assert source_health(archive, now=1000)['sources']['cel']['state'] == 'unavailable'
    checkpoint(archive, 'cel', ok=True, checked=990, progress={'caught_up':True})
    assert source_health(archive, now=1000)['sources']['cel']['state'] == 'snapshot'
    assert source_health(archive, now=1200)['sources']['cel']['state'] == 'stale'
    checkpoint(archive, 'cel', ok=True, checked=2000, progress={'caught_up':True})
    assert source_health(archive, now=1000)['sources']['cel']['state'] == 'unknown'
    checkpoint(archive, 'sql', ok=True, checked=990, progress={'cel_caught_up':False})
    result = source_health(archive, now=1000)
    assert result['sources']['cel']['state'] == 'catching_up'
    assert result['sources']['cdr']['state'] == 'unknown'


def test_short_rule_does_not_accuse_users_or_label_transfers_as_disconnects():
    visit=dict(coverage='observed', outcome='answered', answered=100, ended=103, talk_seconds=3)
    result=short_after_answer(visit)
    assert result['confidence']=='suspected' and result['human_intent']=='unavailable'
    assert result['unit']=='queue_segment'
    for key,value in [('coverage','missing_entry'),('outcome','transferred'),('talk_seconds',None),('talk_seconds',float('nan')),('ended',99),('answered',True)]:
        assert short_after_answer({**visit,key:value}) is None
    assert short_after_answer({**visit,'talk_seconds':10,'ended':110}) is None
    with pytest.raises(ValueError):short_after_answer(visit,threshold_seconds=True)


def test_backlog_and_source_switch_are_not_misreported_as_healthy_sql(archive):
    checkpoint(archive,'sql',ok=True,checked=990,progress={'cel_caught_up':True,'cdr_caught_up':False})
    assert source_health(archive,now=1000)['sources']['cdr']['state']=='catching_up'
    checkpoint(archive,'cel',ok=True,checked=1190,progress={'caught_up':True})
    result=source_health(archive,now=1200)['sources']['cel']
    assert result['state']=='unknown' and result['reason']=='source_selection_unknown'
    assert result['alternatives']['snapshot']['state']=='snapshot'
