"""Asterisk 20 AMI QueueStatus adapter: read-only, queue-scoped, no external dependencies.

Used only over the pre-established SSH loopback tunnel. It never sends a call-changing action.
"""
import socket
import time
from collections import OrderedDict


def _field(event, *names, default=''):
    """AMI field names are case-insensitive; upstream versions vary."""
    lowered = {str(k).lower(): v for k, v in event.items()}
    for name in names:
        if name.lower() in lowered and lowered[name.lower()] is not None:
            return lowered[name.lower()]
    return default


def _as_int(value, default=0):
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def parse_queue_events(events, queue_name='8001'):
    """Convert AMI QueueStatus events into the SaneQueue data shape.

    Asterisk field names are preserved where supported. No mutation of server state.
    """
    from qpanel.ami_targets import validate_target
    validate_target('127.0.0.1', 5038, queue_name)
    queues = OrderedDict()
    entries_seen = False
    now = int(time.time())
    for event in events:
        name = event.get('Event')
        qname = str(event.get('Queue') or queue_name)
        if queue_name != '*' and qname != queue_name:
            continue
        if name == 'QueueParams':
            queues[qname] = {
                'Strategy': event.get('Strategy', '—'),
                'Calls': str(_as_int(event.get('Calls'))),
                'Holdtime': str(_as_int(event.get('Holdtime'))) if event.get('Holdtime') not in (None,'') else '',
                'TalkTime': str(_as_int(event.get('TalkTime'))) if event.get('TalkTime') not in (None,'') else '',
                'Completed': str(_as_int(event.get('Completed'))),
                'Abandoned': str(_as_int(event.get('Abandoned'))),
                'ServicelevelPerf': _field(event,'ServiceLevelPerf',default=''),
                'ServiceLevelSeconds': _field(event,'ServiceLevel',default=''),
                'ServicelevelPerf2': _field(event,'ServiceLevelPerf2',default=''),
                'members': {},
                'entries': {},
            }
        elif name == 'QueueMember':
            if qname not in queues:
                continue
            interface = str(event.get('Location') or event.get('Interface') or '')
            if not interface:
                continue
            last_call = _as_int(event.get('LastCall'))
            last_call_ago = '—' if last_call <= 0 else f'{max(0, now-last_call)} sec ago'
            last_pause = _as_int(event.get('LastPause'))
            queues[qname]['members'][interface] = {
                'Name': _field(event,'MemberName','Name',default='') or interface,
                'Location': interface,
                'StateInterface': event.get('StateInterface') or interface,
                'Membership': event.get('Membership', ''),
                'Status': str(event.get('Status', '0')),
                'Paused': str(event.get('Paused', '0')),
                'PausedReason': event.get('PausedReason', ''),
                'InCall': str(event.get('InCall', '0')),
                'CallsTaken': str(_as_int(event.get('CallsTaken'))),
                'Penalty': str(_as_int(event.get('Penalty'))),
                'LastCall': last_call,
                'LastCallAgo': last_call_ago,
                'LastPause': last_pause,
                'LastPauseAgo': f'{max(0,now-last_pause)} sec ago' if last_pause > 0 else '—',
            }
        elif name == 'QueueEntry':
            if qname not in queues:
                continue
            channel = str(event.get('Channel') or event.get('Uniqueid') or '')
            if not channel:
                continue
            entries_seen = True
            queues[qname]['entries'][channel] = {
                'Channel': channel,
                'CallerIDNum': event.get('CallerIDNum', ''),
                'CallerIDName': event.get('CallerIDName', ''),
                # Only explicitly tagged source is trusted; queue status has no standard trunk field.
                'SourceTrunk': _field(event,'IngressTrunk','SourceTrunk',default=''),
                'Uniqueid': _field(event,'Uniqueid',default=''),
                'Position': str(_as_int(event.get('Position'))),
                'Priority': str(_as_int(event.get('Priority'))),
                'Wait': str(_as_int(event.get('Wait'))),
            }
    if queue_name == '*':
        if not queues:
            raise RuntimeError('QueueStatus returned no queues')
    elif queue_name not in queues:
        raise RuntimeError('Selected queue missing from QueueStatus events')
    if entries_seen:
        # Prefer the actual queue entries when available, independently for each queue.
        for qname, q in queues.items():
            if q['entries']:
                q['Calls'] = str(len(q['entries']))
    return dict(queues)


def read_queue_data(host, port, user, password, queue_name='8001'):
    from qpanel.ami_targets import validate_target
    host, port, queue_name = validate_target(host, port, queue_name)
    # Reuse tested read-only protocol framing for AMI; no control permissions used here.
    from AMI_READONLY_TEST import ReadOnlyAMI
    client = None
    try:
        client = ReadOnlyAMI(host, int(port), timeout=5)
        client.login(user, password)
        client.sock.settimeout(8)
        client.deadline = time.monotonic() + 9
        options={'Action':'QueueStatus','ActionID':'sq-live-queue'}
        if queue_name != '*': options['Queue']=queue_name
        client.send(**options)
        events = []
        completed = False
        deadline = time.monotonic() + 9
        while time.monotonic() < deadline:
            try:
                event = client.read_packet()
            except socket.timeout as exc:
                raise TimeoutError('QueueStatus timed out') from exc
            if event.get('ActionID') not in ('sq-live-queue', None):
                continue
            if event.get('Response') == 'Error':
                raise PermissionError('QueueStatus denied')
            if event.get('Event') == 'QueueStatusComplete':
                completed = True
                break
            if event.get('Event') in ('QueueParams','QueueMember','QueueEntry'):
                events.append(event)
            if len(events) > 12000:
                raise RuntimeError('Excessive QueueStatus data')
        if not completed:
            raise TimeoutError('QueueStatus did not complete')
        return parse_queue_events(events, queue_name)
    finally:
        if client is not None:
            client.close()
