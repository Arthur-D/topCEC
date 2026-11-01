"""Hardware-free tests for Firefox WebExtension and native messaging."""
# SPDX-License-Identifier: GPL-3.0-or-later
import io
import json
import os
import runpy
import subprocess
import struct
import sys
import unittest
from pathlib import Path
import tempfile
import zipfile
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'cec-tv'))

from firefox_media import FirefoxWebExtensionProvider
from monitor import Mapping
from native_messaging import MAX_MESSAGE_SIZE, read_message, write_message


class FirefoxMediaChecks(unittest.TestCase):
    def setUp(self):
        self.mapping = Mapping(15)
        self.mapping.snapshot(json.dumps([
            {'title': 'TV video — Mozilla Firefox', 'output': 'HDMI-A-2'},
            {'title': 'Office — Mozilla Firefox', 'output': 'DP-1'},
        ]), 10)
        self.provider = FirefoxWebExtensionProvider()

    def snapshot(self, windows):
        return json.dumps({'version': 1, 'windows': windows})

    def test_extension_permissions_are_limited_to_tabs_and_native_messaging(self):
        manifest = json.loads(
            (ROOT / 'firefox-extension/manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(manifest['permissions'], ['tabs', 'nativeMessaging'])
        self.assertNotIn('host_permissions', manifest)

    def test_audible_unmuted_tab_uses_its_correlated_window_display(self):
        self.assertTrue(self.provider.update(self.snapshot([{
            'window_id': 3,
            'active_title': 'TV video',
            'tabs': [{'audible': True, 'muted': False}],
        }]), 11))
        self.assertEqual(self.provider.audio_state(
            self.mapping, 12, 'HDMI-A-2', 15), (True, False))

    def test_background_audio_uses_window_active_title_not_focused_window(self):
        self.provider.update(self.snapshot([{
            'window_id': 4,
            'active_title': 'Office',
            'tabs': [
                {'audible': True, 'muted': False},
                {'audible': False, 'muted': False},
            ],
        }]), 11)
        self.assertEqual(self.provider.audio_state(
            self.mapping, 12, 'HDMI-A-2', 15), (False, False))

    def test_muted_or_silent_tabs_do_not_count_as_playback(self):
        self.provider.update(self.snapshot([{
            'window_id': 3,
            'active_title': 'missing title',
            'tabs': [
                {'audible': True, 'muted': True},
                {'audible': False, 'muted': False},
            ],
        }]), 11)
        self.assertEqual(self.provider.audio_state(
            self.mapping, 12, 'HDMI-A-2', 15), (False, False))

    def test_unmatched_or_duplicate_active_window_titles_are_uncertain(self):
        self.provider.update(self.snapshot([{
            'window_id': 9,
            'active_title': 'Unknown',
            'tabs': [{'audible': True, 'muted': False}],
        }]), 11)
        self.assertEqual(self.provider.audio_state(
            self.mapping, 12, 'HDMI-A-2', 15), (False, True))

        self.mapping.snapshot(json.dumps([
            {'title': 'TV video — Mozilla Firefox', 'output': 'HDMI-A-2'},
            {'title': 'TV video - Firefox', 'output': 'DP-1'},
        ]), 12)
        self.provider.update(self.snapshot([{
            'window_id': 9,
            'active_title': 'TV video',
            'tabs': [{'audible': True, 'muted': False}],
        }]), 13)
        self.assertEqual(self.provider.audio_state(
            self.mapping, 13, 'HDMI-A-2', 15), (False, True))

    def test_expired_native_snapshot_falls_back_and_stale_kwin_is_unknown(self):
        self.provider.update(self.snapshot([]), 10)
        self.assertIsNone(self.provider.audio_state(
            self.mapping, 26, 'HDMI-A-2', 15))
        self.assertIsNone(self.mapping.browser_window_output('TV video', 26))

    def test_invalid_snapshot_clears_previous_state(self):
        self.provider.update(self.snapshot([]), 10)
        self.assertFalse(self.provider.update(
            '{"version": 1, "windows": [{"window_id": true}]}', 11))
        self.assertEqual(self.provider.audio_state(
            self.mapping, 11, 'HDMI-A-2', 15), None)

    def test_native_messaging_frame_round_trip_and_eof(self):
        message = {'version': 1, 'windows': []}
        stream = io.BytesIO()
        write_message(stream, message)
        stream.seek(0)
        self.assertEqual(read_message(stream), message)
        self.assertIsNone(read_message(stream))

    def test_native_host_forwards_snapshot_to_session_service(self):
        snapshot = {
            'version': 1,
            'windows': [{
                'window_id': 3,
                'active_title': 'TV video',
                'tabs': [{'audible': True, 'muted': False}],
            }],
        }
        source = io.BytesIO()
        write_message(source, snapshot)
        source.seek(0)
        output = io.BytesIO()
        reported = []
        service = SimpleNamespace(Report=reported.append)
        fake_dbus = SimpleNamespace(
            SessionBus=lambda: SimpleNamespace(
                get_object=lambda name, path: service),
            Interface=lambda obj, name: obj,
            DBusException=RuntimeError)
        with patch.dict(sys.modules, {'dbus': fake_dbus}), \
                patch.object(sys, 'stdin', SimpleNamespace(buffer=source)), \
                patch.object(sys, 'stdout', SimpleNamespace(buffer=output)):
            host = runpy.run_path(
                str(ROOT / 'cec-tv/firefox-native-host.py'),
                run_name='topcec_firefox_native_host_test')
            self.assertEqual(host['main'](), 0)
        self.assertEqual(len(reported), 1)
        self.assertTrue(reported[0].startswith('Firefox-media-snapshot: '))
        forwarded = json.loads(reported[0].split(': ', 1)[1])
        self.assertEqual(forwarded, snapshot)
        output.seek(0)
        self.assertEqual(read_message(output), {'accepted': True})

    def test_native_messaging_rejects_bad_lengths_and_truncated_frames(self):
        with self.assertRaisesRegex(ValueError, 'message length'):
            read_message(io.BytesIO(struct.pack('<I', MAX_MESSAGE_SIZE + 1)))
        with self.assertRaisesRegex(EOFError, 'Truncated'):
            read_message(io.BytesIO(struct.pack('<I', 5) + b'{}'))

    def test_extension_builder_creates_signing_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            archive_path = Path(directory) / 'nested/extension.zip'
            subprocess.run(
                ['bash', str(ROOT / 'packaging/build-firefox-extension.sh')],
                check=True,
                env={**os.environ,
                     'TOPCEC_FIREFOX_EXTENSION_OUTPUT': str(archive_path)},
                capture_output=True, text=True)
            with zipfile.ZipFile(archive_path) as archive:
                self.assertEqual(
                    set(archive.namelist()), {'manifest.json', 'background.js'})
                manifest = json.loads(archive.read('manifest.json'))
                self.assertEqual(
                    manifest['browser_specific_settings']['gecko']['id'],
                    'topcec-media@topcec.local')

    def test_native_host_install_and_uninstall_preserve_unrelated_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / 'home'
            app = home / '.local/share/topcec'
            manifest_dir = root / 'native-hosts'
            environment = {
                **os.environ,
                'HOME': str(home),
                'TOPCEC_HOME': str(home),
                'TOPCEC_APP_DIR': str(app),
                'TOPCEC_FIREFOX_NATIVE_DIR': str(manifest_dir),
                'TOPCEC_SKIP_SYSTEMCTL': '1',
            }
            subprocess.run(
                ['bash', str(ROOT / 'packaging/install-user.sh')],
                check=True, env=environment, capture_output=True, text=True)
            manifest = json.loads((manifest_dir / 'net.local.topcec.media.json')
                                  .read_text(encoding='utf-8'))
            self.assertEqual(
                manifest['path'], str(app / 'cec-tv/firefox-native-host.py'))
            self.assertEqual(
                manifest['allowed_extensions'], ['topcec-media@topcec.local'])
            self.assertTrue(os.access(manifest['path'], os.X_OK))
            self.assertTrue((app / 'firefox-extension/background.js').is_file())
            extra = app / 'preserve-me'
            extra.write_text('custom', encoding='utf-8')
            subprocess.run(
                ['bash', str(ROOT / 'packaging/uninstall-user.sh')],
                check=True, env=environment, capture_output=True, text=True)
            self.assertFalse((manifest_dir / 'net.local.topcec.media.json').exists())
            self.assertEqual(extra.read_text(encoding='utf-8'), 'custom')


if __name__ == '__main__':
    unittest.main(verbosity=2)
