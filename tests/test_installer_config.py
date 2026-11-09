import importlib.util,os,unittest
from pathlib import Path


@unittest.skipIf(os.name=='nt','Provisioner runs on Linux PBX hosts')
class InstallerConfigurationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec=importlib.util.spec_from_file_location('provision',Path(__file__).resolve().parents[1]/'scripts/provision.py')
        cls.module=importlib.util.module_from_spec(spec);spec.loader.exec_module(cls.module)

    def test_managed_ami_block_preserves_other_integrations_and_rotates_once(self):
        original='[existing_fop]\nsecret=existing-private-placeholder\nwrite=all\n'
        first=self.module.manager_block(original,'a'*64,'b'*64)
        second=self.module.manager_block(first,'c'*64,'d'*64)
        self.assertIn(original.strip(),second)
        self.assertEqual(second.count('[sanequeue_collector_auto]'),1)
        self.assertNotIn('a'*64,second)
        collector=second.split('[sanequeue_collector_auto]',1)[1].split('[sanequeue_control_auto]',1)[0]
        self.assertIn('write = reporting',collector)
        self.assertNotIn('write = system',collector)
        with self.assertRaises(ValueError):self.module.manager_block('[sanequeue_control_auto]\nsecret=unmanaged','x','y')

    def test_origins_do_not_accept_credentials_paths_or_env_injection(self):
        for value in ('https://user:password@example.com','https://example.com/path','https://example.com\nSANEQUEUE_FAKE=1','javascript:alert(1)','https://example.com?token=secret'):
            with self.subTest(value=value),self.assertRaises(ValueError):self.module.validate_origin(value)
        self.assertEqual(self.module.validate_origin('http://192.168.2.2:5000/'),'http://192.168.2.2:5000')

    def test_ambiguous_or_partial_managed_ami_markers_fail_before_replacement(self):
        begin,end=self.module.BEGIN,self.module.END
        for text in (begin, end, end+'\n'+begin, begin+'\n'+end+'\n'+begin+'\n'+end,
                     'prefix '+begin+'\n'+end,begin+'\n'+end+' trailing'):
            with self.subTest(text=text),self.assertRaisesRegex(ValueError,'ambiguous_managed_ami_block'):
                self.module.manager_block(text,'a'*64,'b'*64)

    def test_private_permissions_use_descriptor_and_refuse_links(self):
        import tempfile,stat
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'private.json';target.write_text('{}')
            alias=Path(folder)/'alias';alias.symlink_to(target)
            with patch.object(self.module.os,'chmod',side_effect=NotImplementedError('lchmod unavailable')):
                self.module.private_permissions(target,os.getuid(),os.getgid(),0o600)
                self.assertEqual(stat.S_IMODE(target.stat().st_mode),0o600)
                self.module.private_permissions(Path(folder),os.getuid(),os.getgid(),0o750)
                with self.assertRaises(OSError):self.module.private_permissions(alias,os.getuid(),os.getgid(),0o777)
            self.assertEqual(stat.S_IMODE(target.stat().st_mode),0o600)

    def test_upgrade_preserves_owner_only_export_directory_contract(self):
        import tempfile,stat
        from sanequeue.reporting.export_jobs import JobStore
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);store=JobStore(root/'jobs.sqlite3',root/'private-exports')
            store.initialize()
            self.module.prepare_state_permissions(root,os.getuid(),os.getgid())
            store.initialize()
            self.assertEqual(stat.S_IMODE((root/'private-exports').stat().st_mode),0o700)
            self.assertEqual(stat.S_IMODE((root/'jobs.sqlite3').stat().st_mode),0o600)

    def test_optional_survey_writer_is_in_install_backup_and_rollback_unit_set(self):
        self.assertIn('sanequeue-surveys.service',self.module.REPORTING_UNITS)

    def test_rollback_restores_snapshot_and_retains_post_snapshot_files(self):
        import stat
        import tempfile

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            backup, state = root/'backup', root/'state'
            backup.mkdir(mode=0o750)
            state.mkdir()
            (backup/'history.sqlite3').write_text('snapshot')
            (state/'history.sqlite3').write_text('new')
            (state/'failed-only').write_text('retained')
            self.module.restore_private_tree(backup, state)
            self.assertEqual((state/'history.sqlite3').read_text(), 'snapshot')
            self.assertFalse((state/'failed-only').exists())
            self.assertEqual(stat.S_IMODE(state.stat().st_mode), 0o750)
            preserved = next(root.glob('.state-rollback-*/failed-install'))
            self.assertEqual((preserved/'history.sqlite3').read_text(), 'new')
            self.assertEqual((preserved/'failed-only').read_text(), 'retained')

    def test_rollback_rejects_directory_symlink(self):
        import tempfile

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            backup, state = root/'backup', root/'state'
            backup.mkdir()
            state.symlink_to(backup, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, 'unsafe_rollback_directory'):
                self.module.restore_private_tree(backup, state)

    def test_state_permissions_stay_inside_open_directory(self):
        import stat
        import tempfile
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            state=root/'state'
            nested=state/'nested'
            nested.mkdir(parents=True)
            (nested/'data').touch()
            outside=root/'outside'
            outside.mkdir()
            outside_file=outside/'data'
            outside_file.touch(mode=0o644)
            outside_mode=stat.S_IMODE(outside_file.stat().st_mode)
            walk=os.fwalk

            def replace_path_after_open(*args,**kwargs):
                for entry in walk(*args,**kwargs):
                    if Path(entry[0])==nested:
                        nested.rename(state/'moved')
                        nested.symlink_to(outside,target_is_directory=True)
                    yield entry

            with patch.object(self.module.os,'fwalk',replace_path_after_open):
                self.module.prepare_state_permissions(state,os.getuid(),os.getgid())
            self.assertEqual(stat.S_IMODE(outside_file.stat().st_mode),outside_mode)
            self.assertEqual(stat.S_IMODE((state/'moved'/'data').stat().st_mode),0o600)
