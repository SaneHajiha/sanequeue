#!/usr/bin/env python3
"""Emergency operations affect only this module, never the PBX service."""
import sys
sys.path.insert(0,str(__import__('pathlib').Path(__file__).resolve().parents[1]))
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
import tempfile
from contextlib import contextmanager

UNITS=('sanequeue.service','sanequeue-collector.service','sanequeue-inventory.timer','sanequeue-inventory.service','sanequeue-redis.service','sanequeue-fastagi.service','sanequeue-pbx-apply.timer','sanequeue-pbx-apply.service','sanequeue-reporting.service','sanequeue-reporting-export.service','sanequeue-reporting-plans.service','sanequeue-reporting-ai.service','sanequeue-media.service','sanequeue-surveys.service','sanequeue-generative.service')

# These are worker/service controls, not web-menu permissions or PBX features.
SERVICE_MODULES={
    'monitoring':('sanequeue-collector.service','sanequeue-inventory.timer','sanequeue-inventory.service'),
    'reporting':('sanequeue-reporting.service',),
    'exports':('sanequeue-reporting-export.service',),
    'plans':('sanequeue-reporting-plans.service',),
    'ai':('sanequeue-reporting-ai.service',),
    'surveys':('sanequeue-surveys.service',),
    'generative':('sanequeue-generative.service',),
    'media':('sanequeue-media.service',),
}
DEPENDENCIES={'exports':('reporting',),'plans':('exports',),
              'ai':('reporting',),'generative':('ai',)}
REQUIREMENTS={'ai':('reporting-ai.enabled','reporting-ai.env'),
              'surveys':('surveys.enabled','survey-bindings.json'),
              'generative':('generative.enabled','generative.json')}
DROPIN='70-sanequeue-service-control.conf'


def service_module(unit):
    return next((name for name,units in SERVICE_MODULES.items() if unit in units),None)


def module_disabled(name,config_dir=Path('/etc/sanequeue')):
    if name not in SERVICE_MODULES:raise ValueError('unsupported_service_module')
    marker=Path(config_dir)/'modules'/(name+'.disabled')
    # A symlink is not accepted as an enable signal; fail closed.
    return marker.exists() or marker.is_symlink()


def module_dependencies(name):
    result=set(DEPENDENCIES.get(name,()))
    for dependency in tuple(result):result.update(module_dependencies(dependency))
    return result


def allowed_start_units(units,config_dir=Path('/etc/sanequeue')):
    return tuple(unit for unit in units if not service_module(unit)
                 or not any(module_disabled(name,config_dir) for name in {service_module(unit),*module_dependencies(service_module(unit))}))


def collector_acceptance_required(state_dir=Path('/var/lib/sanequeue'),config_dir=Path('/etc/sanequeue')):
    return not (Path(state_dir)/'module.disabled').exists() and not module_disabled('monitoring',config_dir)


def _safe_file(path):
    if path.is_symlink() or (path.exists() and not path.is_file()):raise ValueError('unsafe_service_control_file')
    return path.read_bytes() if path.exists() else None


def _write(path,value,mode=0o600):
    _safe_file(path)
    if value is None:
        path.unlink(missing_ok=True);return
    if path.parent.is_symlink():raise ValueError('unsafe_service_control_directory')
    path.parent.mkdir(parents=True,exist_ok=True)
    descriptor,temporary=tempfile.mkstemp(prefix='.service-control-',dir=path.parent)
    try:
        with os.fdopen(descriptor,'wb') as stream:stream.write(value);stream.flush();os.fsync(stream.fileno())
        os.chmod(temporary,mode);os.replace(temporary,path)
    finally:
        if os.path.exists(temporary):os.unlink(temporary)


