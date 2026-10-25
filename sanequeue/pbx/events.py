"""Persist bounded callback lifecycle evidence in the collector's private snapshot."""
import re

class CallbackEvents:
    def __init__(self):self.by_uid={}
    def observe(self,packet,state):
        e={str(k).lower():str(v) for k,v in packet.items()};kind=e.get('event','').lower();uid=e.get('uniqueid','');now=state.clock()
        if kind=='originateresponse' and e.get('actionid','').startswith('sq-cb-'):
            ident=e['actionid'];target=e.get('exten','')
            if not re.fullmatch(r'[0-9]{2,8}',target):return
            value=state.action_events.setdefault(ident,{})
            value.update(response=e.get('response',''),reason=e.get('reason',''),uniqueid=uid,target=target,observed_at=now)
            if uid and uid!='<unknown>' and e.get('response','').lower()=='success':self.by_uid[uid]=ident
            self.by_uid={key:value for key,value in self.by_uid.items() if value in state.action_events}
        ident=self.by_uid.get(uid);row=state.action_events.get(ident,{})
        if kind=='hangup' and row:
            row['ended_at']=now;state.version+=1
        if kind=='bridgeenter':
            bridge=e.get('bridgeuniqueid','');members=state.bridges.get(bridge,set())
            for source in members:
                ident=self.by_uid.get(source);row=state.action_events.get(ident,{})
                if not row or row.get('connected_at'):continue
                target=row.get('target','')
                for peer in members-{source}:
                    channel=state.channels.get(peer,{}).get('channel','')
                    if re.fullmatch(r'(?:SIP|PJSIP)/'+re.escape(target)+r'-[a-fA-F0-9]+',channel):
                        row.update(connected_at=now,target_uniqueid=peer);state.version+=1;break
