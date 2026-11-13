# SPDX-License-Identifier: GPL-3.0-or-later
"""Hardware-free tests for Chromium-family browser media monitoring."""
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'cec-tv'))
from chromium_media import BROWSERS, ChromiumMedia
from configuration import SCHEMA_VERSION, validate_config


class ChromiumMediaChecks(unittest.TestCase):
    def setUp(self):
        self.media = ChromiumMedia(read_exe=lambda _: '/usr/bin/unrelated')

    def desktop(self, rows, now=10):
        self.assertTrue(self.media.update_windows(json.dumps(rows), now))

    def window(self, desktop, title, output):
        return {'pid': 42, 'desktop': desktop, 'class': desktop,
                'title': title, 'output': output}

    def report(self, browser, instance, title, audible, muted=False, now=10):
        self.media.update(json.dumps({
            'browser': browser, 'instance': instance * 32, 'version': 1,
            'windows': [{'window_id': 1, 'active_title': title,
                         'tabs': [{'audible': audible, 'muted': muted}]}],
        }), now)

    def test_all_supported_browsers_match_audio_to_display(self):
        for browser, (name, aliases) in BROWSERS.items():
            with self.subTest(browser=browser):
                self.media = ChromiumMedia(read_exe=lambda _: '/usr/bin/unrelated')
                self.desktop([self.window(next(iter(aliases)), 'Video - ' + name, 'TV')])
                self.report(browser, 'a', 'Video', True)
                self.assertEqual(self.media.state(browser, ['TV'], 11, 15), (True, None))
                self.assertEqual(self.media.state(browser, ['other'], 11, 15), (False, None))
                self.report(browser, 'a', 'Video', True, muted=True, now=11)
                self.assertEqual(self.media.state(browser, ['TV'], 11, 15), (False, None))

    def test_missing_stale_and_ambiguous_data_block(self):
        self.desktop([self.window('chromium', 'Video - Chromium', 'TV')])
        self.assertIn('unavailable', self.media.state('chromium', ['TV'], 10, 15)[1])
        self.report('chromium', 'a', 'Video', True)
        self.report('chromium', 'b', 'Video', False)
        self.assertIn('uniquely', self.media.state('chromium', ['TV'], 11, 15)[1])
        self.desktop([self.window('chromium', 'Video - Chromium', 'TV')], now=30)
        self.assertIn('stale', self.media.state('chromium', ['TV'], 30, 15)[1])

    def test_browser_only_on_another_display_needs_no_extension(self):
        self.desktop([self.window('chromium', 'Video - Chromium', 'other')])
        self.assertEqual(self.media.state('chromium', ['TV'], 11, 15), (False, None))
        self.desktop([self.window('chromium', 'Video - Chromium', 'unknown')])
        self.assertIn('unavailable', self.media.state('chromium', ['TV'], 11, 15)[1])

    def test_invalid_new_snapshot_does_not_reuse_previous_silent_state(self):
        self.desktop([self.window('chromium', 'Video - Chromium', 'TV')])
        self.report('chromium', 'a', 'Video', False)
        invalid = {'browser': 'chromium', 'instance': 'a' * 32, 'version': 1,
                   'windows': [{'window_id': 1, 'active_title': 'Video',
                                'tabs': [{'audible': None, 'muted': False}]}]}
        with self.assertRaises(ValueError):
            self.media.update(json.dumps(invalid), 11)
        self.assertIn('invalid', self.media.state('chromium', ['TV'], 11, 15)[1])

    def test_browser_web_app_is_identified_by_executable_and_unknown_is_conservative(self):
        self.media = ChromiumMedia(read_exe=lambda _: '/opt/google/chrome/chrome')
        self.desktop([self.window('custom-web-app', 'Video - Google Chrome', 'TV')])
        self.report('chrome', 'a', 'Video', True)
        self.assertEqual(self.media.state('chrome', ['TV'], 11, 15), (True, None))
        self.media = ChromiumMedia(read_exe=lambda _: '/some/unknown/chrome')
        self.desktop([self.window('custom-web-app', 'Video', 'TV')])
        self.assertIn('identity is unknown', self.media.state('chrome', ['TV'], 11, 15)[1])

    def test_settings_validate_and_default_to_off(self):
        self.assertEqual(validate_config({'schema_version': SCHEMA_VERSION})
                         ['chromium_audio_blocks_standby'], [])
        with self.assertRaises(ValueError):
            validate_config({'schema_version': SCHEMA_VERSION,
                             'chromium_audio_blocks_standby': ['chrome', 'chrome']})

    def test_setup_registers_native_and_flatpak_hosts_without_overwriting_other_hosts(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            env = {**os.environ, 'HOME': str(home), 'XDG_CONFIG_HOME': str(home / '.config'),
                   'XDG_DATA_HOME': str(home / '.local/share')}
            script = ROOT / 'packaging/setup-chromium-extension.py'
            for mode in ([], ['--flatpak']):
                command = [sys.executable, str(script), 'chromium', *mode]
                subprocess.run(command, env=env, check=True, capture_output=True, text=True)
                subprocess.run(command + ['--extension-id', 'a' * 32], env=env,
                               check=True, capture_output=True, text=True)
                config = (home / '.var/app/org.chromium.Chromium/config'
                          if mode else home / '.config')
                manifest = config / 'chromium/NativeMessagingHosts/net.local.topcec.media.json'
                value = json.loads(manifest.read_text())
                self.assertEqual(value['allowed_origins'], ['chrome-extension://' + 'a' * 32 + '/'])
                self.assertTrue(os.access(value['path'], os.X_OK))
                value['path'] = '/unrelated'
                manifest.write_text(json.dumps(value))
                result = subprocess.run(command + ['--extension-id', 'a' * 32], env=env,
                                        capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(json.loads(manifest.read_text())['path'], '/unrelated')

    def test_native_host_delivers_to_isolated_session_bus(self):
        if not shutil.which('dbus-run-session') or not shutil.which('gdbus'):
            self.skipTest('D-Bus test tools unavailable')
        subprocess.run(['dbus-run-session', '--', sys.executable, __file__,
                        '--native-integration'], check=True, timeout=15)

    def test_browser_bus_does_not_expose_power_controls(self):
        if not shutil.which('dbus-run-session') or not shutil.which('gdbus'):
            self.skipTest('D-Bus test tools unavailable')
        subprocess.run(['dbus-run-session', '--', sys.executable, __file__,
                        '--service-isolation'], check=True, timeout=20)


def service_isolation():
    import time

    with tempfile.TemporaryDirectory() as directory:
        env = {**os.environ, 'HOME': directory, 'XDG_CONFIG_HOME': directory}
        monitor = subprocess.Popen(
            [sys.executable, str(ROOT / 'cec-tv/monitor.py'), '--no-kde-timeout'],
            env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            for _ in range(50):
                result = subprocess.run(
                    ['gdbus', 'introspect', '--session', '--dest', 'net.local.topcec.BrowserMedia',
                     '--object-path', '/net/local/topcec/BrowserMedia'],
                    capture_output=True, text=True)
                if result.returncode == 0:
                    break
                if monitor.poll() is not None:
                    raise AssertionError('Monitor exited: ' + monitor.communicate()[1])
                time.sleep(0.1)
            assert result.returncode == 0, result.stderr
            assert 'Report' in result.stdout
            denied = subprocess.run(
                ['gdbus', 'call', '--session', '--dest', 'net.local.topcec.BrowserMedia',
                 '--object-path', '/net/local/CecActivity', '--method',
                 'net.local.CecActivity.RequestPower', 'off'], capture_output=True, text=True)
            assert denied.returncode != 0, 'Browser service exposed power controls'
        finally:
            monitor.terminate()
            monitor.communicate(timeout=5)


def native_integration():
    import dbus
    import dbus.service
    from dbus.mainloop.glib import DBusGMainLoop
    from gi.repository import GLib
    import threading

    DBusGMainLoop(set_as_default=True)
    bus = dbus.SessionBus()
    name = dbus.service.BusName('net.local.topcec.BrowserMedia', bus)
    received = []

    class Service(dbus.service.Object):
        @dbus.service.method('net.local.topcec.BrowserMedia', in_signature='s', out_signature='')
        def Report(self, value):
            received.append(str(value))

    service = Service(name, '/net/local/topcec/BrowserMedia')
    loop = GLib.MainLoop()
    thread = threading.Thread(target=loop.run, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory() as directory:
            host = Path(directory) / 'chromium-native-host.py'
            shutil.copyfile(ROOT / 'cec-tv/chromium-native-host.py', host)
            host.with_name('browser-id').write_text('chromium')
            message = json.dumps({'version': 1, 'windows': [{
                'window_id': 1, 'active_title': 'A "title" with ü',
                'tabs': [{'audible': True, 'muted': False}]}]}).encode()
            result = subprocess.run([sys.executable, str(host)],
                                    input=struct.pack('<I', len(message)) + message,
                                    capture_output=True, check=True, timeout=10)
            assert json.loads(result.stdout[4:]) == {'accepted': True}
            assert len(received) == 1
            data = json.loads(received[0])
            assert data['browser'] == 'chromium'
            assert data['windows'][0]['active_title'] == 'A "title" with ü'
    finally:
        loop.quit()
        thread.join(timeout=3)
        service.remove_from_connection()


if __name__ == '__main__':
    if sys.argv[1:] == ['--native-integration']:
        native_integration()
    elif sys.argv[1:] == ['--service-isolation']:
        service_isolation()
    else:
        unittest.main(verbosity=2)