@contextmanager
def _control_lock(directory):
    if directory.is_symlink() or directory.parent.is_symlink():raise ValueError('unsafe_service_control_directory')
    directory.mkdir(parents=True,exist_ok=True,mode=0o700)
    lock=directory/'.control.lock';_safe_file(lock)
    with lock.open('a+b') as stream:
        if os.name=='posix':
            import fcntl
            deadline=time.monotonic()+5
            while True:
                try:fcntl.flock(stream.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB);break
                except BlockingIOError:
                    if time.monotonic()>=deadline:raise RuntimeError('service_control_busy_retry') from None
                    time.sleep(.05)
        try:yield
        finally:
            if os.name=='posix':fcntl.flock(stream.fileno(),fcntl.LOCK_UN)


def service_status(config_dir=Path('/etc/sanequeue'),unit_dir=Path('/etc/systemd/system')):
    return {name:{'disabled':module_disabled(name,config_dir),
                  'installed':all((Path(unit_dir)/unit).is_file() for unit in units),
                  'units':units,'dependencies':DEPENDENCIES.get(name,()),
                  'scope':'background_service_only'} for name,units in SERVICE_MODULES.items()}


def control_service(action,name,run,*,cascade=False,dry_run=False,
                    config_dir=Path('/etc/sanequeue'),unit_dir=Path('/etc/systemd/system'),
                    state_dir=Path('/var/lib/sanequeue')):
    """Change only allowlisted workers. Restore files and service states on failure.

    Runtime rollback cannot undo work already interrupted by stopping a worker;
    existing worker leases/recovery rules handle that separately.
    """
    if action not in ('enable','disable'):raise ValueError('invalid_service_control_action')
    if name not in SERVICE_MODULES:raise ValueError('unsupported_service_module_use_pbx_feature_settings')
    config_dir,unit_dir,state_dir=map(Path,(config_dir,unit_dir,state_dir))
    if config_dir.is_symlink() or unit_dir.is_symlink():raise ValueError('unsafe_service_control_directory')
    if action=='enable' and (state_dir/'module.disabled').exists():raise ValueError('global_module_disabled_enable_global_first')
    selected={name}
    while True:
        dependents={key for key,deps in DEPENDENCIES.items() if selected.intersection(deps)
                    and key not in selected and any((unit_dir/u).is_file() for u in SERVICE_MODULES[key])
                    and not module_disabled(key,config_dir)} if action=='disable' else set()
        if not dependents:break
        if not cascade:raise ValueError('dependent_services_require_cascade:'+','.join(sorted(dependents)))
        selected.update(dependents)
    ordered=[key for key in SERVICE_MODULES if key in selected]
    if action=='disable':ordered.reverse()
    for key in ordered:
        if not all((unit_dir/unit).is_file() for unit in SERVICE_MODULES[key]):raise ValueError('service_module_not_installed:'+key)
        if action=='enable':
            for dependency in module_dependencies(key):
                if module_disabled(dependency,config_dir) or not all((unit_dir/u).is_file() for u in SERVICE_MODULES[dependency]):raise ValueError('dependency_unavailable:'+dependency)
            for requirement in REQUIREMENTS.get(key,()):
                path=config_dir/requirement
                if path.is_symlink() or not path.is_file():raise ValueError('explicit_configuration_required:'+requirement)
    result={'action':action,'service_modules':ordered,'units':[u for key in ordered for u in SERVICE_MODULES[key]],
            'scope':'background_service_only','dry_run':bool(dry_run),'asterisk_restarted':False}
    if dry_run:return result
    with _control_lock(config_dir/'modules'):
        # Recheck under lock: another controller must not reverse a dependency.
        if action=='enable':
            if (state_dir/'module.disabled').exists():raise ValueError('global_module_disabled_enable_global_first')
            for dependency in module_dependencies(name):
                if module_disabled(dependency,config_dir):raise ValueError('dependency_unavailable:'+dependency)
        else:
            for dependent,dependencies in DEPENDENCIES.items():
                if dependent not in selected and selected.intersection(dependencies) and not module_disabled(dependent,config_dir) and any((unit_dir/u).is_file() for u in SERVICE_MODULES[dependent]):raise ValueError('dependent_service_changed_retry')
        files={};modes={};before={};all_units=result['units']
        for key in ordered:
            marker=config_dir/'modules'/(key+'.disabled');files[marker]=_safe_file(marker)
            for unit in SERVICE_MODULES[key]:
                directory=unit_dir/(unit+'.d')
                if directory.is_symlink():raise ValueError('unsafe_service_control_directory')
                path=directory/DROPIN;files[path]=_safe_file(path)
        for path,content in files.items():
            if content is not None:modes[path]=path.stat().st_mode & 0o777
        for unit in all_units:
            before[unit]={'enabled':run('systemctl','is-enabled','--quiet',unit).returncode==0,
                          'active':run('systemctl','is-active','--quiet',unit).returncode==0}
        def checked(*args):
            if run(*args).returncode:raise RuntimeError('service_control_command_failed')
        try:
            for key in ordered:
                marker=config_dir/'modules'/(key+'.disabled')
                for unit in SERVICE_MODULES[key]:
                    # Additional conditions never reset existing unit conditions.
                    _write(unit_dir/(unit+'.d')/DROPIN,('[Unit]\nConditionPathExists=!'+str(marker)+'\n').encode(),0o644)
                _write(marker,b'Disabled background service by local administrator\n' if action=='disable' else None)
            checked('systemctl','daemon-reload')
            for unit in all_units:
                if action=='disable':
                    checked('systemctl','disable',unit);checked('systemctl','stop',unit)
                    if run('systemctl','is-active','--quiet',unit).returncode==0:raise RuntimeError('service_control_worker_still_active')
                elif unit!='sanequeue-inventory.service':
                    checked('systemctl','enable',unit);checked('systemctl','start',unit)
                    if run('systemctl','is-active','--quiet',unit).returncode:raise RuntimeError('service_control_worker_not_active')
        except Exception:
            rollback_failed=False
            for path,content in files.items():
                try:_write(path,content,modes.get(path,0o644 if path.name==DROPIN else 0o600))
                except Exception:rollback_failed=True
            try:
                if run('systemctl','daemon-reload').returncode:rollback_failed=True
            except Exception:rollback_failed=True
            for unit,old in before.items():
                for operation in ('enable' if old['enabled'] else 'disable','start' if old['active'] else 'stop'):
                    try:
                        if run('systemctl',operation,unit).returncode:rollback_failed=True
                    except Exception:rollback_failed=True
            raise RuntimeError('service_control_failed_rollback_incomplete' if rollback_failed else 'service_control_failed_previous_state_restored') from None
    return result


