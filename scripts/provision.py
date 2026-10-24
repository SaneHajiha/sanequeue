#!/usr/bin/env python3
"""Provision a single-node local Issabel/Asterisk install with reversible changes."""
import argparse,configparser,getpass,grp,ipaddress,json,os,pwd,re,secrets,shutil,socket,subprocess,sys,time
import stat
from pathlib import Path
from urllib.parse import urlparse
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from qpanel.local_accounts import read_accounts,set_account
from sanequeue.realtime.local_inventory import snapshot

BEGIN='; BEGIN SANEQUEUE MANAGED ACCESS'
END='; END SANEQUEUE MANAGED ACCESS'


def manager_block(original,collector_secret,control_secret):
    block=BEGIN+'\n'
    for name,secret,write in (('sanequeue_collector_auto',collector_secret,'reporting'),('sanequeue_control_auto',control_secret,'agent,call,originate,reporting')):
        block+=f'[{name}]\nsecret = {secret}\ndeny = 0.0.0.0/0.0.0.0\npermit = 127.0.0.1/255.255.255.255\nread = system,call,agent,reporting\nwrite = {write}\nwritetimeout = 1000\n\n'
    block+=END+'\n'
    pattern=re.escape(BEGIN)+r'.*?'+re.escape(END)+r'\n?'
    remainder=re.sub(pattern,'',original,flags=re.S)
    if re.search(r'^\[sanequeue_(collector|control)_auto\]',remainder,re.M):raise ValueError('managed_ami_name_collision')
    return remainder.rstrip()+'\n\n'+block


def run(args,**kwargs):
    return subprocess.run(args,check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=kwargs.pop('timeout',30),**kwargs)


def origin_default():
    for token in subprocess.check_output(['hostname','-I']).decode().split():
        try:
            address=ipaddress.ip_address(token)
            if address.version==4 and address.is_private and not address.is_loopback:return 'http://'+str(address)+':5000'
        except ValueError:pass
    return 'http://127.0.0.1:5000'


