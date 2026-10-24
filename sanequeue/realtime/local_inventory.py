"""Local, redacted PBX inventory. Run the exporter as a root-owned timer.

The web worker never executes CLI commands or reads SIP authentication files.
"""
import argparse
import json
import math
import os
from pathlib import Path
import re
import subprocess
import shutil
import tempfile
import time

IDENTIFIER = re.compile(r'[A-Za-z0-9_.-]{1,48}\Z')
CONFIGS = {'PJSIP': ('pjsip_additional.conf','pjsip_custom.conf','pjsip_custom_post.conf'),
           'SIP': ('sip_additional.conf','sip_custom.conf','sip_custom_post.conf')}


def definitions(text, technology):
    """Read only type/context; never retain passwords, contacts or network addresses."""
    result=[];current=None
    for raw in text.splitlines():
        line=raw.split(';',1)[0].strip()
        match=re.match(r'^\[([^\]]+)\]',line)
        if match:
            current={'endpoint':match[1]};result.append(current)
        elif current is not None and '=' in line:
            key,value=line.split('=',1);key=key.strip().lower()
            if key in ('context','type'):current[key]=value.strip()
    return [dict(endpoint=r['endpoint'],technology=technology,category='extension' if r['context']=='from-internal' else 'trunk')
            for r in result if IDENTIFIER.fullmatch(r['endpoint']) and r.get('context')
            and (r.get('type')=='endpoint' if technology=='PJSIP' else r.get('type') in ('friend','peer','user'))]


def endpoint_states(text, technology):
    states={}
    for line in text.splitlines():
        if technology=='PJSIP':
            match=re.match(r'^\s*Endpoint:\s+([A-Za-z0-9_.-]+)(?:/\S+)?\s+(.+?)\s+\d+\s+of\s+',line)
        else:
            match=re.match(r'^([A-Za-z0-9_.-]+)(?:/\S+)?\s+.*?\s+(OK \(\d+ ms\)|UNREACHABLE|UNKNOWN|Unmonitored)\s*(?:\s+.*)?$',line,re.I)
        if match:states[match[1]]=match[2].strip()[:48]
    return states


def snapshot(config_dir=Path('/etc/asterisk')):
    rows={};drivers={}
    for technology,files in CONFIGS.items():
        try:
            command='pjsip show endpoints' if technology=='PJSIP' else 'sip show peers'
            result=subprocess.run([shutil.which('asterisk') or '/usr/sbin/asterisk','-rx',command],capture_output=True,timeout=5,check=True)
            text=result.stdout[:1024*1024].decode(errors='replace')
            drivers[technology]='No such command' not in text and 'Unable to connect' not in text
            states=endpoint_states(text,technology)
        except (OSError,subprocess.SubprocessError):
            drivers[technology]=False;states={}
        for name in files:
            path=config_dir/name
            if not path.is_file() or path.stat().st_size>10*1024*1024:continue
            for row in definitions(path.read_text(errors='replace'),technology):
                row['state']=states.get(row['endpoint'],'Unknown')
                state=row['state'].lower().replace('_',' ')
                row['reachable']=state.startswith('ok') or state in ('not in use','in use','busy','ringing','ring+inuse')
                match=re.search(r'OK \((\d+) ms\)',row['state'],re.I)
                row['qualify_rtt_ms']=int(match[1]) if match else None
                rows[(technology,row['endpoint'])]=row
    return dict(observed_at=time.time(),source='local-read-only-adapter',drivers=drivers,endpoints=list(rows.values())[:2000])


def read_snapshot(path, *, now=None):
    try:
        path=Path(path)
        if path.stat().st_size>1024*1024:return None
        data=json.loads(path.read_text())
        age=(time.time() if now is None else now)-float(data['observed_at'])
        if not math.isfinite(age) or age<0 or age>90:return None
        rows=data.get('endpoints')
        if not isinstance(rows,list) or len(rows)>2000:return None
        if any(not isinstance(row,dict) or row.get('technology') not in ('SIP','PJSIP') or row.get('category') not in ('extension','trunk') or not isinstance(row.get('endpoint'),str) or not IDENTIFIER.fullmatch(row['endpoint']) for row in rows):return None
        return data
    except (OSError,ValueError,KeyError,TypeError):return None


def projection(data, category):
    rows=[r for r in data['endpoints'] if r['category']==category]
    available=sum(r['state'].lower() in ('not in use','not_inuse','idle','avail','available') or r['state'].lower().startswith('ok') for r in rows)
    return dict(kind='extensions' if category=='extension' else 'trunks',supported=True,
                source=data['source'],observed_at=data['observed_at'],drivers=data['drivers'],complete=all(data['drivers'].get(row['technology'],False) for row in rows),
                data=dict(total=len(rows),available=available,endpoints=rows))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',default='/run/sanequeue/inventory.json')
    options=parser.parse_args()
    target=Path(options.output);target.parent.mkdir(parents=True,exist_ok=True)
    descriptor,temporary=tempfile.mkstemp(prefix='.inventory-',dir=target.parent)
    try:
        with os.fdopen(descriptor,'w') as stream:
            json.dump(snapshot(),stream);stream.flush();os.fsync(stream.fileno())
        # The systemd unit supplies root:sanequeue and a private parent directory.
        import grp
        os.chown(temporary,0,grp.getgrnam('sanequeue').gr_gid);os.chmod(temporary,0o640)
        os.replace(temporary,target)
    finally:
        if os.path.exists(temporary):os.unlink(temporary)


if __name__=='__main__':main()
