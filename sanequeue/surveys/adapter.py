"""Opt-in loopback survey adapter; no route installation or AMI polling."""
import argparse
import asyncio
import hashlib
import hmac
import io
import json
import os
from pathlib import Path
import re
import stat
import threading
import time
import wave

from .store import SurveyStore,ID


def configuration(path='/etc/sanequeue/survey-bindings.json',*,owner_uid=0):
    """Only root-approved form versions and installed local PCM prompts."""
    path=Path(path)
    try:
        if path.is_symlink():return None
        fd=os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_NONBLOCK',0))
        with os.fdopen(fd,'rb') as stream:
            meta=os.fstat(stream.fileno())
            if not stat.S_ISREG(meta.st_mode) or meta.st_size>65536 or meta.st_nlink!=1:return None
            if os.name!='nt' and (meta.st_uid!=owner_uid or meta.st_mode&0o022):return None
            config=json.loads(stream.read(65537))
        if not isinstance(config,dict) or not re.fullmatch('[a-f0-9]{64}',config.get('token','')):return None
        rows=config.get('bindings')
        if not isinstance(rows,dict) or len(rows)>100:return None
        result={}
        for key,row in rows.items():
            if not re.fullmatch('[A-Za-z0-9_-]{1,32}',key) or not isinstance(row,dict):return None
            if not re.fullmatch('[A-Za-z0-9_-]{1,32}',row.get('queue','')) or not ID.fullmatch(row.get('form_id','')) or type(row.get('form_version')) is not int or row['form_version']<1:return None
            if not isinstance(row.get('enabled',False),bool):return None
            prompts=row.get('prompts')
            if not isinstance(prompts,dict) or not 1<=len(prompts)<=10:return None
            for prompt,sound in prompts.items():
                if not re.fullmatch('[a-z][a-z0-9_]{0,31}',prompt) or not isinstance(sound,str) or not re.fullmatch('[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+){0,8}',sound) or len(sound)>120:return None
            result[key]=dict(queue=row['queue'],form_id=row['form_id'],form_version=row['form_version'],enabled=row.get('enabled',False),prompts=prompts)
        return dict(token=config['token'],bindings=result)
    except (OSError,ValueError,TypeError):return None


def verify_prompts(binding,root='/var/lib/asterisk/sounds',*,cache=None):
    """Checked file metadata, not proof of playback/hearing. No decoders or TTS.

    Root-managed prompt fingerprints avoid rehashing unchanged files per caller.
    The PBX later opens the pathname itself: these hashes cannot prove what a
    caller heard, and administrative replacement can race that later open.
    """
    root=Path(root).resolve()
    hashes={}
    for key,sound in binding['prompts'].items():
        path=root/(sound+'.wav')
        if path.is_symlink() or root not in path.resolve().parents:raise ValueError('unsafe_survey_prompt')
        fd=os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_NONBLOCK',0))
        with os.fdopen(fd,'rb') as stream:
            meta=os.fstat(stream.fileno())
            if not stat.S_ISREG(meta.st_mode) or meta.st_size>250000:raise ValueError('invalid_survey_prompt')
            fingerprint=(meta.st_dev,meta.st_ino,meta.st_size,meta.st_mtime_ns)
            cached=cache.get(str(path)) if cache is not None else None
            if cached and cached[0]==fingerprint:
                hashes[key]=cached[1];continue
            content=stream.read(250001)
        with wave.open(io.BytesIO(content),'rb') as audio:
            frames=audio.getnframes()
            if (audio.getnchannels(),audio.getsampwidth(),audio.getframerate(),audio.getcomptype())!=(1,2,8000,'NONE') or not 0<frames<=120000 or len(audio.readframes(frames))!=frames*2:raise ValueError('invalid_survey_prompt')
        hashes[key]=hashlib.sha256(content).hexdigest()
        if cache is not None:
            if len(cache)>=128:cache.clear()
            cache[str(path)]=(fingerprint,hashes[key])
    return hashes