def enabled_units(unit_dir=Path('/etc/systemd/system'),ai_marker=Path('/etc/sanequeue/reporting-ai.enabled'),survey_marker=Path('/etc/sanequeue/surveys.enabled'),generative_marker=Path('/etc/sanequeue/generative.enabled'),config_dir=Path('/etc/sanequeue')):
    """Do not require optional services from installations predating reports."""
    return allowed_start_units(tuple(unit for unit in UNITS if (unit_dir/unit).is_file() and unit not in ('sanequeue-inventory.service','sanequeue-pbx-apply.service')
        and (not unit.startswith('sanequeue-reporting') or (unit_dir/unit).is_file())
        and (unit!='sanequeue-reporting-ai.service' or ai_marker.is_file())
        and (unit!='sanequeue-surveys.service' or ((unit_dir/unit).is_file() and survey_marker.is_file() and not survey_marker.is_symlink()))
        and (unit!='sanequeue-generative.service' or ((unit_dir/unit).is_file() and generative_marker.is_file() and not generative_marker.is_symlink()))),config_dir)


def global_enable(run,flag,units):
    """A failed emergency resume remains disabled; never leave partial new starts."""
    previous=_safe_file(flag)
    before={unit:(run('systemctl','is-active','--quiet',unit).returncode==0,
                  run('systemctl','is-enabled','--quiet',unit).returncode==0) for unit in units}
    try:
        flag.unlink(missing_ok=True)
        # The PBX adapter has its own idle guard; its timer retries a busy PBX.
        run('systemctl','start','sanequeue-pbx-apply.service')
        if run('systemctl','enable','--now',*units).returncode:raise RuntimeError('module_start_failed')
    except Exception:
        _write(flag,previous or b'Disabled after failed global service resume\n')
        failed=False
        for unit,(active,enabled) in before.items():
            for operation,needed in (('stop',not active),('disable',not enabled)):
                if needed:
                    try:
                        if run('systemctl',operation,unit).returncode:failed=True
                    except Exception:failed=True
        raise RuntimeError('global_enable_failed_disabled_rollback_incomplete' if failed else 'global_enable_failed_disabled_state_preserved') from None

