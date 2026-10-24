import sqlite3

import pytest

from sanequeue.actions.plans import plan
from sanequeue.realtime.inventory import inventory_projection, parse_health
from sanequeue.realtime.state import QueueState
from sanequeue.security.sessions import SessionRegistry


def test_inventory_merges_drivers_without_mutating_cached_snapshot():
    state={'inventory':{
        'extensions':dict(supported=True,observed_at=20,data=parse_health('extensions',[dict(objectname='100',devicestate='Not in use')])),
        'sip_extensions':dict(supported=True,observed_at=10,data=parse_health('sip_extensions',[dict(peer='200',status='OK (2 ms)')]))}}
    result=inventory_projection(state,'extensions')
    assert result['data']['total']==2
    assert result['data']['available']==2
    assert [r['technology'] for r in result['data']['endpoints']]==['PJSIP','SIP']
    assert state['inventory']['extensions']['data']['total']==1
    assert result['observed_at']==10
    assert inventory_projection({},'permissions')['supported'] is False


def test_sent_rtcp_does_not_erase_recent_received_round_trip_time():
    now=[100]
    state=QueueState(clock=lambda:now[0])
    state.ingest(dict(Event='Newchannel',Uniqueid='u',Channel='PJSIP/100-aaa'))
    state.ingest(dict(Event='RTCPReceived',Uniqueid='u',RTT='.025'))
    state.ingest(dict(Event='RTCPSent',Uniqueid='u',Report0IAJitter='10'))
    assert state.channels['u']['rtcp']['rtt_ms']==25
    now[0]=131
    state.ingest(dict(Event='RTCPSent',Uniqueid='u',Report0IAJitter='12'))
    assert state.channels['u']['rtcp']['rtt_ms'] is None
    assert state.channels['u']['rtcp']['direction']=='sent'


def test_park_rejects_third_participant_even_when_not_in_viewer_scope():
    state={'channels':{
        'a':dict(channel='PJSIP/100-a',queues=['q'],bridge='b'),
        'b':dict(channel='PJSIP/200-b',queues=['q'],bridge='b'),
        'c':dict(channel='PJSIP/300-c',queues=['private'],bridge='b')}}
    with pytest.raises(ValueError,match='two_party'):
        plan(state,'q','park','PJSIP/100-a')


def test_session_revocation_is_shared_and_tokens_are_never_stored(tmp_path):
    now=[1000]
    path=tmp_path/'sessions.sqlite'
    first=SessionRegistry(path,clock=lambda:now[0],ttl=300)
    second=SessionRegistry(path,clock=lambda:now[0],ttl=300)
    token=first.issue('supervisor','v1')
    assert second.active(token,'supervisor','v1')
    assert not second.active(token,'other','v1')
    assert not second.active(token,'supervisor','v2')
    with sqlite3.connect(path) as db:
        assert token not in str(db.execute('SELECT * FROM sessions').fetchall())
    second.revoke(token)
    assert not first.active(token,'supervisor','v1')
    token=first.issue('supervisor','v1')
    now[0]+=301
    assert not second.active(token,'supervisor','v1')


def test_queue_provenance_crosses_only_exact_local_halves_and_observed_bridges():
    state=QueueState()
    names={'caller':'PJSIP/200-aaa','one':'Local/100@from-queue-0001;1',
           'two':'Local/100@from-queue-0001;2','agent':'PJSIP/100-bbb',
           'unrelated':'Local/100@from-queue-0002;2'}
    for uid,name in names.items():
        state.ingest(dict(Event='Newchannel',Uniqueid=uid,Channel=name,Linkedid='shared-untrusted-value'))
    for bridge,ids in [('caller-bridge',['caller','one']),('agent-bridge',['two','agent'])]:
        for uid in ids:state.ingest(dict(Event='BridgeEnter',Uniqueid=uid,BridgeUniqueid=bridge))
    state.ingest(dict(Event='AgentConnect',Queue='q',Uniqueid='caller',DestUniqueid='one'))
    for uid in ('caller','one','two','agent'):assert state.channels[uid]['queues']==['q']
    assert state.channels['unrelated']['queues']==[]


def test_snapshot_queue_application_is_explicit_provenance_not_a_linkedid_guess():
    state=QueueState()
    state.ingest(dict(Event='QueueParams',Queue='q'))
    state.ingest(dict(Event='CoreShowChannel',Uniqueid='a',Channel='PJSIP/1-a',Application='Queue',ApplicationData='q,t,,,300'))
    assert state.channels['a']['queues']==['q']
    state.ingest(dict(Event='CoreShowChannel',Uniqueid='b',Channel='PJSIP/2-b',Application='Dial',ApplicationData='q'))
    assert state.channels['b']['queues']==[]


def test_agent_called_establishes_ringing_scope_without_marking_answered():
    state=QueueState()
    for uid,name in [('caller','PJSIP/200-a'),('one','Local/100@from-queue-1;1'),('two','Local/100@from-queue-1;2'),('agent','PJSIP/100-b')]:
        state.ingest(dict(Event='Newchannel',Uniqueid=uid,Channel=name))
    state.ingest(dict(Event='DialBegin',Uniqueid='two',DestUniqueid='agent'))
    state.ingest(dict(Event='AgentCalled',Queue='q',Uniqueid='caller',DestUniqueid='one'))
    state.ingest(dict(Event='DialBegin',Uniqueid='two',DestUniqueid='agent'))
    assert state.channels['agent']['queues']==['q']
    assert 'answered_at' not in state.channels['agent']


def test_observed_terminal_command_result_cannot_be_downgraded_by_late_timeout(tmp_path):
    from sanequeue.actions.ledger import ActionLedger
    ledger=ActionLedger(tmp_path/'ledger.sqlite',clock=lambda:100)
    ident=ledger.create('u','q','Park',{'Channel':'Local/exact;2'})
    ledger.reconcile({'last_event_at':101,'parked':{'default:71':dict(parkeechannel='Local/exact;2',observed_at=101)}})
    assert ledger.public(ident,'u',['q'])['state']=='confirmed'
    ledger.update(ident,'unknown','late_transport_timeout')
    assert ledger.public(ident,'u',['q'])['state']=='confirmed'
