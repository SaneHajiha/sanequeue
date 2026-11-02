"""Service control uses synthetic units and fake systemd; never touches a PBX."""
import ast
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch,Mock
from scripts.module_control import (SERVICE_MODULES,DROPIN,control_service,
    enabled_units,allowed_start_units,module_disabled,service_status,
    collector_acceptance_required,global_enable,_global_action)


class Systemd:
    def __init__(self,units):
        self.active={unit:True for unit in units};self.enabled=dict(self.active)
        self.commands=[];self.fail=None;self.keep_active=None
    def __call__(self,*command):
        self.commands.append(command);operation=command[1];unit=command[-1];code=0
        if self.fail and self.fail(command):self.fail=None;code=1
        elif operation=='is-active':code=0 if self.active.get(unit) else 3
        elif operation=='is-enabled':code=0 if self.enabled.get(unit) else 1
        elif operation=='start':self.active[unit]=True
        elif operation=='stop':
            if unit!=self.keep_active:self.active[unit]=False
        elif operation=='enable':self.enabled[unit]=True
        elif operation=='disable':self.enabled[unit]=False
        return subprocess.CompletedProcess(command,code,b'',b'')


class ServiceModuleControlTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.etc=self.root/'etc';self.units=self.root/'units';self.state=self.root/'state'
        for path in (self.etc,self.units,self.state):path.mkdir()
        for units in SERVICE_MODULES.values():
            for unit in units:(self.units/unit).write_text('[Unit]\nDescription=Synthetic\n')
        self.systemd=Systemd([u for units in SERVICE_MODULES.values() for u in units])
    def control(self,action,name,**kwargs):
        return control_service(action,name,self.systemd,config_dir=self.etc,unit_dir=self.units,state_dir=self.state,**kwargs)
    def marker(self,name):return self.etc/'modules'/(name+'.disabled')
    def configured(self,name):
        requirements={'ai':['reporting-ai.enabled','reporting-ai.env'],
            'surveys':['surveys.enabled','survey-bindings.json'],'generative':['generative.enabled','generative.json']}
        for path in requirements[name]:(self.etc/path).write_text('explicit test configuration')

    def test_disable_monitoring_is_persistent_and_leaves_web_redis_and_pbx_alone(self):
        result=self.control('disable','monitoring')
        self.assertEqual(result['service_modules'],['monitoring']);self.assertTrue(self.marker('monitoring').is_file())
        for unit in SERVICE_MODULES['monitoring']:
            self.assertFalse(self.systemd.active[unit]);self.assertFalse(self.systemd.enabled[unit])
            condition=(self.units/(unit+'.d')/DROPIN).read_text()
            self.assertEqual(condition,'[Unit]\nConditionPathExists=!'+str(self.marker('monitoring'))+'\n')
        self.assertFalse(collector_acceptance_required(self.state,self.etc))
        self.assertFalse(any('asterisk' in argument or 'mariadb' in argument for cmd in self.systemd.commands for argument in cmd))
        touched={cmd[-1] for cmd in self.systemd.commands if cmd[1] not in ('daemon-reload',)}
        self.assertEqual(touched,set(SERVICE_MODULES['monitoring']))
        # Replacing a unit during upgrade cannot erase its separate drop-in.
        (self.units/'sanequeue-collector.service').write_text('[Unit]\nDescription=New release\n')
        self.assertTrue(module_disabled('monitoring',self.etc))
        self.assertTrue((self.units/'sanequeue-collector.service.d'/DROPIN).is_file())
        start=allowed_start_units(('sanequeue-collector.service','sanequeue.service','sanequeue-redis.service'),self.etc)
        self.assertEqual(start,('sanequeue.service','sanequeue-redis.service'))

    def test_reporting_requires_explicit_cascade_and_stops_all_dependents(self):
        with self.assertRaisesRegex(ValueError,'require_cascade'):self.control('disable','reporting')
        self.assertEqual(self.systemd.commands,[])
        result=self.control('disable','reporting',cascade=True)
        self.assertEqual(set(result['service_modules']),{'reporting','exports','plans','ai','generative'})
        self.assertEqual(result['service_modules'][-1],'reporting')
        for name in result['service_modules']:self.assertTrue(module_disabled(name,self.etc))
        self.assertFalse(module_disabled('monitoring',self.etc));self.assertFalse(module_disabled('surveys',self.etc))
        # Global enable and the installer must respect both own and parent gates.
        self.assertNotIn('sanequeue-reporting.service',enabled_units(self.units,config_dir=self.etc))
        self.assertEqual(allowed_start_units(('sanequeue-reporting-export.service','sanequeue-reporting-plans.service'),self.etc),())

    def test_enabling_requires_parent_and_global_enabled(self):
        self.control('disable','exports',cascade=True)
        with self.assertRaisesRegex(ValueError,'dependency_unavailable:exports'):self.control('enable','plans')
        self.control('enable','exports');self.control('enable','plans')
        self.assertFalse(self.marker('plans').exists())
        (self.state/'module.disabled').touch()
        with self.assertRaisesRegex(ValueError,'global_module_disabled'):self.control('enable','plans')
        self.assertFalse(collector_acceptance_required(self.state,self.etc))

    def test_opt_in_is_never_created_by_service_control(self):
        for name in ('ai','surveys','generative'):
            with self.subTest(module=name):
                with self.assertRaisesRegex(ValueError,'explicit_configuration_required'):self.control('enable',name)
                self.configured(name);self.control('enable',name)
                self.assertTrue(self.systemd.active[SERVICE_MODULES[name][0]])

    def test_missing_unit_and_shared_pbx_features_are_not_false_success(self):
        (self.units/'sanequeue-media.service').unlink()
        self.assertFalse(service_status(self.etc,self.units)['media']['installed'])
        with self.assertRaisesRegex(ValueError,'not_installed'):self.control('disable','media')
        for name in ('callback','caller-id','asterisk','../../other'):
            with self.subTest(module=name),self.assertRaisesRegex(ValueError,'unsupported_service_module'):self.control('disable',name)
        self.assertEqual(self.systemd.commands,[])

    def test_dry_run_does_not_write_files_or_call_systemd(self):
        result=self.control('disable','reporting',cascade=True,dry_run=True)
        self.assertTrue(result['dry_run']);self.assertEqual(self.systemd.commands,[])
        self.assertFalse((self.etc/'modules').exists())

    def test_stop_failure_restores_markers_dropins_and_service_states(self):
        target=self.units/'sanequeue-media.service.d'/DROPIN;target.parent.mkdir();target.write_text('[Unit]\n# prior managed content\n')
        original=target.read_bytes();before_active=dict(self.systemd.active);before_enabled=dict(self.systemd.enabled)
        self.systemd.fail=lambda cmd:cmd[1]=='stop'
        with self.assertRaisesRegex(RuntimeError,'previous_state_restored'):self.control('disable','media')
        self.assertFalse(self.marker('media').exists());self.assertEqual(target.read_bytes(),original)
        self.assertEqual(self.systemd.active,before_active);self.assertEqual(self.systemd.enabled,before_enabled)

    def test_start_failure_restores_disabled_marker_and_stopped_state(self):
        self.control('disable','media');before=self.marker('media').read_bytes();target=self.units/'sanequeue-media.service.d'/DROPIN;dropin=target.read_bytes()
        self.systemd.fail=lambda cmd:cmd[1]=='start'
        with self.assertRaisesRegex(RuntimeError,'previous_state_restored'):self.control('enable','media')
        self.assertEqual(self.marker('media').read_bytes(),before);self.assertEqual(target.read_bytes(),dropin)
        self.assertFalse(self.systemd.active['sanequeue-media.service']);self.assertFalse(self.systemd.enabled['sanequeue-media.service'])

    def test_worker_still_active_fails_and_restores_previous_intent(self):
        self.systemd.keep_active='sanequeue-media.service'
        with self.assertRaisesRegex(RuntimeError,'previous_state_restored'):self.control('disable','media')
        self.assertFalse(self.marker('media').exists())

    def test_daemon_reload_failure_restores_new_files(self):
        self.systemd.fail=lambda cmd:cmd[1]=='daemon-reload'
        with self.assertRaisesRegex(RuntimeError,'previous_state_restored'):self.control('disable','media')
        self.assertFalse(self.marker('media').exists());self.assertFalse((self.units/'sanequeue-media.service.d'/DROPIN).exists())

    def test_global_start_filters_transitive_disabled_parent(self):
        self.marker('reporting').parent.mkdir();self.marker('reporting').touch()
        self.assertEqual(allowed_start_units(('sanequeue-reporting-plans.service','sanequeue-generative.service','sanequeue.service'),self.etc),('sanequeue.service',))

    def test_failed_global_resume_restores_kill_switch_and_partial_service_states(self):
        flag=self.state/'module.disabled';flag.write_bytes(b'original administrator stop\n')
        unit='sanequeue-reporting.service';self.systemd.active[unit]=False;self.systemd.enabled[unit]=False
        def runner(*command):
            if command[1:3]==('enable','--now'):
                self.systemd.active[unit]=True;self.systemd.enabled[unit]=True
                return subprocess.CompletedProcess(command,1)
            return self.systemd(*command)
        with self.assertRaisesRegex(RuntimeError,'disabled_state_preserved'):global_enable(runner,flag,(unit,))
        self.assertEqual(flag.read_bytes(),b'original administrator stop\n');self.assertFalse(self.systemd.active[unit]);self.assertFalse(self.systemd.enabled[unit])

    def test_failed_global_resume_preserves_new_fastagi_and_disables_new_feature_dispatch(self):
        flag=self.state/'module.disabled';flag.write_bytes(b'original stop\n');spool=self.root/'resume-spool';spool.mkdir();(spool/'disabled').touch()
        worker='sanequeue-reporting.service';fastagi='sanequeue-fastagi.service'
        for unit in (worker,fastagi):self.systemd.active[unit]=False;self.systemd.enabled[unit]=False
        def runner(*command):
            if command[1:3]==('start','sanequeue-pbx-apply.service'):(spool/'disabled').unlink()
            if command[1:3]==('enable','--now'):
                for unit in (worker,fastagi):self.systemd.active[unit]=True;self.systemd.enabled[unit]=True
                return subprocess.CompletedProcess(command,1)
            return self.systemd(*command)
        adapter=SimpleNamespace(atomic=lambda path,value,*args:path.write_bytes(value))
        with patch.dict(sys.modules,{'sanequeue.pbx.root_adapter':adapter,'pwd':SimpleNamespace(getpwnam=lambda name:SimpleNamespace(pw_gid=0))}):
            with self.assertRaisesRegex(RuntimeError,'disabled_state_preserved'):global_enable(runner,flag,(worker,fastagi),spool=spool)
        self.assertEqual(flag.read_bytes(),b'original stop\n');self.assertEqual((spool/'disabled').read_bytes(),b'disabled\n')
        self.assertTrue(self.systemd.active[fastagi]);self.assertFalse(self.systemd.active[worker])
        self.assertFalse(any(cmd[1] in ('stop','disable') and cmd[-1]==fastagi for cmd in self.systemd.commands))

    def test_rollback_failure_is_not_claimed_restored(self):
        def runner(*command):
            if command[1]=='daemon-reload':return subprocess.CompletedProcess(command,1)
            return self.systemd(*command)
        with self.assertRaisesRegex(RuntimeError,'rollback_incomplete'):
            control_service('disable','media',runner,config_dir=self.etc,unit_dir=self.units,state_dir=self.state)
        self.assertFalse(self.marker('media').exists())

    def test_telephony_activation_is_separate_pending_stage_with_no_pbx_restart(self):
        # Execute this pure helper from its real AST, avoiding Linux-only pwd/grp
        # imports so its failure semantics also run in Windows development CI.
        tree=ast.parse((Path(__file__).parents[1]/'scripts/provision.py').read_text())
        helper=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='activate_telephony')
        namespace={'Path':Path};exec(compile(ast.Module(body=[helper],type_ignores=[]),'provision-helper','exec'),namespace)
        calls=[]
        def busy(args):
            calls.append(args)
            if args==['systemctl','start','sanequeue-pbx-apply.service']:raise RuntimeError('active calls')
        result=namespace['activate_telephony'](busy,self.state)
        self.assertEqual(result['state'],'pending');self.assertTrue(result['timer_started']);self.assertFalse(result['apply_command_succeeded'])
        self.assertIn(['systemctl','enable','--now','sanequeue-fastagi.service'],calls)
        self.assertFalse(any('restart' in cmd or 'asterisk' in cmd for cmd in calls))
        (self.state/'module.disabled').touch();calls.clear();result=namespace['activate_telephony'](busy,self.state)
        self.assertEqual(result['reason'],'global_module_disabled');self.assertEqual(calls,[])

    def test_provision_orders_adapter_after_core_acceptance_and_preserves_running_fastagi(self):
        tree=ast.parse((Path(__file__).parents[1]/'scripts/provision.py').read_text())
        main=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='main')
        activation=[n for n in ast.walk(main) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='activate_telephony']
        gateway=[n for n in ast.walk(main) if isinstance(n,ast.Constant) and n.value=='gateway_acceptance_failed']
        self.assertEqual(len(activation),1);self.assertGreater(activation[0].lineno,gateway[0].lineno)
        # All direct PBX activation belongs to the final isolated helper.
        for call in ast.walk(main):
            if not isinstance(call,ast.Call) or not isinstance(call.func,ast.Name) or call.func.id!='run' or not call.args or not isinstance(call.args[0],ast.List):continue
            arguments=[n.value for n in call.args[0].elts if isinstance(n,ast.Constant)]
            self.assertFalse('start' in arguments and 'sanequeue-pbx-apply.service' in arguments)
            self.assertFalse('enable' in arguments and 'sanequeue-pbx-apply.timer' in arguments)
        source=ast.get_source_segment((Path(__file__).parents[1]/'scripts/provision.py').read_text(),main)
        self.assertIn("if unit=='sanequeue-fastagi.service' and active[unit]:continue",source)

    def global_action(self,action,adapter):
        spool=self.root/'spool';spool.mkdir(exist_ok=True)
        parser=SimpleNamespace(error=lambda message:(_ for _ in ()).throw(ValueError(message)))
        with patch.dict(sys.modules,{'sanequeue.pbx.root_adapter':adapter,'pwd':SimpleNamespace(getpwnam=lambda name:SimpleNamespace(pw_gid=0))}),patch('builtins.print'):
            return _global_action(SimpleNamespace(action=action,yes=True),self.systemd,parser,self.state/'module.disabled',
                spool=spool,unit_dir=self.units,backup_root=self.root/'backups',manager=self.root/'manager.conf')

    def test_global_disable_preserves_shared_fastagi_and_sets_both_disable_flags(self):
        self.systemd.active['sanequeue-fastagi.service']=True;self.systemd.enabled['sanequeue-fastagi.service']=True
        adapter=SimpleNamespace(atomic=lambda path,value,*args:path.write_bytes(value))
        self.global_action('disable',adapter)
        self.assertTrue((self.state/'module.disabled').exists());self.assertEqual((self.root/'spool/disabled').read_bytes(),b'disabled\n')
        self.assertTrue(self.systemd.active['sanequeue-fastagi.service']);self.assertTrue(self.systemd.enabled['sanequeue-fastagi.service'])
        self.assertFalse(any(cmd[1] in ('stop','disable') and cmd[-1]=='sanequeue-fastagi.service' for cmd in self.systemd.commands))
        self.assertFalse(any('asterisk.service' in cmd or 'restart' in cmd for cmd in self.systemd.commands))

    def test_busy_uninstall_refuses_before_flags_or_service_mutations(self):
        idle=Mock(side_effect=ValueError('active_calls_defer_dialplan_change'));restore=Mock();atomic=Mock()
        before=dict(self.systemd.active)
        with self.assertRaisesRegex(ValueError,'active_calls'):
            self.global_action('uninstall',SimpleNamespace(require_idle=idle,restore=restore,atomic=atomic))
        idle.assert_called_once();restore.assert_not_called();atomic.assert_not_called()
        self.assertFalse((self.state/'module.disabled').exists());self.assertFalse((self.root/'spool/disabled').exists())
        self.assertEqual(self.systemd.commands,[]);self.assertEqual(self.systemd.active,before)

    def test_uninstall_restores_managed_dialplan_before_stopping_shared_fastagi(self):
        self.systemd.active['sanequeue-fastagi.service']=True;events=[]
        original_runner=self.systemd
        def run(*command):events.append(command);return original_runner(*command)
        def idle():events.append('idle')
        def restore():
            self.assertTrue(original_runner.active['sanequeue-fastagi.service']);events.append('restore')
        self.systemd=run
        with patch('scripts.module_control.remove_managed_ami'):
            self.global_action('uninstall',SimpleNamespace(require_idle=idle,restore=restore,atomic=lambda path,value,*args:path.write_bytes(value)))
        self.assertEqual(events[0],'idle');self.assertLess(events.index('restore'),events.index(('systemctl','stop','sanequeue-fastagi.service')))
        self.assertFalse(original_runner.active['sanequeue-fastagi.service']);self.assertFalse(any('restart' in event for event in events if isinstance(event,tuple)))

    def test_failed_uninstall_restore_leaves_shared_fastagi_running(self):
        self.systemd.active['sanequeue-fastagi.service']=True
        adapter=SimpleNamespace(require_idle=lambda:None,restore=Mock(side_effect=ValueError('external_dialplan_change_detected')),atomic=lambda path,value,*args:path.write_bytes(value))
        with self.assertRaisesRegex(ValueError,'external_dialplan_change'):
            self.global_action('uninstall',adapter)
        self.assertTrue(self.systemd.active['sanequeue-fastagi.service'])
        self.assertFalse(any(cmd[1]=='stop' and cmd[-1]=='sanequeue-fastagi.service' for cmd in self.systemd.commands))


if __name__=='__main__':unittest.main()

