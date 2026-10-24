import shutil
import tempfile
import unittest
from qpanel.upgrader import (__first_line as firstline,
    get_current_version, check_require_upgrade, get_stable_version)
import qpanel


class UpgradeTestClass(unittest.TestCase):

    def setUp(self):
        # Create a temporary directory
        self.test_dir = tempfile.mkdtemp()

    def tearDown(self):
        # Remove the directory after the test
        shutil.rmtree(self.test_dir)

    def test_first_line(self):
        content = 'a\n\b\t\b'
        self.assertEqual(firstline(content), 'a')
        self.assertNotEqual(firstline(content), 'ab')

    def test_version(self):
        self.assertEqual(get_current_version(), qpanel.__version__)
        self.assertNotEqual(get_current_version(), '0.11.0')

    def test_check_require_upgrade(self):
        stable = '0.10'
        current = '0.9'
        dev = '1.11.0'

        self.assertEqual(check_require_upgrade(dev, stable), False)
        self.assertEqual(check_require_upgrade(current, stable), True)


    def test_request_estable_version(self):
        from unittest.mock import patch
        with patch('qpanel.upgrader.requests.get') as get:
            get.return_value.text='2.1.0\n'
            self.assertEqual(get_stable_version(),'2.1.0')
            get.assert_called_once_with('https://raw.githubusercontent.com/SaneHajiha/sanequeue/master/VERSION',timeout=(3,5))

    def test_update_check_handles_network_failure(self):
        from unittest.mock import patch
        import requests
        with patch('qpanel.upgrader.requests.get',side_effect=requests.Timeout):
            self.assertIsNone(get_stable_version())

    def test_update_check_rejects_html_and_beta_channel(self):
        from unittest.mock import patch
        for text in ['<html>error</html>','2.1.0-beta.18']:
            with self.subTest(text=text), patch('qpanel.upgrader.requests.get') as get:
                get.return_value.text=text
                self.assertIsNone(get_stable_version())

# runs the unit tests
if __name__ == '__main__':
    unittest.main()
