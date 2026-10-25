"""Debounced critical conditions; missing observations never prove a PBX outage."""
import time


class SystemAlerts:
    def __init__(self,clock=time.time):
        self.clock=clock;self.since={}

    def evaluate(self,inventory,live,connected,rules):
        now=self.clock();candidates=[]
        def add(kind,resource,value=1,threshold=1):
            if rules.get(kind):candidates.append(dict(queue='__system__',scope='system',type=kind,
                resource=resource,label=resource,value=value,threshold=threshold))
        if not connected:add('monitoring_unavailable','AMI / Collector')
        if inventory is None:add('inventory_stale','PBX inventory')
        else:
            for row in inventory['endpoints']:
                if row['category']!='trunk':continue
                key=row['technology']+'/'+row['endpoint'];state=str(row.get('state','')).lower().replace('_',' ')
                observed=live.get(key,{})
                if now-observed.get('observed_at',0)<90:state=str(observed.get('state','')).lower()
                if any(word in state for word in ('unreachable','unavailable','unregistered','rejected')):add('trunk_down',key)
            used=inventory.get('disk_used_percent')
            if isinstance(used,(int,float)) and used>=rules['disk_used_percent']:add('disk_critical','PBX disk',round(used,1),rules['disk_used_percent'])
        keys={(a['type'],a['label']) for a in candidates}
        self.since={k:v for k,v in self.since.items() if k in keys}
        result=[]
        for alert in candidates:
            key=(alert['type'],alert['label']);first=self.since.setdefault(key,now)
            if now-first>=rules['debounce_seconds']:result.append(alert)
        return result
