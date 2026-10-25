"""Pure action planning with exact observed targets and local destination allowlists."""
import re
from sanequeue.api.state import scoped_channels

PERMISSIONS={'transfer':'transfer','attended_transfer':'transfer','cancel_transfer':'transfer',
             'park':'park','retrieve':'park','pickup':'pickup','dial':'dial','hangup_active':'hangup'}


def plan(state, queue, action, channel='', *, destination='', own_phone='',
         extensions=(), context='from-internal', parkinglot='default', allowed_queues=None, external_destinations=()):
    if action not in PERMISSIONS:raise ValueError('unknown_action')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',context) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',parkinglot):
        raise ValueError('invalid_server_control_settings')
    allowed=set(allowed_queues or [queue])
    if queue not in allowed:raise ValueError('queue_not_allowed')
    def originate(application=None,data=None):
        if not re.fullmatch(r'(SIP|PJSIP)/[A-Za-z0-9_.-]{1,48}',own_phone):
            raise ValueError('assigned_supervisor_phone_required')
        fields=dict(Channel=own_phone,Async='true',Timeout='30000',CallerID='SaneQueue')
        if application:fields.update(Application=application,Data=data)
        return fields
    if action=='dial':
        internal=destination in extensions and re.fullmatch(r'[0-9]{1,12}',destination)
        external=destination in external_destinations and re.fullmatch(r'\+?[0-9]{3,15}',destination)
        if not internal and not external:
            raise ValueError('destination_not_in_internal_allowlist')
        if own_phone.split('/')[-1]==destination:raise ValueError('cannot_call_own_phone')
        fields=originate();fields.update(Context=context,Exten=destination,Priority='1')
        return 'Originate',fields
    if action=='retrieve':
        parked=state.get('parked',{}).get(channel)
        if not parked or queue not in parked.get('queues',[]) or not set(parked['queues']).issubset(allowed):
            raise ValueError('parked_call_not_in_scope')
        lot,space=parked.get('parkinglot',''),parked.get('parkingspace','')
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',lot) or not re.fullmatch(r'[0-9]{1,8}',space):
            raise ValueError('invalid_parking_target')
        return 'Originate',originate('ParkedCall',lot+','+space)
    channels=scoped_channels(state,allowed)
    matches=[(uid,c) for uid,c in channels.items() if c.get('channel')==channel and queue in c['queues']]
    if len(matches)!=1:raise ValueError('active_channel_not_in_scope')
    uid,current=matches[0]
    if action in ('transfer','attended_transfer'):
        if not current.get('bridge'):raise ValueError('transfer_requires_observed_bridge')
        peers=[c for c in state.get('channels',{}).values() if c.get('bridge')==current['bridge']]
        if len(peers)!=2 or any(not c.get('queues') or not set(c['queues']).issubset(allowed) for c in peers):
            raise ValueError('transfer_requires_two_party_scoped_bridge')
        if destination not in extensions or not re.fullmatch(r'[0-9]{1,12}',destination):
            raise ValueError('destination_not_in_internal_allowlist')
        return ('BlindTransfer' if action=='transfer' else 'Atxfer'),dict(Channel=channel,Context=context,Exten=destination)
    if action=='cancel_transfer':return 'CancelAtxfer',dict(Channel=channel)
    if action=='hangup_active':return 'Hangup',dict(Channel=channel)
    if action=='pickup':
        if current.get('channelstatedesc','').lower() not in ('ring','ringing'):
            raise ValueError('pickup_requires_ringing_channel')
        if channel==own_phone or channel.startswith(own_phone+'-'):
            raise ValueError('cannot_pick_up_own_phone')
        return 'Originate',originate('PickupChan',channel)
    if action=='park':
        bridge=current.get('bridge')
        participants=[c for c in state.get('channels',{}).values() if bridge and c.get('bridge')==bridge]
        if len(participants)!=2 or any(not c.get('queues') or not set(c['queues']).issubset(allowed) for c in participants):
            raise ValueError('park_requires_two_party_scoped_bridge')
        peers=[c for other,c in channels.items() if other!=uid and bridge and c.get('bridge')==bridge]
        if len(peers)!=1:raise ValueError('park_requires_two_party_scoped_bridge')
        return 'Park',dict(Channel=peers[0]['channel'],TimeoutChannel=channel,Parkinglot=parkinglot)
    raise ValueError('unknown_action')
