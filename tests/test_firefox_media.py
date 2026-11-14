"""Hardware-free tests for Firefox WebExtension and native messaging."""
# SPDX-License-Identifier: GPL-3.0-or-later
import io
import json
import os
import runpy
import shutil
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

    def test_extension_declares_frame_and_site_access_for_video(self):
        manifest = json.loads(
            (ROOT / 'firefox-extension/manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(manifest['permissions'],
                         ['tabs', 'nativeMessaging', 'webNavigation', '<all_urls>'])
        self.assertTrue(manifest['content_scripts'][0]['all_frames'])

    @unittest.skipUnless(shutil.which('node'), 'Node.js is required for JavaScript tests')
    def test_video_state_prioritizes_playing_over_inaccessible_frames(self):
        script = r'''
const fs = require("fs");
const vm = require("vm");
const assert = require("assert");
let states = [];
const listener = {addListener() {}};
const browser = {
    webNavigation: {getAllFrames: async () => states.map((_, frameId) => ({frameId}))},
    tabs: {
        sendMessage: async (_tabId, _message, {frameId}) => {
            if (states[frameId] === null) throw new Error("inaccessible");
            return {playing: states[frameId]};
        },
        onUpdated: listener, onActivated: listener, onCreated: listener,
        onRemoved: listener, onAttached: listener, onDetached: listener,
    },
    windows: {getAll: async () => [], onCreated: listener, onRemoved: listener},
    runtime: {
        connectNative: () => ({onDisconnect: listener, onMessage: listener,
                               postMessage() {}}),
        onStartup: listener, onInstalled: listener,
    },
};
const context = vm.createContext({browser, setTimeout, clearTimeout,
                                  setInterval() {}, console});
vm.runInContext(fs.readFileSync(process.argv[1], "utf8"), context);
(async () => {
    for (const [input, expected] of [
        [[true, null], true], [[false, null], null], [[false, false], false],
        [[true, false], true], [[], null],
    ]) {
        states = input;
        assert.strictEqual(await context.videoState(1), expected);
    }
})().catch(error => { console.error(error); process.exitCode = 1; });
'''
        subprocess.run(['node', '-e', script, str(ROOT / 'firefox-extension/background.js')],
                       check=True, capture_output=True, text=True)

    def test_video_only_uses_all_tabs_and_blocks_unknown_on_target_display(self):
        self.mapping.snapshot(json.dumps([
            {'title': 'TV video — Mozilla Firefox', 'output': 'HDMI-A-2'},
        ]), 10)
        windows = [{
            'window_id': 3, 'active_title': 'TV video',
            'tabs': [{'audible': True, 'muted': False, 'video': False},
                     {'audible': False, 'muted': True, 'video': True}],
        }]
        self.assertTrue(self.provider.update(self.snapshot(windows), 11))
        self.assertEqual(self.provider.video_state(self.mapping, 12, 'HDMI-A-2', 15),
                         (True, False))
        self.assertEqual(self.provider.video_state(self.mapping, 12, 'DP-1', 15),
                         (False, False))
        windows[0]['tabs'][1]['video'] = None
        self.assertTrue(self.provider.update(self.snapshot(windows), 11))
        self.assertEqual(self.provider.video_state(self.mapping, 12, 'HDMI-A-2', 15),
                         (False, True))
        windows[0]['tabs'][1]['video'] = False
        self.assertTrue(self.provider.update(self.snapshot(windows), 11))
        self.assertEqual(self.provider.video_state(self.mapping, 12, 'HDMI-A-2', 15),
                         (False, False))
        del windows[0]['tabs'][1]['video']
        self.assertTrue(self.provider.update(self.snapshot(windows), 11))
        self.assertEqual(self.provider.video_state(self.mapping, 12, 'HDMI-A-2', 15),
                         (False, True))

    def test_video_requires_complete_window_mapping_and_only_relevant_extension(self):
        self.assertEqual(self.provider.video_state(self.mapping, 12, 'unrelated', 15),
                         (False, False))
        self.assertIsNone(self.provider.video_state(self.mapping, 12, 'HDMI-A-2', 15))
        self.provider.update(self.snapshot([{
            'window_id': 3, 'active_title': 'TV video',
            'tabs': [{'audible': False, 'muted': False, 'video': False}],
        }]), 11)
        self.assertEqual(self.provider.video_state(self.mapping, 12, 'HDMI-A-2', 15),
                         (False, True))

    def test_audible_unmuted_tab_uses_its_correlated_window_display(self):
        self.assertTrue(self.provider.update(self.snapshot([{
            'window_id': 3,
            'active_title': 'TV video',
            'tabs': [{'audible': True, 'muted': False, 'video': True}],
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
                'tabs': [{'audible': True, 'muted': False, 'video': True}],
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
                    set(archive.namelist()), {'manifest.json', 'background.js', 'video.js'})
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
                'XDG_DATA_HOME': str(root / 'data'),
                'XDG_CONFIG_HOME': str(root / 'config'),
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
            with zipfile.ZipFile(app / 'topcec-firefox-media.zip') as archive:
                self.assertEqual(set(archive.namelist()), {'manifest.json', 'background.js', 'video.js'})
            extra = app / 'preserve-me'
            extra.write_text('custom', encoding='utf-8')
            subprocess.run(
                ['bash', str(ROOT / 'packaging/uninstall-user.sh')],
                check=True, env=environment, capture_output=True, text=True)
            self.assertFalse((manifest_dir / 'net.local.topcec.media.json').exists())
            self.assertFalse((app / 'topcec-firefox-media.zip').exists())
            self.assertEqual(extra.read_text(encoding='utf-8'), 'custom')


if __name__ == '__main__':
    unittest.main(verbosity=2)
