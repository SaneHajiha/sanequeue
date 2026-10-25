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