def validate_origin(value):
    parsed=urlparse(value)
    if any(ord(c)<33 for c in value) or parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password or parsed.path not in ('','/') or parsed.query or parsed.fragment:
        raise ValueError('invalid_public_origin')
    if parsed.port is not None and not 1<=parsed.port<=65535:raise ValueError('invalid_public_origin')
    return value.rstrip('/')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--release',type=Path,required=True);parser.add_argument('--check',action='store_true')
    args=parser.parse_args()
    if os.geteuid()!=0:raise RuntimeError('root_required')
    release=args.release.resolve()
    if not release.is_relative_to(Path('/opt')) or not (release/'sanequeue/asgi.py').is_file():raise ValueError('invalid_release_directory')
    asterisk=shutil.which('asterisk');redis=shutil.which('redis-server')
    if not asterisk or not redis:raise RuntimeError('asterisk_and_redis_required')
    run([asterisk,'-rx','core show version'])
    with socket.create_connection(('127.0.0.1',5038),timeout=3):pass
    manager=Path('/etc/asterisk/manager.conf');custom=Path('/etc/asterisk/manager_custom.conf')
    if not manager.is_file():raise RuntimeError('asterisk_manager_config_missing')
    if args.check:
        print(json.dumps({'preflight':'passed','python':sys.version.split()[0],'system_python_unchanged':True,'automatic_queue_discovery':True}));return
    state=Path('/var/lib/sanequeue');etc=Path('/etc/sanequeue');link=Path('/opt/sanequeue')
    existing=read_accounts(state/'local_accounts.json')
    username=password=phone=None
    if not existing:
        username=input('Administrator username [admin]: ').strip() or 'admin'
        password=getpass.getpass('Choose administrator password (12-200 characters): ')
        if not 12<=len(password)<=200 or password!=getpass.getpass('Repeat administrator password: '):raise ValueError('passwords_must_match_12_to_200')
        inventory=snapshot();phones=[r['technology']+'/'+r['endpoint'] for r in inventory['endpoints'] if r['category']=='extension']
        print('Detected internal phones: '+(', '.join(phones) or 'none'))
        phone=input('Administrator supervisor phone [none; can change in profile]: ').strip()
        if phone and phone not in phones:raise ValueError('select_a_detected_internal_phone')
    origin=validate_origin(os.getenv('SANEQUEUE_PUBLIC_ORIGIN') or input('Panel origin ['+origin_default()+']: ').strip() or origin_default())
    parsed=urlparse(origin);bind='127.0.0.1'
    try:
        address=ipaddress.ip_address(parsed.hostname)
        if address.is_private and address.version==4 and parsed.scheme=='http':bind=str(address)
    except ValueError:pass
    web_port=parsed.port or 5000 if parsed.scheme=='http' and bind!='127.0.0.1' else 5000
    if not 1024<=web_port<=65535 or web_port in (5038,5060,5061,16379):raise ValueError('choose_a_non_pbx_web_port')
    probe=socket.socket();occupied=probe.connect_ex(('127.0.0.1',16379))==0;probe.close()
    if occupied and subprocess.run(['systemctl','is-active','--quiet','sanequeue-redis']).returncode:
        raise RuntimeError('private_redis_port_in_use_by_another_service')
    stamp=time.strftime('%Y%m%d-%H%M%S')
    backup=Path('/var/backups/sanequeue')/(stamp+'-installer');backup.mkdir(parents=True,mode=0o700)
    os.chmod(backup,0o700)
    units=('sanequeue.service','sanequeue-collector.service','sanequeue-redis.service','sanequeue-inventory.service','sanequeue-inventory.timer')
    active={unit:subprocess.run(['systemctl','is-active','--quiet',unit]).returncode==0 for unit in units}
    old_link=str(link.resolve()) if link.exists() else None
    old_physical=None
    created_control_link=False
    changed=[]
    try:
        for unit in ('sanequeue.service','sanequeue-collector.service','sanequeue-inventory.timer'):
            subprocess.run(['systemctl','stop',unit],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        if etc.exists():shutil.copytree(etc,backup/'etc')
        if state.exists():shutil.copytree(state,backup/'state',symlinks=True)
        shutil.copy2(manager,backup/'manager.conf')
        if custom.exists():shutil.copy2(custom,backup/'manager_custom.conf')
        for unit in units:
            path=Path('/etc/systemd/system')/unit
            if path.exists():shutil.copy2(path,backup/unit)
        if subprocess.run(['id','sanequeue'],stdout=subprocess.PIPE,stderr=subprocess.PIPE).returncode:
            run(['useradd','--system','--home-dir',str(state),'--shell','/sbin/nologin','sanequeue'])
        owner=pwd.getpwnam('sanequeue');group=grp.getgrnam('sanequeue')
        etc.mkdir(parents=True,exist_ok=True);os.chown(etc,0,group.gr_gid);os.chmod(etc,0o750)
        state.mkdir(parents=True,exist_ok=True)
        def private(path,content):
            path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
            with os.fdopen(os.open(path,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o640),'w') as stream:stream.write(content)
            os.chown(path,0,group.gr_gid);os.chmod(path,0o640);changed.append(path)
        def asterisk_config(path,content):
            previous=path.stat() if path.exists() else None
            with os.fdopen(os.open(path,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o640),'w') as stream:stream.write(content)
            os.chown(path,previous.st_uid if previous else 0,previous.st_gid if previous else grp.getgrnam('asterisk').gr_gid)
            os.chmod(path,stat.S_IMODE(previous.st_mode) if previous else 0o640)
        read_secret,control_secret,redis_secret=(secrets.token_hex(32) for _ in range(3))
        old_custom=custom.read_text() if custom.exists() else ''
        asterisk_config(custom,manager_block(old_custom,read_secret,control_secret))
        manager_text=manager.read_text()
        if not re.search(r'^\s*#(?:try)?include\s+["<]?manager_custom\.conf',manager_text,re.M):
            asterisk_config(manager,manager_text.rstrip()+'\n#include manager_custom.conf\n')
        run([asterisk,'-rx','manager reload'])
        cfg=configparser.ConfigParser(interpolation=None);cfg.read(etc/'config.ini')
        cfg['manager']={'host':'127.0.0.1','port':'5038','user':'sanequeue_collector_auto','password':read_secret}
        if not cfg.has_section('general'):cfg.add_section('general')
        for key,value in dict(host=bind,port=str(parsed.port or (443 if parsed.scheme=='https' else 5000)),language='fa',interval='5',debug='False',check_upgrade='False',theme='qpanel').items():cfg['general'][key]=value
        if not cfg['general'].get('secret_key'):cfg['general']['secret_key']=secrets.token_hex(32)
        if not existing:set_account(state/'local_accounts.json',username,'admin',phone,password)
        accounts=read_accounts(state/'local_accounts.json');cfg['users']={u:a['password_hash'] for u,a in accounts.items()};cfg['roles']={u:a['role'] for u,a in accounts.items()}
        if not cfg.has_section('sanequeue'):cfg.add_section('sanequeue')
        cfg['sanequeue'].update(queue_log_path='/var/log/asterisk/queue_log',report_database=str(state/'reports.sqlite3'),reports_enabled='false')
        import io
        output=io.StringIO();cfg.write(output);private(etc/'config.ini',output.getvalue())
        private(etc/'collector.ini',f'[ami]\nhost=127.0.0.1\nport=5038\nuser=sanequeue_collector_auto\npassword={read_secret}\n[collector]\nredis_url=redis://:{redis_secret}@127.0.0.1:16379/0\npbx_id=primary\nreconcile_seconds=120\npublish_seconds=1\nheartbeat_seconds=10\n')
        private(etc/'control.ini',f'[ami]\nhost=127.0.0.1\nport=5038\nuser=sanequeue_control_auto\npassword={control_secret}\n')
        private(etc/'gateway.env',f'SANEQUEUE_PUBLIC_ORIGINS={origin},http://127.0.0.1:5000\nSANEQUEUE_HTTPS={int(parsed.scheme=="https")}\nSANEQUEUE_CONTROL_MODE=rbac\nSANEQUEUE_ADVANCED_ACTIONS=transfer,attended_transfer,cancel_transfer,park,retrieve,pickup,dial,hangup_active\nSANEQUEUE_TRANSFER_CONTEXT=from-internal\nSANEQUEUE_PARKING_LOT=default\nSANEQUEUE_AUTO_EXTENSIONS=1\n')
        private(etc/'redis.conf',f'bind 127.0.0.1\nport 16379\nprotected-mode yes\nrequirepass {redis_secret}\nsave ""\nappendonly no\nmaxmemory 128mb\nmaxmemory-policy noeviction\ndaemonize no\n')
        for root,dirs,files in os.walk(state):
            os.chown(root,owner.pw_uid,group.gr_gid);os.chmod(root,0o750)
            for name in files:os.chown(Path(root)/name,owner.pw_uid,group.gr_gid);os.chmod(Path(root)/name,0o600)
        if link.exists() and not link.is_symlink():
            if not link.resolve().is_relative_to(Path('/opt')):raise ValueError('unsafe_existing_source')
            old_physical=Path('/opt')/('sanequeue-before-'+stamp);link.rename(old_physical)
        elif link.is_symlink():link.unlink()
        link.symlink_to(release,target_is_directory=True)
        controller=release/'scripts/sanequeuectl';controller.chmod(0o755)
        control_link=Path('/usr/local/sbin/sanequeuectl')
        if control_link.exists() or control_link.is_symlink():
            if not control_link.is_symlink() or str(control_link.readlink())!='/opt/sanequeue/scripts/sanequeuectl':raise RuntimeError('sanequeuectl_path_collision')
        else:
            control_link.symlink_to('/opt/sanequeue/scripts/sanequeuectl');created_control_link=True
        for source,destination in (('sanequeue-asgi.service','sanequeue.service'),('sanequeue-collector.service','sanequeue-collector.service'),('sanequeue-inventory.service','sanequeue-inventory.service'),('sanequeue-inventory.timer','sanequeue-inventory.timer')):
            text=(release/'deploy'/source).read_text()
            if destination=='sanequeue.service':text=text.replace('--host 127.0.0.1 --port 5000','--host '+bind+' --port '+str(web_port))
            (Path('/etc/systemd/system')/destination).write_text(text)
        redis_unit=f'[Unit]\nDescription=SaneQueue private Redis cache\nAfter=network.target\n[Service]\nUser=sanequeue\nGroup=sanequeue\nExecStart={redis} /etc/sanequeue/redis.conf\nRestart=on-failure\nNoNewPrivileges=true\nPrivateTmp=true\nProtectSystem=strict\nProtectHome=true\n[Install]\nWantedBy=multi-user.target\n'
        Path('/etc/systemd/system/sanequeue-redis.service').write_text(redis_unit)
        run(['systemctl','daemon-reload']);run(['systemctl','restart','sanequeue-redis'])
        run(['systemctl','start','sanequeue-inventory.service'])
        run(['systemctl','enable','--now','sanequeue-inventory.timer','sanequeue-collector.service','sanequeue.service','sanequeue-redis.service'])
        from redis import Redis
        cache=Redis(host='127.0.0.1',port=16379,password=redis_secret,socket_timeout=3)
        maintenance=(state/'module.disabled').exists()
        ready=maintenance
        for _ in range(30):
            if ready:break
            raw=cache.get('sanequeue:{primary}:health')
            if raw:
                health=json.loads(raw)
                if health.get('connected') and health.get('complete'):ready=True;break
            time.sleep(1)
        cache.close()
        if not ready:raise RuntimeError('collector_acceptance_failed')
        import urllib.request
        gateway_ready=False
        for _ in range(30):
            try:
                with urllib.request.urlopen('http://'+bind+':'+str(web_port)+'/login',timeout=2) as response:
                    gateway_ready=response.status==200
            except (OSError,urllib.error.URLError):pass
            if gateway_ready:break
            time.sleep(1)
        if not gateway_ready:raise RuntimeError('gateway_acceptance_failed')
        print('SaneQueue installed. Open '+origin+'/operations')
        print('Queues and internal phones are discovered automatically. No default administrator password exists.')
        print('Private rollback backup: '+str(backup))
        (backup/'result.json').write_text(json.dumps({'release':str(release),'previous_source':old_link,'origin':origin,'succeeded':True}))
    except Exception:
        if created_control_link:
            control_link.unlink(missing_ok=True)
        for unit in units:subprocess.run(['systemctl','stop',unit],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        if link.is_symlink():link.unlink()
        if old_physical and old_physical.exists():old_physical.rename(link)
        elif old_link:link.symlink_to(old_link,target_is_directory=True)
        for path,name in ((manager,'manager.conf'),(custom,'manager_custom.conf')):
            if (backup/name).exists():shutil.copy2(backup/name,path)
            elif path==custom and path.exists():path.unlink()
        for unit in units:
            target=Path('/etc/systemd/system')/unit
            if (backup/unit).exists():shutil.copy2(backup/unit,target)
            elif target.exists():target.unlink()
        if (backup/'etc').exists():shutil.copytree(backup/'etc',etc,dirs_exist_ok=True)
        if (backup/'state').exists():shutil.copytree(backup/'state',state,dirs_exist_ok=True,symlinks=True)
        run([asterisk,'-rx','manager reload']);run(['systemctl','daemon-reload'])
        for unit,was_active in active.items():
            if was_active:subprocess.run(['systemctl','start',unit],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        print('Installation failed; previous source/configuration/services restored. Backup: '+str(backup),file=sys.stderr)
        raise


if __name__=='__main__':
    try:main()
    except Exception as error:
        # Never reflect credential-bearing URLs, config values or provider errors.
        print('Installer stopped: '+(str(error) if isinstance(error,(RuntimeError,ValueError)) else type(error).__name__),file=sys.stderr)
        raise SystemExit(1)
