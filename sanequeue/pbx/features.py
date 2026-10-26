"""Admin configuration and bounded, offline telephone-prompt conversion."""
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import threading
import time
import wave

from flask import abort,jsonify,request,session,send_file
from flask_login import login_required,current_user

SLOTS=('menu','confirmation','wait_timeout')
CONVERSION=threading.BoundedSemaphore(1)
DEFAULT={'callback':{'enabled':False,'waiting_enabled':True,'callback_enabled':True,'max_wait_seconds':300,'expiry_seconds':600,'retry_seconds':10},
         'caller_id':{'enabled':False,'country_code':'98','national_prefix':'0','area_code':'21','local_digits':8,'mobile_digits':10,'directory_names':True,'provider_prefixes':False,'expand_local':False},
         'audio':{slot:'' for slot in SLOTS}}


def validate(raw):
    if not isinstance(raw,dict):raise ValueError('invalid_feature_settings')
    result=json.loads(json.dumps(DEFAULT))
    for area in ('callback','caller_id'):
        value=raw.get(area,{})
        if not isinstance(value,dict):raise ValueError('invalid_feature_settings')
        for key,default in result[area].items():
            selected=value.get(key,default)
            if isinstance(default,bool):
                if not isinstance(selected,bool):raise ValueError('invalid_feature_switch')
            elif isinstance(default,int):
                lo,hi=(30,1800) if key in ('max_wait_seconds','expiry_seconds') else (5,60) if key=='retry_seconds' else (3,15)
                if isinstance(selected,bool) or not isinstance(selected,int) or not lo<=selected<=hi:raise ValueError('invalid_feature_number')
            elif not isinstance(selected,str) or not re.fullmatch(r'[0-9]{1,5}',selected):raise ValueError('invalid_number_format')
            result[area][key]=selected
    if result['callback']['enabled'] and not (result['callback']['waiting_enabled'] or result['callback']['callback_enabled']):raise ValueError('choose_wait_or_callback')
    audio=raw.get('audio',{})
    if not isinstance(audio,dict):raise ValueError('invalid_audio_selection')
    for slot in SLOTS:
        value=audio.get(slot,'')
        if value and (not isinstance(value,str) or not re.fullmatch('[a-f0-9]{64}',value)):raise ValueError('invalid_audio_selection')
        result['audio'][slot]=value
    return result


def normalize_number(number,config):
    """Predict the managed dialplan's conservative international/mobile rules."""
    if not isinstance(number,str) or not re.fullmatch(r'\+?[0-9]{2,20}',number):return number
    value=number;country=config['country_code'];prefix=config['national_prefix']
    if config.get('provider_prefixes') and country=='98':
        # Optional Iranian provider anomalies; keep these separate from general E.164 rules.
        if value.startswith('0000'):value=value[4:]
        if value.startswith('+'):value=value[1:]
        for extra in ('98','0098','002198'):
            if value.startswith(extra):value=value[len(extra):]
        for length,extra in ((13,'210'),(12,'21'),(15,'21098'),(13,'098')):
            if len(value)==length and value.startswith(extra):value=prefix+value[len(extra):]
        if len(value) in (6,7) and not value.startswith(prefix):value=prefix+value
    else:
        international='+'+country
        if value.startswith(international):value=value[len(international):]
        elif value.startswith('00'+country):value=value[2+len(country):]
        elif value.startswith(('+','00')):return number
        elif value.startswith(country) and len(value)==len(country)+config['mobile_digits']:value=value[len(country):]
    if country=='98' and len(value)==config['mobile_digits'] and value.startswith('9'):value=prefix+value
    elif len(value)==config['mobile_digits'] and value.startswith(config['area_code']):value=prefix+value
    elif config.get('expand_local') and len(value)==config['local_digits'] and not value.startswith(prefix):value=prefix+config['area_code']+value
    return value




def bundled_prompt():
    path=Path(__file__).resolve().parents[2]/'assets/audio/callback-menu-fa.wav'
    manifest=json.loads(path.with_name('manifest.json').read_text())['callback-menu-fa.wav']
    if path.is_symlink() or path.stat().st_size>1_100_000:raise ValueError('invalid_bundled_prompt')
    content=path.read_bytes()
    if hashlib.sha256(content).hexdigest()!=manifest['sha256']:raise ValueError('bundled_prompt_hash_mismatch')
    with wave.open(str(path),'rb') as sound:
        if sound.getnchannels()!=1 or sound.getsampwidth()!=2 or sound.getframerate()!=8000 or not 0<sound.getnframes()<=480000:raise ValueError('invalid_bundled_prompt_format')
    return path,content

def convert_audio(content):
    if not content or len(content)>8*1024*1024:raise ValueError('audio_max_8mb')
    from imageio_ffmpeg import get_ffmpeg_exe
    with tempfile.TemporaryDirectory(prefix='sanequeue-audio-') as folder:
        source=Path(folder)/'input';target=Path(folder)/'prompt.wav';source.write_bytes(content)
        try:executable=get_ffmpeg_exe()
        except (RuntimeError,OSError):raise ValueError('audio_converter_unavailable') from None
        command=[executable,'-hide_banner','-loglevel','error','-nostdin','-protocol_whitelist','file,pipe','-format_whitelist','wav,mp3,ogg,flac,mov,matroska,aac',
                 '-max_alloc','16777216','-probesize','1048576','-analyzeduration','1000000','-threads','1','-i',str(source),
                 '-map','0:a:0','-vn','-sn','-dn','-map_metadata','-1','-t','61','-ac','1','-ar','8000','-c:a','pcm_s16le','-threads','1','-f','wav',str(target)]
        if os.name!='nt' and Path('/usr/bin/nice').is_file():command=['/usr/bin/nice','-n','10',*command]
        try:
            result=subprocess.run(command,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=20,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0) if os.name=='nt' else 0)
        except (OSError,subprocess.TimeoutExpired):raise ValueError('audio_conversion_failed') from None
        if result.returncode or not target.is_file() or target.stat().st_size>1_100_000:raise ValueError('invalid_audio')
        with wave.open(str(target),'rb') as sound:
            seconds=sound.getnframes()/sound.getframerate()
            if not 0<seconds<=60 or sound.getnchannels()!=1 or sound.getsampwidth()!=2:raise ValueError('audio_duration_max_60_seconds')
        return target.read_bytes(),round(seconds,2)