class QueueEvidence:
    """Incremental local tail, at most 256 KiB; incomplete lines never prove a call."""
    def __init__(self,path='/var/log/asterisk/queue_log'):
        self.path=Path(path);self.lines=[];self.lock=threading.RLock();self.identity=None;self.offset=0;self.data=b''
    def read(self):
        with self.lock:
            fd=os.open(self.path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_NONBLOCK',0))
            with os.fdopen(fd,'rb') as stream:
                meta=os.fstat(stream.fileno())
                if not stat.S_ISREG(meta.st_mode):raise ValueError('invalid_queue_log')
                identity=(meta.st_dev,meta.st_ino)
                append=identity==self.identity and self.offset<=meta.st_size and meta.st_size-self.offset<=262144
                if append and self.offset==meta.st_size:return self.lines
                offset=self.offset if append else max(0,meta.st_size-262144)
                stream.seek(offset)
                if offset and not append:stream.readline(4097)
                chunk=stream.read(262144);self.offset=stream.tell();self.identity=identity
                data=(self.data if append else b'')+chunk
                if len(data)>262144:
                    data=data[-262144:];cut=data.find(b'\n');data=data[cut+1:] if cut>=0 else b''
                self.data=data
                complete=data.rsplit(b'\n',1)[0] if b'\n' in data else b''
                lines=complete.decode('utf-8',errors='replace').splitlines()
            self.lines=[line for line in lines if len(line)<=4096];return self.lines
    def prove(self,caller,queue,now):
        if not isinstance(caller,str) or not re.fullmatch('[A-Za-z0-9_.-]{1,100}',caller):return None
        entered=None;connected=None;complete=None
        for line in self.read():
            parts=line.split('|',5)
            if len(parts)<5 or parts[1]!=caller or parts[2]!=queue:continue
            event=parts[4]
            if event=='ENTERQUEUE':entered=line;connected=None;complete=None
            elif event=='CONNECT' and entered:
                if connected:entered=None;connected=None;complete=None
                else:connected=line;complete=None
            elif event in ('TRANSFER','BLINDTRANSFER','ATTENDEDTRANSFER','COMPLETECALLER','ABANDON','EXITWITHTIMEOUT','EXITWITHKEY','EXITEMPTY'):entered=None;connected=None;complete=None
            elif event=='COMPLETEAGENT':
                if not connected or parts[3]!=connected.split('|',5)[3] or complete and complete!=line:entered=None;connected=None;complete=None
                else:complete=line
        if not complete:return None
        finished=complete.split('|',5)
        try:
            if not -5<=now-float(finished[0])<=30:return None
        except ValueError:return None
        return dict(queue=queue,agent=finished[3],caller_uniqueid=caller,visit_proof=hashlib.sha256((entered+'\n'+connected+'\n'+complete).encode()).hexdigest(),source='queue_log_completeagent')


class Runtime:
    def __init__(self,state,config_path,*,evidence=None,sounds='/var/lib/asterisk/sounds',enabled_marker=None):
        self.store=SurveyStore(state);self.store.initialize();self.config_path=config_path;self.evidence=evidence or QueueEvidence();self.sounds=sounds;self.prompt_cache={}
        self.enabled_marker=Path(enabled_marker) if enabled_marker is not None else Path(config_path).with_name('surveys.enabled')
    def dispatch(self,env,*,now=None):
        # Recheck emergency withdrawal on every AGI request, not only at startup.
        if (self.store.state/'module.disabled').exists() or not self.enabled_marker.is_file() or self.enabled_marker.is_symlink():return {}
        now=time.time() if now is None else now;config=configuration(self.config_path)
        route=env.get('agi_network_script','').split('/')
        if not config or len(route)!=2 or not hmac.compare_digest(route[0],config['token']):return {}
        caller=env.get('agi_uniqueid','');mode=route[1]
        if mode=='start':
            binding_id=env.get('agi_arg_1','');binding=config['bindings'].get(binding_id)
            if not binding or not binding['enabled']:return {}
            proof=self.evidence.prove(caller,binding['queue'],now)
            if not proof:return {}
            proof.update(binding=binding_id,prompt_map=binding['prompts'],checked_prompt_hashes=verify_prompts(binding,self.sounds,cache=self.prompt_cache))
            observed_linkedid=env.get('agi_arg_2','')
            if re.fullmatch('[A-Za-z0-9_.-]{1,100}',observed_linkedid):proof['observed_linkedid']=observed_linkedid
            response=self.store.start(binding,proof,now=now)
        elif mode in ('answer','hangup'):
            ident=env.get('agi_arg_1','');sequence=env.get('agi_arg_2','')
            if not re.fullmatch('[0-9]{1,2}',sequence):return {}
            response=self.store.answer(ident,int(sequence),'hangup' if mode=='hangup' else env.get('agi_arg_3','timeout'),caller_uniqueid=caller,now=now)
            # The form and queue stay frozen; withdrawal of its approved binding
            # prevents another question without relabeling the historic answers.
            binding=config['bindings'].get(response['binding'])
            if not binding or not binding['enabled'] or binding['queue']!=response['queue'] or binding['form_id']!=response['form_id'] or binding['form_version']!=response['version'] or binding['prompts']!=response['prompt_map']:return {}
            if response['state']=='active' and verify_prompts(binding,self.sounds,cache=self.prompt_cache)!=response['checked_prompt_hashes']:return {}
        else:return {}
        if binding['queue']!=response['queue'] or binding['form_id']!=response['form_id'] or binding['form_version']!=response['version'] or binding['prompts']!=response['prompt_map']:return {}
        question=response['question'] if response['state']=='active' else None
        values=dict(SQ_SURVEY_ID=response['id'],SQ_SURVEY_SEQUENCE=str(response['sequence']),SQ_SURVEY_READY='1' if question else '0',SQ_SURVEY_STATE=response['state'])
        if question:values.update(SQ_SURVEY_AUDIO=binding['prompts'][question['prompt']],SQ_SURVEY_TIMEOUT=str(question['timeout_seconds']))
        return values


def dialplan(token):
    if not isinstance(token,str) or not re.fullmatch('[a-f0-9]{64}',token):raise ValueError('invalid_survey_token')
    return '''; Explicit opt-in subroutine only; install after a reviewed Queue(...,c...) call.
[sanequeue-customer-survey]
exten => s,1,Set(SQ_SURVEY_READY=0)
 same => n,Set(SQ_SURVEY_ID=)
 same => n,AGI(agi://127.0.0.1:19052/TOKEN/start,${ARG1},${CHANNEL(linkedid)})
 same => n,GotoIf($["${SQ_SURVEY_READY}"!="1"]?done)
 same => n,Set(CHANNEL(hangup_handler_push)=sanequeue-survey-finish,s,1)
 same => n,Set(SQ_SURVEY_STEPS=0)
 same => n(question),Set(SQ_SURVEY_DIGIT=)
 same => n,Read(SQ_SURVEY_DIGIT,${SQ_SURVEY_AUDIO},1,,1,${SQ_SURVEY_TIMEOUT})
 same => n,ExecIf($["${SQ_SURVEY_DIGIT}"=""]?Set(SQ_SURVEY_DIGIT=timeout))
 same => n,Set(SQ_SURVEY_READY=0)
 same => n,AGI(agi://127.0.0.1:19052/TOKEN/answer,${SQ_SURVEY_ID},${SQ_SURVEY_SEQUENCE},${SQ_SURVEY_DIGIT})
 same => n,Set(SQ_SURVEY_STEPS=$[${SQ_SURVEY_STEPS}+1])
 same => n,GotoIf($["${SQ_SURVEY_READY}"="1" & ${SQ_SURVEY_STEPS}<10]?question)
 same => n(done),Return()

[sanequeue-survey-finish]
exten => s,1,AGI(agi://127.0.0.1:19052/TOKEN/hangup,${SQ_SURVEY_ID},${SQ_SURVEY_SEQUENCE})
 same => n,Return()
'''.replace('TOKEN',token)


class Server:
    def __init__(self,runtime):self.runtime=runtime;self.active=0
    async def handle(self,reader,writer):
        if self.active>=32:writer.close();return
        self.active+=1
        try:await asyncio.wait_for(self.session(reader,writer),2)
        except Exception:pass
        finally:
            self.active-=1;writer.close()
            try:await writer.wait_closed()
            except OSError:pass
    async def session(self,reader,writer):
        env={};total=0
        for _ in range(100):
            line=await reader.readline();total+=len(line)
            if len(line)>4096 or total>16384:raise ValueError('survey_agi_limit')
            if not line.strip():break
            key,sep,value=line.decode(errors='replace').partition(':')
            if sep:env[key.strip()]=value.strip()
        values=await asyncio.to_thread(self.runtime.dispatch,env)
        for key,value in values.items():
            safe=str(value).replace('\\','\\\\').replace('"','\\"')
            writer.write(('SET VARIABLE '+key+' "'+safe+'"\n').encode());await writer.drain()
            if not (await reader.readline()).startswith(b'200'):break


async def serve(args):
    runtime=Runtime(args.state,args.config,evidence=QueueEvidence(args.queue_log),sounds=args.sounds)
    server=await asyncio.start_server(Server(runtime).handle,'127.0.0.1',19052,limit=4097)
    async with server:await server.serve_forever()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--state',default='/var/lib/sanequeue');parser.add_argument('--config',default='/etc/sanequeue/survey-bindings.json');parser.add_argument('--queue-log',default='/var/log/asterisk/queue_log');parser.add_argument('--sounds',default='/var/lib/asterisk/sounds');parser.add_argument('--render',action='store_true');args=parser.parse_args()
    if args.render:
        config=configuration(args.config)
        if not config:raise SystemExit('Root-approved survey configuration is unavailable')
        print(dialplan(config['token']))
    else:asyncio.run(serve(args))


if __name__=='__main__':main()
