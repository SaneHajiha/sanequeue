"""Read-only AMI PBX capability and health inventory with classified, redacted errors.

Action permissions and event classes are independent in Asterisk AMI. Never
escalate privileges automatically and never issue mutating actions here.
"""
import secrets
import time
import socket
from AMI_READONLY_TEST import ReadOnlyAMI
from qpanel.ami_targets import validate_target

_ACTIONS = {
    'channels': ('CoreShowChannels', 'CoreShowChannel', 'CoreShowChannelsComplete'),
    'extensions': ('PJSIPShowEndpoints', 'EndpointList', 'EndpointListComplete'),
    'parking': ('ParkedCalls', 'ParkedCall', 'ParkedCallsComplete'),
    'contacts': ('PJSIPShowContacts', 'ContactList', 'ContactListComplete'),
    'registrations': ('PJSIPShowRegistrationsOutbound', 'OutboundRegistrationDetail', 'OutboundRegistrationDetailComplete'),
    'sip_extensions': ('SIPpeers', 'PeerEntry', 'PeerlistComplete'),
    'sip_registrations': ('SIPshowregistry', 'RegistryEntry', 'RegistrationsComplete'),
}
_CAPABILITIES = ('QueueStatus', 'QueueSummary', 'CoreShowChannels', 'PJSIPShowEndpoints',
                 'PJSIPShowContacts', 'PJSIPShowRegistrationsOutbound', 'ParkedCalls',
                 'QueuePause', 'QueueAdd', 'QueueRemove', 'QueuePenalty',
                 'QueueChangePriorityCaller', 'Hangup', 'Originate', 'Redirect',
                 'BlindTransfer', 'Park', 'BridgeList', 'PresenceStateList', 'ListCommands')


def _unavailable_reason(message):
    """Classify only; avoid reflecting AMI arbitrary strings into the browser."""
    msg = str(message or '').lower()
    if any(t in msg for t in ('permission', 'privilege', 'denied', 'not authorized', 'not permitted')):
        return 'action_permission_denied'
    if any(t in msg for t in ('unknown', 'not registered', 'does not exist', 'not found', 'invalid action')):
        return 'action_or_module_unavailable'
    if 'not connected' in msg:
        return 'not_connected'
    return 'ami_action_rejected'


def parse_health(kind, events):
    if kind == 'channels':
        rows = [{'state':str(e.get('ChannelStateDesc') or 'Unknown'),
                 'tech':str(e.get('Channel') or '').split('/')[0][:20]} for e in events]
        return {'channel_legs':len(rows), 'up':sum(r['state']=='Up' for r in rows),
                'ringing':sum(r['state'] in ('Ring','Ringing') for r in rows),
                'by_technology':{k:sum(r['tech']==k for r in rows) for k in sorted({r['tech'] for r in rows})}}
    if kind in ('extensions', 'sip_extensions'):
        rows = [{'endpoint':str(e.get('ObjectName') or e.get('Endpoint') or e.get('ObjectName') or e.get('Peer') or '')[:48],
                 'state':str(e.get('DeviceState') or e.get('Status') or 'Unknown')[:48],
                 'technology': 'SIP' if kind == 'sip_extensions' else 'PJSIP'} for e in events]
        return {'total':len(rows),'available':sum(r['state'].lower() in ('not in use','not_inuse','idle','avail','available') or r['state'].lower().startswith('ok') for r in rows),
                'endpoints':rows[:200]}
    if kind == 'parking':
        return {'parked_calls':len(events),'spaces':[str(e.get('ParkingSpace') or '')[:12] for e in events[:100]]}
    if kind == 'contacts':
        # NEVER expose SIP contact URIs, device IPs or user agents to the browser.
        return {'contacts':len(events),'available':sum(str(e.get('Status','')).lower() in ('avail','available','reachable') for e in events)}
    if kind in ('registrations','sip_registrations'):
        return {'registrations':len(events),
                'registered':sum(str(e.get('Status') or e.get('State','')).lower()=='registered' for e in events),
                'unregistered':sum(str(e.get('Status') or e.get('State','')).lower()!='registered' for e in events)}
    raise ValueError('Unsupported health action')


def read_capabilities(host, port, user, password, queue):
    host,port,_=validate_target(host,port,queue)
    client=None
    saw_success=False
    try:
        client=ReadOnlyAMI(host,port,timeout=6)
        client.login(user,password)
        client.sock.settimeout(8)
        action_id='sq-cap-'+secrets.token_hex(5)
        client.send(Action='ListCommands',ActionID=action_id)
        deadline=time.monotonic()+9
        while time.monotonic()<deadline:
            packet=client.read_packet()
            if packet.get('ActionID') not in (action_id,None):continue
            if packet.get('Response')=='Error':
                return {'supported':False,'kind':'permissions','reason':_unavailable_reason(packet.get('Message'))}
            if packet.get('Response')=='Success':
                # Asterisk ListCommands returns one response with action->synopsis pairs.
                available={a:(a in packet) for a in _CAPABILITIES}
                return {'supported':True,'kind':'permissions','actions':available,
                        'action_count':sum(available.values()),
                        'note':'Listed actions are AMI-authorized, not proof that required modules are operational.'}
        return {'supported':False,'kind':'permissions','reason':'timeout'}
    except (socket.timeout,TimeoutError,EOFError,OSError):
        return {'supported':False,'kind':'permissions','reason':'timeout_or_network'}
    finally:
        if client:client.close()


def read_health(host, port, user, password, queue, kind):
    host,port,_=validate_target(host,port,queue)
    if kind not in _ACTIONS:raise ValueError('Unsupported action')
    action,event_type,completed_name=_ACTIONS[kind]
    client=None
    saw_success=False
    try:
        client=ReadOnlyAMI(host,port,timeout=6)
        client.login(user,password)
        action_id='sq-health-'+secrets.token_hex(5)
        client.sock.settimeout(10)
        client.deadline=time.monotonic()+11
        client.send(Action=action,ActionID=action_id)
        events=[];deadline=time.monotonic()+11
        saw_success=False
        while time.monotonic()<deadline:
            packet=client.read_packet()
            if packet.get('ActionID') not in (action_id,None): continue
            if packet.get('Response')=='Error':
                return {'supported':False,'kind':kind,'reason':_unavailable_reason(packet.get('Message')),'action':action}
            if packet.get('Response')=='Success': saw_success=True
            if packet.get('Event')==completed_name:
                return {'supported':True,'kind':kind,'data':parse_health(kind,events),'action':action}
            if packet.get('Event')==event_type:events.append(packet)
            if len(events)>2000:
                return {'supported':False,'kind':kind,'reason':'result_too_large','action':action}
        return {'supported':False,'kind':kind,'reason':'event_list_incomplete' if saw_success else 'action_timeout','action':action}
    except (socket.timeout,TimeoutError):
        return {'supported':False,'kind':kind,'reason':'event_list_incomplete' if saw_success else 'timeout','action':action}
    except (EOFError,ConnectionError,OSError):
        return {'supported':False,'kind':kind,'reason':'connection_lost','action':action}
    finally:
        if client:client.close()
