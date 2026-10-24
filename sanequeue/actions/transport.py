"""Separate short-lived control session with an absolute deadline and no retry."""
import configparser
import re
import time
from AMI_READONLY_TEST import ReadOnlyAMI

FIELDS={
 'QueuePause':{'Queue','Interface','Paused','Reason'},
 'QueuePenalty':{'Queue','Interface','Penalty'},
 'QueueAdd':{'Queue','Interface','Penalty','Paused','MemberName'},
 'QueueRemove':{'Queue','Interface'},
 'QueueChangePriorityCaller':{'Queue','Caller','Priority','Immediate'},
 'Hangup':{'Channel'},
 'Originate':{'Channel','Application','Data','Async','Timeout','CallerID','Exten','Context','Priority'},
 'BlindTransfer':{'Channel','Context','Exten'}, 'Atxfer':{'Channel','Context','Exten'},
 'CancelAtxfer':{'Channel'},
 'Park':{'Channel','TimeoutChannel','Parkinglot','ParkingSpace','Timeout'},
}


def send_action(config, action, fields, action_id):
    if action not in FIELDS or not set(fields).issubset(FIELDS[action]):raise ValueError('action_not_allowed')
    for key,value in dict(fields,ActionID=action_id).items():
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9]*',key) or len(str(value))>2048 or any(c in str(value) for c in '\r\n\x00'):
            raise ValueError('invalid_action_field')
    cfg=configparser.ConfigParser(interpolation=None)
    if not cfg.read(config):raise PermissionError('control_config_missing')
    a=cfg['ami'];client=None
    try:
        client=ReadOnlyAMI(a['host'],a.getint('port',5038),timeout=3)
        client.deadline=time.monotonic()+8
        client.login(a['user'],a['password'])
        client.send(Action=action,ActionID=action_id,**fields)
        while True:
            packet=client.read_packet()
            if packet.get('ActionID')==action_id and 'Response' in packet:
                return str(packet['Response']).lower()=='success'
    finally:
        if client:client.close()