def without_managed_access(text):
    return re.sub(r'(?m)^; BEGIN SANEQUEUE MANAGED ACCESS\n.*?^; END SANEQUEUE MANAGED ACCESS\n?','',text,flags=re.S)

def remove_managed_ami(manager, backup, reload_manager):
    """Restore the exact original configuration if applying removal fails."""
    if manager.is_symlink():raise ValueError('manager_symlink_refused')
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
    parser.add_argument('--module',help='Control one background service group: '+', '.join(SERVICE_MODULES))
    parser.add_argument('--cascade',action='store_true',help='Also disable dependent service groups')
    parser.add_argument('--dry-run',action='store_true',help='Show a per-service plan without changes')
    args=parser.parse_args()
    if os.geteuid()!=0:parser.error('Run with sudo/root')
    def run(*command):return subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=30)
    if args.module:
        if args.action=='status':
            if args.module not in SERVICE_MODULES:parser.error('Unsupported service module; callback/caller-ID use PBX feature settings')
            print(json.dumps(service_status()[args.module]));return
        if args.action not in ('enable','disable'):parser.error('Per-service uninstall is unsupported; use disable --module NAME')
        print(json.dumps(control_service(args.action,args.module,run,cascade=args.cascade,dry_run=args.dry_run)));return
    if args.cascade or args.dry_run:parser.error('--cascade/--dry-run require --module')
    flag=Path('/var/lib/sanequeue/module.disabled')
    if args.action=='status':
        print(json.dumps({'enabled':not flag.exists(),'services':{unit:run('systemctl','is-active','--quiet',unit).returncode==0 for unit in UNITS},'service_modules':service_status()}));return
    with _control_lock(Path('/etc/sanequeue/modules')):
        return _global_action(args,run,parser,flag)


def _global_action(args,run,parser,flag):
    if args.action=='enable':
        global_enable(run,flag,enabled_units())
        print('SaneQueue enabled. Per-service disabled workers remain disabled; Asterisk was not restarted.');return
    if args.action=='uninstall' and not args.yes:parser.error('Use uninstall --yes; configuration and private state will be retained')
    flag.parent.mkdir(parents=True,exist_ok=True)
    descriptor,temporary=tempfile.mkstemp(prefix='.disabled-',dir=flag.parent)
    try:
        with os.fdopen(descriptor,'w') as stream:stream.write('Disabled by local administrator\n');stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,flag)
    finally:
        if os.path.exists(temporary):os.unlink(temporary)
    spool=Path('/var/spool/asterisk/sanequeue')
    if spool.is_dir():
        from sanequeue.pbx.root_adapter import atomic
        import pwd
        atomic(spool/'disabled',b'disabled\n',0,pwd.getpwnam('asterisk').pw_gid)
    failures=[]
    for unit in UNITS:
        run('systemctl','disable',unit)
        run('systemctl','stop',unit)
        if run('systemctl','is-active','--quiet',unit).returncode==0:failures.append(unit)
    if failures:raise RuntimeError('module_services_still_active:'+','.join(failures))
    if args.action=='uninstall':
        from sanequeue.pbx.root_adapter import restore
        restore()
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
