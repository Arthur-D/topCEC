"""Staged tests for the user-level installer and uninstaller."""
# SPDX-License-Identifier: GPL-3.0-or-later
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class UserPackagingChecks(unittest.TestCase):
    def test_install_and_uninstall_are_scoped_and_preserve_config(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home = root / 'home'
            config_home = root / 'config'
            app_dir = home / '.local/share/topcec'
            bin_dir = home / '.local/bin'
            unit_dir = config_home / 'systemd/user'
            config_path = config_home / 'topcec/config.json'
            config_path.parent.mkdir(parents=True)
            config_path.write_text('user config\n', encoding='utf-8')
            unrelated_app = home / '.local/share/other-app'
            unrelated_app.mkdir(parents=True)
            (unrelated_app / 'keep').write_text('keep', encoding='utf-8')
            unrelated_bin = bin_dir / 'other-tool'
            unrelated_bin.parent.mkdir(parents=True)
            unrelated_bin.write_text('keep', encoding='utf-8')
            unrelated_unit = unit_dir / 'other.service'
            unrelated_unit.parent.mkdir(parents=True)
            unrelated_unit.write_text('[Unit]\n', encoding='utf-8')

            environment = {
                **os.environ,
                'HOME': str(home),
                'TOPCEC_HOME': str(home),
                'XDG_CONFIG_HOME': str(config_home),
                'TOPCEC_SKIP_SYSTEMCTL': '1',
                'TOPCEC_FIREFOX_NATIVE_DIR': str(root / 'mozilla/native-messaging-hosts'),
            }
            subprocess.run(
                ['bash', str(ROOT / 'packaging/install-user.sh')],
                check=True, env=environment, capture_output=True, text=True)

            for name in ('monitor.py', 'start.py', 'topcec_gui.py',
                         'activity.js', 'firefox.js', 'topcec.qml'):
                self.assertTrue((app_dir / 'cec-tv' / name).is_file())
            self.assertTrue(os.access(app_dir / 'cec-tv/start.py', os.X_OK))
            self.assertIn('%h/.local/share/topcec/cec-tv/start.py',
                          (unit_dir / 'topcec.service').read_text(encoding='utf-8'))
            self.assertTrue(os.access(bin_dir / 'topcec-gui', os.X_OK))
            native_manifest = root / 'mozilla/native-messaging-hosts/net.local.topcec.media.json'
            self.assertTrue(native_manifest.is_file())
            self.assertTrue((app_dir / 'firefox-extension/background.js').is_file())
            self.assertTrue((config_path).is_file())
            custom_file = app_dir / 'keep-user-file'
            custom_file.write_text('keep', encoding='utf-8')

            subprocess.run(
                ['bash', str(ROOT / 'packaging/uninstall-user.sh')],
                check=True, env=environment, capture_output=True, text=True)

            self.assertEqual(custom_file.read_text(encoding='utf-8'), 'keep')
            self.assertFalse((bin_dir / 'topcec-gui').exists())
            self.assertFalse((unit_dir / 'topcec.service').exists())
            self.assertFalse(native_manifest.exists())
            self.assertEqual(config_path.read_text(encoding='utf-8'), 'user config\n')
            self.assertEqual((unrelated_app / 'keep').read_text(encoding='utf-8'), 'keep')
            self.assertEqual(unrelated_bin.read_text(encoding='utf-8'), 'keep')
            self.assertTrue(unrelated_unit.exists())

    def test_rpm_spec_limits_payload_to_gpl_topcec_files(self):
        spec = (ROOT / 'packaging/topcec.spec').read_text(encoding='utf-8')
        builder = (ROOT / 'packaging/build-rpm.sh').read_text(encoding='utf-8')
        self.assertIn('License:        GPL-3.0-or-later', spec)
        self.assertIn('%{_userunitdir}/topcec.service', spec)
        self.assertIn('%{_topcec_appdir}/cec-tv/monitor.py', spec)
        self.assertIn('%files gui', spec)
        self.assertIn('topcec.service', builder)
        self.assertNotIn('tests/original', builder)
        self.assertNotIn('legacy/', builder)
        self.assertNotIn('pip install', spec + builder)
        self.assertNotIn('Source1:', spec)
        self.assertIn('%license LICENSE', spec)
        self.assertIn('%{_topcec_appdir}/cec-tv/firefox-native-host.py', spec)
        self.assertIn('net.local.topcec.media.json', spec)
        self.assertIn('%{_prefix}/lib/mozilla/native-messaging-hosts', spec)
        self.assertNotIn('%{_datadir}/mozilla/native-messaging-hosts', spec)
        self.assertIn('topcec-%{version}.tar.gz', spec)
        self.assertIn('topcec-$VERSION.tar.gz', builder)
        self.assertIn('_sourcedir $WORK_DIR/SOURCES', builder)
        self.assertIn('completed without producing an RPM artifact', builder)
        for third_party_material in ('legacy/', 'tests/original/', 'site-packages'):
            self.assertNotIn(third_party_material, spec + builder)

    @unittest.skipIf(shutil.which('rpmbuild'), 'rpmbuild available; build path required')
    def test_rpm_builder_reports_missing_tool_without_installing(self):
        result = subprocess.run(
            ['bash', str(ROOT / 'packaging/build-rpm.sh')],
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 127)
        self.assertIn('rpmbuild is required', result.stderr)


if __name__ == '__main__':
    unittest.main(verbosity=2)
