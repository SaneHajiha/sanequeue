"""Loopback FastAGI: cached lookups and validated internal callback requests."""
import asyncio
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import time

from .features import normalize_number

SPOOL=Path('/var/spool/asterisk/sanequeue')


class Runtime:
    def __init__(self,path=SPOOL/'runtime.json'):
        self.path=Path(path);self.value={};self.loaded=0
    def read(self):
        if time.monotonic()-self.loaded<3:return self.value
        metadata=self.path.stat()
        if self.path.is_symlink() or metadata.st_size>2_000_000 or (os.name!='nt' and (metadata.st_uid!=0 or metadata.st_mode&0o022)):raise ValueError('invalid_runtime')
        value=json.loads(self.path.read_text())
        if not isinstance(value,dict) or not re.fullmatch('[a-f0-9]{64}',value.get('token','')):raise ValueError('invalid_runtime')
        self.value=value;self.loaded=time.monotonic();return value


def dispatch(env,config,spool=SPOOL,*,now=None):
    now=time.time() if now is None else now
    route=env.get('agi_network_script','').split('/')
    if len(route)!=2 or not hmac.compare_digest(route[0],config.get('token','')):return {}
    mode=route[1];settings=config['settings'];phones=config.get('phones',{})
    if (Path(spool)/'disabled').exists():return {}
    if mode=='incident':
        from .incidents import select_notice
        row=select_notice(config,env.get('agi_arg_1',''),env.get('agi_arg_2',''),env.get('agi_arg_3',''),now)
        if row is None:return {'SQ_NOTICE_ENABLED':'0'}
        return {'SQ_NOTICE_ENABLED':'1','SQ_NOTICE_AUDIO':row['audio'],'SQ_NOTICE_REVISION':str(row['revision'])}
    if mode=='normalize':
        number=env.get('agi_callerid','')
        value=normalize_number(number,settings['caller_id']) if settings['caller_id']['enabled'] else number
        return {'SQ_CID_CHANGED':'1' if value!=number else '0','SQ_CID_NUMBER':value if re.fullmatch(r'\+?[0-9]{2,20}',value or '') else ''}
    if mode=='name':
        queue=env.get('agi_arg_1','');number=re.sub(r'[^+0-9]','',env.get('agi_callerid',''))
        name=config.get('directory',{}).get(queue,{}).get(number,'') if settings['caller_id']['directory_names'] else ''
        if env.get('agi_arg_2')=='1' and number in phones.values():name='Callback '+number
        return {'SQ_CONTACT_FOUND':'1' if name else '0','SQ_CONTACT_NAME':name[:100]}
    if mode not in ('menu','enqueue'):return {}
    phone=re.sub(r'-[a-f0-9]{4,}$','',env.get('agi_channel',''),flags=re.I)
    source=phones.get(phone);target=env.get('agi_arg_1','')
    cb=settings['callback'];eligible=bool(cb['enabled'] and source and re.fullmatch('[0-9]{2,8}',target) and target in phones.values() and target!=source)
    audio=settings['audio']
    sound=lambda slot,default:'custom/sanequeue/'+audio[slot] if audio[slot] else default
    if mode=='menu':return {'SQ_MENU_ENABLED':'1' if eligible else '0','SQ_TARGET':target if eligible else '',
        'SQ_CALLBACK_ALLOWED':'1' if cb['callback_enabled'] else '0','SQ_WAIT_ALLOWED':'1' if cb['waiting_enabled'] else '0',
        'SQ_MAX_WAIT':str(cb['max_wait_seconds']),'SQ_MENU_AUDIO':sound('menu','custom/sanequeue/callback-menu-fa'),
        'SQ_CONFIRM_AUDIO':sound('confirmation','enabled&privacy-thankyou'),'SQ_TIMEOUT_AUDIO':sound('wait_timeout','vm-nobodyavail')}
    if not eligible or not cb['callback_enabled']:return {'SQ_JOB_ACCEPTED':'0'}
    folder=Path(spool);jobs=list(folder.glob('job-*.json'))
    if len(jobs)>=200:return {'SQ_JOB_ACCEPTED':'0'}
    for path in jobs:
        try:
            if path.is_symlink() or path.stat().st_size>1024:continue
            row=json.loads(path.read_text())
            if row.get('source')==phone and row.get('target')==target and row.get('expires',0)>now:return {'SQ_JOB_ACCEPTED':'1'}
        except (OSError,ValueError):continue
    token=secrets.token_hex(16);path=folder/('job-'+token+'.json')
    fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY|getattr(os,'O_NOFOLLOW',0),0o640)
    with os.fdopen(fd,'w') as stream:
        json.dump(dict(id=token,source=phone,target=target,created=now,expires=now+cb['expiry_seconds']),stream)
    return {'SQ_JOB_ACCEPTED':'1'}


class FastAGI:
    def __init__(self,runtime=None,spool=SPOOL):self.runtime=runtime or Runtime();self.spool=Path(spool);self.active=0
    async def handle(self,reader,writer):
        if self.active>=32:writer.close();return
        self.active+=1
        try:
            await asyncio.wait_for(self.session(reader,writer),timeout=3)
        except (OSError,ValueError,KeyError,asyncio.TimeoutError):pass
        finally:
            self.active-=1;writer.close()
            try:await writer.wait_closed()
            except OSError:pass

    async def session(self,reader,writer):
        env={};total=0
        for _ in range(100):
            line=await reader.readline();total+=len(line)
            if len(line)>8192 or total>32768:raise ValueError('agi_environment_limit')
            if not line.strip():break
            key,sep,value=line.decode('utf-8',errors='replace').partition(':')
            if sep:env[key.strip()]=value.strip()
        config=await asyncio.to_thread(self.runtime.read)
        values=await asyncio.to_thread(dispatch,env,config,self.spool)
        for key,value in values.items():
            safe=''.join(c for c in str(value) if c.isprintable()).replace('\\','\\\\').replace('"','\\"')[:500]
            writer.write(('SET VARIABLE '+key+' "'+safe+'"\n').encode());await writer.drain()
            reply=await reader.readline()
            if not reply.startswith(b'200'):break


async def main():
    app=FastAGI();server=await asyncio.start_server(app.handle,'127.0.0.1',19051,limit=8193)
    async with server:await server.serve_forever()


if __name__=='__main__':asyncio.run(main())
