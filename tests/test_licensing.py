"""Verify project license text and SPDX coverage."""
# SPDX-License-Identifier: GPL-3.0-or-later
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
PROJECT_FILES = (
    'cec-tv/activity_policy.py',
    'cec-tv/cec-kde-settings.py',
    'cec-tv/cec-power-command.py',
    'cec-tv/cec_power_state.py',
    'cec-tv/configuration.py',
    'cec-tv/firefox_media.py',
    'cec-tv/monitor.py',
    'cec-tv/native_messaging.py',
    'cec-tv/firefox-native-host.py',
    'cec-tv/providers.py',
    'cec-tv/start.py',
    'cec-tv/topcec.qml',
    'cec-tv/topcec_gui.py',
    'cec-tv/activity.js',
    'cec-tv/firefox.js',
    'packaging/install-user.sh',
    'packaging/install-firefox-native-host.sh',
    'packaging/uninstall-user.sh',
    'packaging/build-rpm.sh',
    'packaging/build-firefox-extension.sh',
    'packaging/topcec.spec',
    'packaging/topcec.service',
    'packaging/topcec-gui',
    'packaging/topcec-gui.desktop',
    'packaging/flatpak/net.local.topcec.yml',
    'packaging/flatpak/topcec-gui',
    'firefox-extension/background.js',
    'systemd/user/topcec.service',
)


class LicenseChecks(unittest.TestCase):
    def test_standard_gplv3_or_later_license_text_is_present(self):
        license_text = (ROOT / 'LICENSE').read_text(encoding='utf-8')
        self.assertIn('GNU GENERAL PUBLIC LICENSE', license_text)
        self.assertIn('Version 3, 29 June 2007', license_text)
        self.assertIn('END OF TERMS AND CONDITIONS', license_text)

    def test_project_code_and_service_files_declare_spdx_license(self):
        for relative_path in PROJECT_FILES:
            with self.subTest(path=relative_path):
                source = (ROOT / relative_path).read_text(encoding='utf-8')
                self.assertIn('SPDX-License-Identifier: GPL-3.0-or-later', source)

    def test_legacy_snapshot_files_are_not_relabelled(self):
        for relative_path in (
            'tests/original/check_cec.py',
            'tests/original/check_fixed.py',
            'tests/original/test_cec_live.py',
            'tests/original/test_kde_settings.py',
            'legacy/bin/cec-tv-power',
        ):
            with self.subTest(path=relative_path):
                source = (ROOT / relative_path).read_text(encoding='utf-8')
                self.assertNotIn('SPDX-License-Identifier: GPL-3.0-or-later', source)

    def test_firefox_manifest_declares_project_license(self):
        manifest = (ROOT / 'firefox-extension/manifest.json').read_text(
            encoding='utf-8')
        self.assertIn('"license": "GPL-3.0-or-later"', manifest)


if __name__ == '__main__':
    unittest.main(verbosity=2)
