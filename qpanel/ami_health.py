"""Read-only AMI PBX capability and health inventory with classified, redacted errors.

Action permissions and event classes are independent in Asterisk AMI. Never
escalate privileges automatically and never issue mutating actions here.
"""
import secrets
import time
import socket
from AMI_READONLY_TEST import ReadOnlyAMI
from qpanel.ami_targets import validate_target

from sanequeue.realtime.inventory import _ACTIONS, _CAPABILITIES, _unavailable_reason, parse_health


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
