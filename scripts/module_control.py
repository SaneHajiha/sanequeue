#!/usr/bin/env python3
"""Emergency operations affect only this module, never the PBX service."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time

UNITS=('sanequeue.service','sanequeue-collector.service','sanequeue-inventory.timer','sanequeue-inventory.service','sanequeue-redis.service')

def without_managed_access(text):
    return re.sub(r'(?m)^; BEGIN SANEQUEUE MANAGED ACCESS\n.*?^; END SANEQUEUE MANAGED ACCESS\n?','',text,flags=re.S)

def remove_managed_ami(manager, backup, reload_manager):
    """Restore the exact original configuration if applying removal fails."""
    if not manager.exists():return
    original=manager.read_text();updated=without_managed_access(original)
    if updated==original:return
    metadata=manager.stat();saved=backup/manager.name
    shutil.copy2(manager,saved)
    try:
        manager.write_text(updated)
        os.chown(manager,metadata.st_uid,metadata.st_gid)
        os.chmod(manager,metadata.st_mode & 0o777)
        if reload_manager():raise RuntimeError('manager_reload_failed')
    except Exception:
        shutil.copy2(saved,manager)
        os.chown(manager,metadata.st_uid,metadata.st_gid)
        os.chmod(manager,metadata.st_mode & 0o777)
        try:reload_manager()
        except Exception:pass
        raise RuntimeError('manager_removal_failed_original_configuration_restored') from None

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('status','disable','enable','uninstall'))
    parser.add_argument('--yes',action='store_true',help='Confirm service removal; private data is retained')
    args=parser.parse_args()
    if os.geteuid()!=0:parser.error('Run with sudo/root')
    def run(*command):return subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=30)
    flag=Path('/var/lib/sanequeue/module.disabled')
    if args.action=='status':
        print(json.dumps({'enabled':not flag.exists(),'services':{unit:run('systemctl','is-active','--quiet',unit).returncode==0 for unit in UNITS}}));return
    if args.action=='enable':
        flag.unlink(missing_ok=True)
        result=run('systemctl','enable','--now',*(unit for unit in UNITS if unit!='sanequeue-inventory.service'))
        if result.returncode:raise RuntimeError('module_start_failed_check_journal')
        print('SaneQueue enabled. Asterisk was not restarted.');return
    if args.action=='uninstall' and not args.yes:parser.error('Use uninstall --yes; configuration and private state will be retained')
    flag.parent.mkdir(parents=True,exist_ok=True)
    descriptor=os.open(flag,os.O_CREAT|os.O_TRUNC|os.O_WRONLY,0o600)
    with os.fdopen(descriptor,'w') as stream:stream.write('Disabled by local administrator\n')
    failures=[]
    for unit in UNITS:
        run('systemctl','disable',unit)
        run('systemctl','stop',unit)
        if run('systemctl','is-active','--quiet',unit).returncode==0:failures.append(unit)
    if failures:raise RuntimeError('module_services_still_active:'+','.join(failures))
    if args.action=='uninstall':
        backup=Path('/var/backups/sanequeue')/(time.strftime('%Y%m%d-%H%M%S')+'-uninstall')
        backup.mkdir(parents=True,mode=0o700)
        manager=Path('/etc/asterisk/manager_custom.conf')
        binary=shutil.which('asterisk') or '/usr/sbin/asterisk'
        remove_managed_ami(manager,backup,lambda:run(binary,'-rx','manager reload').returncode)
        for unit in UNITS:
            target=Path('/etc/systemd/system')/unit
            if target.is_file():shutil.copy2(target,backup/unit);target.unlink()
        run('systemctl','daemon-reload')
        print('SaneQueue services and its managed AMI identities removed. Private configuration, source and data retained for recovery. Backup: '+str(backup))
    else:print('All SaneQueue services stopped and disabled. Use sanequeuectl enable to restore them.')
    print('Asterisk was not restarted; no active PBX channels were hung up.')

if __name__=='__main__':main()
