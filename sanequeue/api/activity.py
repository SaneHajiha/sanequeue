"""Queue-scoped activity API, with a separate self-service path for all roles."""
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
import sqlite3

from flask import abort,jsonify,request
from flask_login import current_user,login_required

from sanequeue.realtime.activity import ActivityStore


def install(app,path,visible_queues,role,own_interfaces,policy,own_since=lambda:0):
    store=ActivityStore(path)

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
            result=store.daily(queues,day,not_before=own_since() if own else 0)
        except ValueError:return jsonify(error='invalid_activity_date'),400
        except (OSError,sqlite3.Error):return jsonify(error='activity_store_unavailable'),503
        who=set(own_interfaces()) if own else None
        if who is not None:result['rows']=[row for row in result['rows'] if row['agent'] in who]
        for row in result['rows']:
            reasons={item['id']:item['label'] for item in policy(row['queue'])['pause_reasons']}
            row['reason_label']=reasons.get(row['reason'],row['reason'])
        result.update(queues=sorted(queues),self_only=own,username=current_user.get_id())
        response=jsonify(result)
        response.headers['Cache-Control']='no-store'
        return response
