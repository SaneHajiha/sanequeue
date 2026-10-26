"""Root-only, typed apply/restore helper. It never restarts Asterisk."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import pwd,grp
import re
import secrets
import shutil
import sqlite3
import stat
import subprocess
import tempfile
import time
import wave

from .features import FeatureStore,validate,normalize_number,bundled_prompt
from .incidents import IncidentStore,bindings as incident_bindings,validate_notice,dialplan as incident_dialplan
from sanequeue.realtime.local_inventory import read_snapshot

MARKER='; SANEQUEUE MANAGED TELEPHONY V1'


def digest(content):return hashlib.sha256(content).hexdigest()


def patch_macro(original):
    if MARKER in original:return original.replace('sanequeue-caller-name,s,1(${NODEST}))','sanequeue-caller-name,s,1(${NODEST},${SANEQUEUE_CALLBACK}))')
    pattern=r'(?ms)^###CallWaiting And CallBack\s*\n.*?(?=^exten\s*=>\s*s,n\(dial\),)'
    updated,count=re.subn(pattern,MARKER+'\nexten => s,n(godial),Gosub(sanequeue-busy-menu,s,1(${DEXTEN}))\n\n',original,count=1)
    if count!=1:raise ValueError('unsupported_dial_one_adapter')
    needle='exten => s,n(dial),'
    updated=updated.replace(needle,'exten => s,n(dial),Gosub(sanequeue-caller-name,s,1(${NODEST},${SANEQUEUE_CALLBACK}))\nexten => s,n,',1)
    return updated


def dialplan(token):
    if not re.fullmatch('[a-f0-9]{64}',token):raise ValueError('invalid_adapter_token')
    url='agi://127.0.0.1:19051/'+token+'/'
    return MARKER+'''
[sanequeue-busy-menu]
exten => s,1,Set(SQ_MENU_ENABLED=0)
 same => n,GotoIf($[${STAT(e,/var/spool/asterisk/sanequeue/disabled)}=1]?done)
 same => n,AGI(URLmenu,${ARG1})
 same => n,GotoIf($["${SQ_MENU_ENABLED}"!="1"]?done)
 same => n,GotoIf($["${EXTENSION_STATE(${SQ_TARGET})}"="INUSE" | "${EXTENSION_STATE(${SQ_TARGET})}"="BUSY"]?offer:done)
 same => n(offer),Read(SQ_CHOICE,${SQ_MENU_AUDIO},1,,1,10)
 same => n,GotoIf($["${SQ_CHOICE}"="2" & "${SQ_CALLBACK_ALLOWED}"="1"]?callback)
 same => n,GotoIf($["${SQ_CHOICE}"="1" & "${SQ_WAIT_ALLOWED}"="1"]?wait:done)
 same => n(callback),Set(SQ_JOB_ACCEPTED=0)
 same => n,AGI(URLenqueue,${SQ_TARGET})
 same => n,GotoIf($["${SQ_JOB_ACCEPTED}"!="1"]?done)
 same => n,Playback(${SQ_CONFIRM_AUDIO})
 same => n,Hangup()
 same => n(wait),Set(SQ_WAIT_UNTIL=$[${EPOCH}+${SQ_MAX_WAIT}])
 same => n,StartMusicOnHold()
 same => n(check),Wait(2)
 same => n,GotoIf($[${STAT(e,/var/spool/asterisk/sanequeue/disabled)}=1]?finish)
 same => n,GotoIf($["${EXTENSION_STATE(${SQ_TARGET})}"="NOT_INUSE"]?finish)
 same => n,GotoIf($[${EPOCH}<${SQ_WAIT_UNTIL}]?check:timeout)
 same => n(finish),StopMusicOnHold()
 same => n(done),Return()
 same => n(timeout),StopMusicOnHold()
 same => n,Playback(${SQ_TIMEOUT_AUDIO})
 same => n,Return()

[sanequeue-caller-name]
exten => s,1,Set(SQ_CONTACT_FOUND=0)
 same => n,GotoIf($[${STAT(e,/var/spool/asterisk/sanequeue/disabled)}=1]?done)
 same => n,AGI(URLname,${ARG1},${ARG2})
 same => n,ExecIf($["${SQ_CONTACT_FOUND}"="1"]?Set(CALLERID(name)=${SQ_CONTACT_NAME}))
 same => n(done),Return()

[sanequeue-callerid-normalize]
exten => s,1,Set(SQ_CID_CHANGED=0)
 same => n,GotoIf($[${STAT(e,/var/spool/asterisk/sanequeue/disabled)}=1]?done)
 same => n,AGI(URLnormalize)
 same => n,ExecIf($["${SQ_CID_CHANGED}"="1"]?Set(__SQ_ORIGINAL_CALLERID=${CALLERID(num)}))
 same => n,ExecIf($["${SQ_CID_CHANGED}"="1"]?Set(CALLERID(num)=${SQ_CID_NUMBER}))
 same => n(done),Return()
'''.replace('URL',url)+incident_dialplan(token)


def atomic(path,content,uid,gid,mode=0o640):
    path=Path(path)
    if path.is_symlink():raise ValueError('symlink_target_refused')
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(prefix='.sanequeue-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as stream:stream.write(content);stream.flush();os.fsync(stream.fileno())
        os.chown(name,uid,gid);os.chmod(name,mode);os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)


def require_idle():
    check=subprocess.run([shutil.which('asterisk') or '/usr/sbin/asterisk','-rx','core show channels count'],capture_output=True,timeout=5)
    match=re.search(rb'(?m)^([0-9]+) active calls',check.stdout)
    if check.returncode or not match:raise ValueError('cannot_verify_idle_pbx')
    if int(match[1]):raise ValueError('active_calls_defer_dialplan_change')


def _read_root_json(path,*,maximum=2_000_000,owner_uid=0):
    """Root-published data only; never follow a web-writable spool symlink."""
    try:fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    except FileNotFoundError:return None,None
    with os.fdopen(fd,'rb') as stream:
        meta=os.fstat(stream.fileno())
        if not stat.S_ISREG(meta.st_mode) or meta.st_uid!=owner_uid or meta.st_mode&0o022 or meta.st_nlink!=1 or meta.st_size>maximum:
            raise ValueError('invalid_root_published_snapshot')
        data=stream.read(maximum+1)
    if len(data)>maximum:raise ValueError('invalid_root_published_snapshot')
    value=json.loads(data)
    if not isinstance(value,dict):raise ValueError('invalid_root_published_snapshot')
    return value,data


def _notice_snapshot(store,allowed):
    """Optional notice failure withdraws notices, with explicit safe diagnostics."""
    diagnostic=dict(state='ok',eligible=0,disabled=0,omitted=0,error_codes=[])
    if not allowed:diagnostic['state']='no_authorized_bindings';return {},diagnostic
    if not store.path.exists():diagnostic['state']='not_initialized';return {},diagnostic
    try:current=store.current(read_only=True,allowed=allowed)
    except (OSError,ValueError,TypeError,sqlite3.Error):
        diagnostic.update(state='unavailable',error_codes=['notice_store_unavailable'])
        return {},diagnostic
    result={}
    for row in current:
        try:
            value=validate_notice(row,allowed)
            if not value['enabled']:diagnostic['disabled']+=1;continue
            revision=row['revision']
            if isinstance(revision,bool) or not isinstance(revision,int) or revision<=0:raise ValueError('invalid_revision')
            store.audio(value['audio'])
            result[value['binding']]=dict(value,revision=revision,**allowed[value['binding']])
        except (OSError,ValueError,TypeError,KeyError):diagnostic['omitted']+=1
    diagnostic['eligible']=len(result)
    if diagnostic['omitted']:diagnostic.update(state='partial',error_codes=['notice_source_or_config_invalid'])
    return result,diagnostic


def _withdraw_notices(runtime_path,desired,gid):
    """Only remove old entries. Activation/extension waits for successful apply."""
    previous,raw=_read_root_json(runtime_path)
    if previous is None:return None,0
    if not re.fullmatch('[a-f0-9]{64}',previous.get('token','')) or not isinstance(previous.get('incidents',{}),dict):
        raise ValueError('invalid_root_published_snapshot')
    existing=previous.get('incidents',{})
    retained={key:row for key,row in existing.items() if desired.get(key)==row}
    removed=len(existing)-len(retained)
    if removed:
        previous['incidents']=retained
        raw=json.dumps(previous,ensure_ascii=False,sort_keys=True).encode()
        atomic(runtime_path,raw,0,gid)
    return raw,removed


def apply():
    if os.geteuid()!=0:raise PermissionError('root_required')
    state=Path('/var/lib/sanequeue');spool=Path('/var/spool/asterisk/sanequeue');configdir=Path('/etc/asterisk')
    sq=grp.getgrnam('sanequeue').gr_gid;ast=pwd.getpwnam('asterisk')
    if spool.is_symlink():raise ValueError('spool_symlink_refused')
    spool.mkdir(parents=True,exist_ok=True);os.chown(spool,ast.pw_uid,sq);os.chmod(spool,0o2770)
    flag=spool/'disabled'
    if (state/'module.disabled').exists():atomic(flag,b'disabled\n',0,ast.pw_gid)
    # Withdrawals and emergency disable must not depend on unrelated feature
    # settings, legacy dialplan validation, audio installation or idle calls.
    incidents=IncidentStore(state)
    notices,notice_diagnostic=_notice_snapshot(incidents,incident_bindings())
    runtime_path=spool/'runtime.json'
    old_runtime,withdrawn=_withdraw_notices(runtime_path,notices,ast.pw_gid)
    safety=dict(notice_snapshot=notice_diagnostic,notice_withdrawn=withdrawn)
    atomic(Path('/run/sanequeue/pbx-status.json'),json.dumps(dict(state='notice_safety_updated',applied=False,
        observed_at=time.time(),**safety)).encode(),0,sq)
    if (state/'module.disabled').exists():
        status=dict(state='disabled',applied=False,observed_at=time.time(),**safety)
        atomic(Path('/run/sanequeue/pbx-status.json'),json.dumps(status).encode(),0,sq)
        return status
    token_path=spool/'adapter-token'
    if not token_path.exists():atomic(token_path,secrets.token_hex(32).encode(),0,ast.pw_gid)
    if token_path.is_symlink():raise ValueError('token_symlink_refused')
    token=token_path.read_text().strip()
    inventory=read_snapshot('/run/sanequeue/inventory.json')
    phones={r['technology']+'/'+r['endpoint']:r['endpoint'] for r in (inventory or {}).get('endpoints',[]) if r['category']=='extension' and re.fullmatch('[0-9]{2,8}',r['endpoint'])}
    # Verify and install the owner-provided prompt independently of private organization uploads.
    sounds=Path('/var/lib/asterisk/sounds/custom/sanequeue')
    if sounds.is_symlink():raise ValueError('sounds_symlink_refused')
    sounds.mkdir(parents=True,exist_ok=True);os.chown(sounds,0,ast.pw_gid);os.chmod(sounds,0o750)
    _,default_audio=bundled_prompt();default_path=sounds/'callback-menu-fa.wav'
    if default_path.exists():
        if default_path.is_symlink() or default_path.read_bytes()!=default_audio:raise ValueError('bundled_prompt_destination_modified')
    else:atomic(default_path,default_audio,0,ast.pw_gid)
    store=FeatureStore(state);settings=store.read()
    original_macro=configdir/'extensions_override_issabelpbx.conf';custom=configdir/'extensions_custom.conf'
    formatter=configdir/'extensions_voipiran_numberformatter.conf';managed=configdir/'sanequeue-features.conf'
    macro=original_macro.read_text() if original_macro.exists() else ''
    available=bool('###CallWaiting And CallBack' in macro or MARKER in macro)
    status={'state':'not_requested','legacy_callback_available':available,'legacy_formatter_available':formatter.is_file(),
            'observed_at':time.time(),'requested_hash':digest(json.dumps(settings,sort_keys=True).encode()),'applied':False,**safety}
    names={}
    dbpath=state/'planning.sqlite3'
    if dbpath.exists():
        db=sqlite3.connect(dbpath.resolve().as_uri()+'?mode=ro',uri=True,timeout=2)
        try:
            for queue,name,number in db.execute('SELECT queue,name,phone FROM directory ORDER BY id DESC LIMIT 5000'):
                if not re.fullmatch('[A-Za-z0-9_-]{1,32}',queue or ''):continue
                number=re.sub(r'[^+0-9]','',str(number))
                if settings['caller_id']['enabled']:number=normalize_number(number,settings['caller_id'])
                if not re.fullmatch(r'\+?[0-9]{2,20}',number):continue
                safe=''.join(c for c in str(name) if c.isprintable() and c not in '$}{\\"')[:80]
                if safe:names.setdefault(queue,{}).setdefault(number,safe)
        finally:db.close()
    runtime={'token':token,'settings':settings,'phones':phones,'directory':names,'incidents':notices}
    content=json.dumps(runtime,ensure_ascii=False,sort_keys=True).encode()
    if len(content)>2_000_000:raise ValueError('telephone_runtime_capacity_exceeded')
    feature_settings_present=store.path.exists()
    if feature_settings_present or notices:
        if settings['callback']['enabled'] and not available:raise ValueError('unsupported_dial_one_adapter')
        if not custom.is_file():raise ValueError('unsupported_custom_dialplan_adapter')
        backup=Path('/var/backups/sanequeue/pbx-feature-originals');backup.mkdir(parents=True,exist_ok=True);os.chmod(backup,0o700)
        changes={managed:dialplan(token).encode()}
        if feature_settings_present and available:changes[original_macro]=patch_macro(macro).encode()
        if custom.exists():
            text=custom.read_text()
            if '#include sanequeue-features.conf' not in text:changes[custom]=(text.rstrip()+'\n#include sanequeue-features.conf\n').encode()
        if feature_settings_present and formatter.exists():
            text=formatter.read_text()
            contexts=re.findall(r'^\[([^\]]+)\]',text,re.M)
            if contexts!=['numberformatter']:raise ValueError('unsupported_formatter_adapter')
            changes[formatter]=(MARKER+'\n[numberformatter]\nexten => s,1,Gosub(sanequeue-callerid-normalize,s,1)\n same => n,Return()\n').encode()
        manifest_path=backup/'manifest.json'
        manifest=json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
        sounds=Path('/var/lib/asterisk/sounds/custom/sanequeue')
        if sounds.is_symlink():raise ValueError('sounds_symlink_refused')
        sounds.mkdir(parents=True,exist_ok=True)
        for ident in set(settings['audio'].values())-{''}:
            source=state/'pbx-sounds'/(ident+'.wav')
            if source.is_symlink() or source.stat().st_size>1_100_000:raise ValueError('invalid_audio_source')
            data=source.read_bytes()
            if digest(data)!=ident:raise ValueError('audio_hash_mismatch')
            with wave.open(str(source),'rb') as sound:
                if sound.getnchannels()!=1 or sound.getsampwidth()!=2 or sound.getframerate()!=8000 or not 0<sound.getnframes()<=480000:raise ValueError('invalid_pbx_audio')
            destination=sounds/(ident+'.wav')
            if not destination.exists():atomic(destination,data,0,ast.pw_gid)
        for row in notices.values():
            _,data=incidents.audio(row['audio'])
            destination=sounds/(row['audio']+'.wav')
            if destination.is_symlink():raise ValueError('notice_audio_destination_symlink')
            if destination.exists():
                if destination.read_bytes()!=data:raise ValueError('notice_audio_destination_changed')
            else:atomic(destination,data,0,ast.pw_gid)
        # Context replacement is deferred until the test/production PBX has no active calls.
        if any(not path.exists() or path.read_bytes()!=data for path,data in changes.items()):
            require_idle()
        before={};changed=[]
        try:
            for path,data in changes.items():
                previous=path.read_bytes() if path.exists() else None
                meta=manifest.get(path.name)
                if meta and previous is not None and digest(previous)!=meta['applied_hash']:raise ValueError('external_dialplan_change_detected')
                if previous==data:continue
                if not meta:
                    manifest[path.name]={'existed':previous is not None,'applied_hash':digest(data),'uid':path.stat().st_uid if previous is not None else 0,'gid':path.stat().st_gid if previous is not None else ast.pw_gid,'mode':path.stat().st_mode&0o777 if previous is not None else 0o640}
                    if previous is not None:atomic(backup/path.name,previous,0,0,0o600)
                else:meta['applied_hash']=digest(data)
                before[path]=previous;atomic(path,data,0,ast.pw_gid);changed.append(path)
            if changed:
                result=subprocess.run([shutil.which('asterisk') or '/usr/sbin/asterisk','-rx','dialplan reload'],capture_output=True,timeout=8)
                if result.returncode or b'Unable to connect' in result.stdout:raise RuntimeError('dialplan_reload_failed')
            if old_runtime!=content:atomic(runtime_path,content,0,ast.pw_gid)
            atomic(manifest_path,json.dumps(manifest).encode(),0,0,0o600)
        except Exception:
            for path in reversed(changed):
                if before[path] is None:path.unlink(missing_ok=True)
                else:atomic(path,before[path],0,ast.pw_gid)
            if changed:subprocess.run([shutil.which('asterisk') or '/usr/sbin/asterisk','-rx','dialplan reload'],capture_output=True,timeout=8)
            if old_runtime is None:runtime_path.unlink(missing_ok=True)
            else:atomic(runtime_path,old_runtime,0,ast.pw_gid)
            raise
        status.update(state='applied',applied=True,applied_at=time.time(),directory_entries=sum(len(v) for v in names.values()))
    elif old_runtime!=content:atomic(runtime_path,content,0,ast.pw_gid)
    status_path=Path('/run/sanequeue/pbx-status.json');atomic(status_path,json.dumps(status).encode(),0,sq)
    if (state/'module.disabled').exists():atomic(flag,b'disabled\n',0,ast.pw_gid)
    else:flag.unlink(missing_ok=True)
    return status


def restore():
    backup=Path('/var/backups/sanequeue/pbx-feature-originals');manifest_path=backup/'manifest.json'
    if not manifest_path.exists():return
    require_idle()
    ast=pwd.getpwnam('asterisk');manifest=json.loads(manifest_path.read_text())
    for name,meta in manifest.items():
        if name not in ('sanequeue-features.conf','extensions_override_issabelpbx.conf','extensions_custom.conf','extensions_voipiran_numberformatter.conf'):raise ValueError('invalid_backup_manifest')
        target=Path('/etc/asterisk')/name
        if target.exists() and digest(target.read_bytes())!=meta['applied_hash']:raise ValueError('external_dialplan_change_detected')
    current={name:(Path('/etc/asterisk')/name).read_bytes() if (Path('/etc/asterisk')/name).exists() else None for name in manifest}
    try:
        for name,meta in manifest.items():
            target=Path('/etc/asterisk')/name
            if meta['existed']:atomic(target,(backup/name).read_bytes(),meta.get('uid',0),meta.get('gid',ast.pw_gid),meta.get('mode',0o640))
            else:target.unlink(missing_ok=True)
        result=subprocess.run([shutil.which('asterisk') or '/usr/sbin/asterisk','-rx','dialplan reload'],capture_output=True,timeout=8)
        if result.returncode:raise RuntimeError('dialplan_restore_reload_failed')
        manifest_path.rename(backup/('manifest-restored-'+str(time.time_ns())+'.json'))
    except Exception:
        for name,data in current.items():
            target=Path('/etc/asterisk')/name
            if data is None:target.unlink(missing_ok=True)
            else:atomic(target,data,0,ast.pw_gid)
        subprocess.run([shutil.which('asterisk') or '/usr/sbin/asterisk','-rx','dialplan reload'],capture_output=True,timeout=8)
        raise


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--restore',action='store_true');args=parser.parse_args()
    try:restore() if args.restore else apply()
    except Exception as error:
        if os.geteuid()==0:
            gid=grp.getgrnam('sanequeue').gr_gid
            safety={}
            try:
                previous,_=_read_root_json('/run/sanequeue/pbx-status.json',maximum=32768)
                if previous:
                    safety={key:previous[key] for key in ('notice_snapshot','notice_withdrawn') if key in previous}
            except (OSError,ValueError):pass
            atomic('/run/sanequeue/pbx-status.json',json.dumps({'state':'apply_failed','error':str(error) if isinstance(error,ValueError) else type(error).__name__,'observed_at':time.time(),'applied':False,**safety}).encode(),0,gid)
        raise SystemExit(1)
