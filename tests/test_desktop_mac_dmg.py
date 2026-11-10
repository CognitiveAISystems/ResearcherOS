"""Check DMG verification cleanup and smoke-test isolation without a Mac mount."""
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from desktop.verify_mac_dmg import verify


class MacDmgVerificationTest(unittest.TestCase):
    def test_detaches_image_if_copy_fails(self):
        def run(command, **kwargs):
            if command[0] == 'ditto':
                raise subprocess.CalledProcessError(1, command)
        with patch('desktop.verify_mac_dmg.subprocess.run', side_effect=run) as mocked:
            with self.assertRaises(subprocess.CalledProcessError):
                verify(Path('/tmp/test.dmg'))
        calls = [call.args[0] for call in mocked.call_args_list]
        self.assertEqual(calls[-1][:2], ['hdiutil', 'detach'])
        self.assertFalse(any(command[0] == 'codesign' for command in calls))

    def test_checks_native_binaries_and_isolates_app_data(self):
        for machine, arch in [('arm64', 'arm64'), ('x86_64', 'x86_64')]:
            with self.subTest(machine=machine):
                with patch('desktop.verify_mac_dmg.platform.machine', return_value=machine), \
                     patch('desktop.verify_mac_dmg.subprocess.run') as mocked:
                    verify(Path('/tmp/test.dmg'))
                calls = mocked.call_args_list
                attach = next(c.args[0] for c in calls if c.args[0][:2] == ['hdiutil', 'attach'])
                self.assertIn('-readonly', attach)
                binaries = [c.args[0] for c in calls if c.args[0][0] == 'lipo']
                self.assertEqual(len(binaries), 2)
                self.assertTrue(all(c[-2:] == ['-verify_arch', arch] for c in binaries))
                launch = calls[-1]
                self.assertEqual(launch.kwargs['timeout'], 90)
                self.assertEqual(launch.kwargs['env']['RESEARCHOS_SMOKE_TEST'], '1')
                self.assertIn('researchos-dmg-', launch.kwargs['env']['KOI_DATA_DIR'])
                self.assertTrue(launch.args[0][1].startswith('--user-data-dir='))


if __name__ == '__main__':
    unittest.main()