class FeatureStore:
    def __init__(self,state):self.state=Path(state);self.path=self.state/'pbx-features.json';self.lock=threading.RLock()
    def read(self):
        try:
            if self.path.is_symlink() or self.path.stat().st_size>16384:raise ValueError('invalid_feature_store')
            return validate(json.loads(self.path.read_text()))
        except FileNotFoundError:return validate({})
    def write(self,value):
        value=validate(value)
        with self.lock:
            self.state.mkdir(parents=True,exist_ok=True)
            fd,name=tempfile.mkstemp(prefix='.pbx-features-',dir=self.state)
            try:
                with os.fdopen(fd,'w') as stream:json.dump(value,stream);stream.flush();os.fsync(stream.fileno())
                os.replace(name,self.path)
            finally:
                if os.path.exists(name):os.unlink(name)
        return value
    def upload(self,slot,content):
        if slot not in SLOTS:raise ValueError('invalid_audio_slot')
        if not CONVERSION.acquire(blocking=False):raise ValueError('audio_conversion_busy')
        try:audio,seconds=convert_audio(content)
        finally:CONVERSION.release()
        ident=hashlib.sha256(audio).hexdigest()
        folder=self.state/'pbx-sounds';folder.mkdir(mode=0o750,exist_ok=True)
        with self.lock:
            files=list(folder.glob('*.wav'))
            if len(files)>=30 and not (folder/(ident+'.wav')).exists():raise ValueError('audio_storage_limit')
            fd,name=tempfile.mkstemp(prefix='.upload-',dir=folder)
            try:
                with os.fdopen(fd,'wb') as stream:stream.write(audio);stream.flush();os.fsync(stream.fileno())
                os.replace(name,folder/(ident+'.wav'))
            finally:
                if os.path.exists(name):os.unlink(name)
            value=self.read();value['audio'][slot]=ident;self.write(value)
        return dict(id=ident,seconds=seconds,settings=value)


def install(app,state,role):
    store=FeatureStore(state)
    def admin():
        if role()!='admin':abort(403)
        provider=app.config.get('SANEQUEUE_MENU_PROVIDER')
        if callable(provider) and 'telephony' not in provider(current_user.get_id(),'admin'):abort(403)
    def csrf():
        if not session.get('csrf_token') or not hmac.compare_digest(request.headers.get('X-CSRF-Token',''),session['csrf_token']):abort(403)
    from .incidents import install as install_incidents
    install_incidents(app,state,role,admin,csrf)
    from sanequeue.surveys.api import install as install_surveys
    install_surveys(app,state)
    from sanequeue.surveys.voice_feedback_api import install as install_voice_feedback
    install_voice_feedback(app,state)
    @app.before_request
    def prompt_limit():
        if request.path=='/api/pbx/features/audio':request.max_content_length=8*1024*1024+65536
    @app.route('/api/pbx/features',methods=['GET','POST'])
    @login_required
    def feature_settings():
        admin()
        if request.method=='POST':
            csrf()
            if (request.content_length or 0)>16384:return jsonify(error='payload_too_large'),413
            try:settings=store.write(request.get_json(silent=True))
            except ValueError as error:return jsonify(error=str(error)),400
        else:settings=store.read()
        try:
            status_path=Path('/run/sanequeue/pbx-status.json')
            status=json.loads(status_path.read_text()) if status_path.stat().st_size<32768 else {}
        except (OSError,ValueError):status={'state':'adapter_not_provisioned'}
        from .callbacks import report
        response=jsonify(settings=settings,status=status,callbacks=report(store.state/'callbacks.sqlite3'));response.headers['Cache-Control']='no-store';return response
    @app.route('/api/pbx/features/audio',methods=['POST'])
    @login_required
    def upload_prompt():
        admin();csrf();image=request.files.get('audio');slot=request.form.get('slot','')
        if not image:return jsonify(error='audio_required'),400
        try:return jsonify(store.upload(slot,image.read(8*1024*1024+1)))
        except ImportError:return jsonify(error='audio_dependency_unavailable'),503
        except ValueError as error:return jsonify(error=str(error)),400
    @app.route('/api/pbx/features/audio/<slot>')
    @login_required
    def play_prompt(slot):
        admin()
        if slot not in SLOTS:abort(404)
        ident=store.read()['audio'][slot]
        if not ident and slot!='menu':abort(404)
        path=store.state/'pbx-sounds'/(ident+'.wav') if ident else bundled_prompt()[0]
        response=send_file(path,mimetype='audio/wav',conditional=False)
        response.headers['Cache-Control']='no-store';return response
    @app.route('/api/pbx/features/preview',methods=['POST'])
    @login_required
    def preview_number():
        admin();csrf()
        if (request.content_length or 0)>16384:return jsonify(error='payload_too_large'),413
        body=request.get_json(silent=True)
        if not isinstance(body,dict) or not isinstance(body.get('number'),str) or len(body['number'])>30:return jsonify(error='invalid_number'),400
        try:return jsonify(original=body['number'],normalized=normalize_number(body['number'],validate(body.get('settings',store.read()))['caller_id']))
        except ValueError as error:return jsonify(error=str(error)),400
