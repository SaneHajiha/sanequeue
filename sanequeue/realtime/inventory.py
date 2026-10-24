"""Redacted PBX inventory parsers; no network or framework imports."""
import copy
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
    names={k.lower():k for k in ('ChannelStateDesc','Channel','ObjectName','Endpoint','Peer','DeviceState','Status','ParkingSpace','State')}
    events=[{names.get(str(k).lower(),k):v for k,v in e.items()} for e in events]
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


def inventory_projection(state, kind):
    """Serve periodic collector observations without issuing browser-driven AMI actions."""
    if kind == 'channels':
        rows=[dict(Channel=c.get('channel',''),ChannelStateDesc=c.get('channelstatedesc','Unknown'))
              for c in state.get('channels',{}).values()]
        return dict(kind=kind,supported=bool(state.get('channels_complete')),
                    data=parse_health(kind,rows),observed_at=state.get('last_sync_at',0))
    inventory=state.get('inventory',{})
    result=copy.deepcopy(inventory.get(kind,dict(kind=kind,supported=False,reason='inventory_initializing')))
    if kind in ('extensions','registrations'):
        legacy=inventory.get('sip_'+kind,{})
        drivers={'PJSIP':bool(result.get('supported')),'SIP':bool(legacy.get('supported'))}
        if legacy.get('supported'):
            if not result.get('supported'):
                result=dict(copy.deepcopy(legacy),kind=kind)
            else:
                data=result['data']
                if kind=='extensions':data['endpoints']=(data.get('endpoints',[])+copy.deepcopy(legacy['data'].get('endpoints',[])))[:200]
                for field in ('total','available','registrations','registered','unregistered'):
                    if field in legacy.get('data',{}):data[field]=data.get(field,0)+legacy['data'][field]
                result['observed_at']=min(result.get('observed_at',0),legacy.get('observed_at',0))
        result['drivers']=drivers
        result['complete']=all(drivers.values())
    return result
