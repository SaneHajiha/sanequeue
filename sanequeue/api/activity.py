"""Queue-scoped activity API, with a separate self-service path for all roles."""
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
import sqlite3
import os,re,threading,time
from pathlib import Path
from sanequeue.realtime.local_inventory import read_snapshot

from flask import abort,jsonify,request
from flask_login import current_user,login_required

from sanequeue.realtime.activity import ActivityStore


def install(app,path,visible_queues,role,own_interfaces,policy,own_since=lambda:0,can_details=lambda queue:False):
    store=ActivityStore(path)
    from sanequeue.realtime.calls import CallStore
    from pathlib import Path
    calls=CallStore(Path(path).with_name('calls.sqlite3'))

    metrics_cache={};metrics_lock=threading.RLock()
    def today_metrics(queues):
        day=datetime.now(ZoneInfo('Asia/Tehran')).date().isoformat();key=(day,tuple(sorted(queues)))
        with metrics_lock:
            cached=metrics_cache.get(key)
            if cached and time.monotonic()-cached[0]<10:return cached[1]
            try:result=calls.daily(queues,day,details=False)
            except (OSError,sqlite3.Error):return {'available':False,'queues':{}}
            values={}
            for row in result.get('summaries',[]):
                item=values.setdefault(row['queue'],dict(answered=0,abandoned=0,talk_seconds=0,wait_seconds=0,sla_known=0,sla_met=0))
                for field in item:item[field]+=row[field] or 0
            result=dict(available=bool(result['since']),day=day,since=result['since'],observed_until=result['observed_until'],queues=values)
            if len(metrics_cache)>=32:metrics_cache.clear()
            metrics_cache[key]=(time.monotonic(),result);return result
    app.config['SANEQUEUE_DAILY_METRICS']=today_metrics

    @app.route('/api/activity/daily')
    @app.route('/api/profile/activity')
    @login_required
    def activity_daily():
        own=request.path.startswith('/api/profile/')
        if not own and role() not in ('admin','supervisor'):abort(403)
        allowed=visible_queues()
        queue=request.args.get('queue','')
        if queue and queue not in allowed:abort(403)
        queues=[queue] if queue else list(allowed)
        today=datetime.now(ZoneInfo('Asia/Tehran')).date()
        day=request.args.get('day',today.isoformat())
        try:
            date=datetime.strptime(day,'%Y-%m-%d').date()
            if not today-timedelta(days=90)<=date<=today:raise ValueError()
            who=set(own_interfaces()) if own else None
            inventory=read_snapshot(os.getenv('SANEQUEUE_LOCAL_INVENTORY','/run/sanequeue/inventory.json'))
            if own and inventory:
                for interface in list(who):
                    match=re.match(r'^Local/([^@]+)@',interface)
                    if match:
                        matches=[r['technology']+'/'+r['endpoint'] for r in inventory['endpoints'] if r['category']=='extension' and r['endpoint']==match[1]]
                        if len(matches)==1:who.add(matches[0])
            result=store.daily(queues,day,not_before=own_since() if own else 0,agents=sorted(who) if own else None)
            result['calls']=calls.daily(queues,day,not_before=own_since() if own else 0,agents=sorted(who) if own else None)
        except ValueError:return jsonify(error='invalid_activity_date'),400
        except (OSError,sqlite3.Error):return jsonify(error='activity_store_unavailable'),503
        inventory=read_snapshot(os.getenv('SANEQUEUE_LOCAL_INVENTORY','/run/sanequeue/inventory.json'))
        def canonical(interface):
            match=re.match(r'^Local/([^@]+)@',interface)
            if not match or inventory is None:return interface
            candidates=[r['technology']+'/'+r['endpoint'] for r in inventory['endpoints'] if r['category']=='extension' and r['endpoint']==match[1]]
            return candidates[0] if len(candidates)==1 else interface
        for row in result['rows']+result.get('intervals',[]):
            row['canonical_agent']=canonical(row['agent'])
            reasons={item['id']:item['label'] for item in policy(row['queue'])['pause_reasons']}
            row['reason_label']=reasons.get(row['reason'],row['reason'])
        for row in result['calls']['rows']:
            reasons={item['id']:item['label'] for item in policy(row['queue'])['pause_reasons']}
            row['reason_label']=reasons.get(row['reason'],row['reason'])
            if not own and not can_details(row['queue']):
                from qpanel.privacy import mask_phone
                row['number']=mask_phone(row['number'])
        result.update(queues=sorted(queues),self_only=own,username=current_user.get_id())
        response=jsonify(result)
        response.headers['Cache-Control']='no-store'
        return response
