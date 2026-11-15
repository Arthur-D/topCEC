# SPDX-License-Identifier: GPL-3.0-or-later
"""Hardware-free Plasma inhibition and window matching tests."""
import json
import tempfile
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'cec-tv'))
from standby_apps import (InhibitionHistory, PlasmaInhibitions, decode_windows,
                          forced_inhibitions, matching_inhibitions, observed_apps)


class StandbyAppsChecks(unittest.TestCase):
    def test_flatpak_chrome_inhibitor_uses_friendly_display_name(self):
        path = '/app/extra/chrome'
        self.assertEqual(observed_apps([path], []), [{'id': path, 'name': 'Google Chrome'}])
        requests = [{'kind': 'idle', 'app': path, 'reason': 'Blink Wake Lock'}]
        blocker, = matching_inhibitions(requests, [], [], [], True, 'TV')
        self.assertEqual((blocker['app'], blocker['reason']),
                         ('Google Chrome', 'Blink Wake Lock'))
        self.assertEqual(matching_inhibitions(requests, [path], [], [], True, 'TV'), [])

    def test_history_persists_idle_requests_and_maps_installed_apps(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'history.json'
            history = InhibitionHistory(path)
            history.observe([{'kind': 'idle', 'app': 'Player'},
                             {'kind': 'sleep:idle', 'app': 'Steam'},
                             {'kind': 'sleep', 'app': 'Downloader'},
                             {'kind': 'idle', 'app': ''}])
            self.assertEqual(InhibitionHistory(path).names, {'Player', 'Steam'})
            self.assertCountEqual(observed_apps(history.names, [
                {'id': 'player.desktop', 'name': 'Player'}]),
                [{'id': 'player.desktop', 'name': 'Player'}, {'id': 'Steam', 'name': 'Steam'}])
            self.assertEqual(observed_apps({'Player'}, [
                {'id': 'player.desktop', 'name': 'Player', 'launcher_group': 'player.desktop'},
                {'id': 'player-copy.desktop', 'name': 'Player', 'launcher_group': 'player.desktop'},
            ]), [{'id': 'Player', 'name': 'Player', 'launcher_group': 'player.desktop'}])
            path.write_text('broken', encoding='utf-8')
            history = InhibitionHistory(path)
            history.observe([{'kind': 'idle', 'app': 'Other'}])
            self.assertIn('Cannot read', history.error)
            self.assertEqual(path.read_text(encoding='utf-8'), 'broken')

    def test_force_inhibition_follows_open_windows_and_selected_displays(self):
        apps = [{'id': 'player.desktop', 'name': 'Player'}]
        windows = [{'desktop': 'player', 'class': 'player', 'output': 'DP-1'}]
        match = lambda outputs, fresh=True: forced_inhibitions(
            ['player.desktop'], apps, windows, fresh, outputs)
        self.assertEqual(match(['DP-1'])[0]['reason'], 'Force inhibit (window open)')
        self.assertEqual(match(['TV']), [])
        self.assertEqual(match([]), [])
        self.assertTrue(match(['TV'], False)[0]['locationUnknown'])
        windows[0]['output'] = 'unknown'
        self.assertTrue(match(['TV'])[0]['locationUnknown'])
        self.assertEqual(forced_inhibitions(['player.desktop'], apps, [], True, ['TV']), [])
        apps[0]['window_class'] = 'PlayerWindow'
        windows[0] = {'desktop': '', 'class': 'PlayerWindow', 'output': 'TV'}
        self.assertEqual(match(['TV'])[0]['app'], 'Player')
        windows[0] = {'desktop': '', 'class': '', 'output': 'TV'}
        self.assertTrue(match(['TV'])[0]['identityUnknown'])

    def test_history_save_failure_is_reported_and_retried(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'history.json'
            history = InhibitionHistory(path)
            requests = [{'kind': 'idle', 'app': 'Player'}]
            with patch('standby_apps.os.replace', side_effect=OSError('disk full')) as replace:
                history.observe(requests, 0)
                self.assertIn('disk full', history.error)
                history.observe(requests, 1)
                self.assertEqual(replace.call_count, 1)
            history.observe(requests, 11)
            self.assertIsNone(history.error)
            self.assertEqual(InhibitionHistory(path).names, {'Player'})

    def test_steam_window_matches_selected_game_and_display(self):
        apps = [{'id': 'game.desktop', 'name': 'Game', 'steam_id': '553850',
                 'window_class': 'OtherClass'}]
        window = {'desktop': '', 'class': 'steam_app_553850', 'output': 'TV'}
        match = lambda outputs: forced_inhibitions(
            ['game.desktop'], apps, [window], True, outputs)
        self.assertEqual(match(['TV'])[0]['app'], 'Game')
        self.assertEqual(match(['other']), [])
        window['class'] = 'steam_app_553851'
        self.assertEqual(match(['TV']), [])
        window['class'] = 'OtherClass'
        self.assertEqual(match(['TV'])[0]['app'], 'Game')
        window['class'] = 'steam_app_553850'
        requests = [{'kind': 'idle', 'app': 'game.desktop', 'reason': 'Playing'}]
        self.assertEqual(matching_inhibitions(
            requests, [], apps, [window], True, ['other']), [])
        self.assertFalse(matching_inhibitions(
            requests, [], apps, [window], True, ['TV'])[0]['locationUnknown'])

    def test_selected_idle_request_is_scoped_to_display_and_preserves_reason(self):
        requests = [
            {'kind': 'sleep:idle', 'app': 'org.example.Player', 'reason': 'Playing video'},
            {'kind': 'sleep', 'app': 'org.example.Player', 'reason': 'Download'},
            {'kind': 'idle', 'app': 'other', 'reason': 'Ignored'},
        ]
        apps = [{'id': 'org.example.Player.desktop', 'name': 'Player'},
                {'id': 'other.desktop', 'name': 'Other'}]
        windows = decode_windows(json.dumps([
            {'desktop': 'org.example.Player', 'class': 'player', 'output': 'DP-1'}]))
        match = lambda exceptions, display, fresh=True: matching_inhibitions(
            requests, ['other.desktop', *exceptions], apps, windows, fresh, display)
        expected = [{'app': 'org.example.Player', 'reason': 'Playing video',
                     'locationUnknown': False, 'identityUnknown': False}]
        self.assertEqual(match([], 'DP-1'), expected)
        self.assertEqual(match([], 'HDMI-1'), [])
        self.assertEqual(match([], ['HDMI-1', 'DP-1']), expected)
        self.assertEqual(match([], []), [])
        self.assertEqual(match(['org.example.Player.desktop'], 'DP-1'), [])
        self.assertTrue(match([], 'HDMI-1', False)[0]['locationUnknown'])
        self.assertTrue(matching_inhibitions(
            requests, ['other.desktop'], apps, [], True, 'DP-1')[0]['locationUnknown'])

    def test_unidentified_request_blocks_until_its_name_is_excepted(self):
        requests = [{'kind': 'idle', 'app': 'unrecognized', 'reason': 'Playing'}]
        self.assertTrue(matching_inhibitions(
            requests, [], [], [], True, 'TV')[0]['identityUnknown'])
        self.assertEqual(matching_inhibitions(
            requests, ['Unrecognized'], [], [], True, 'TV'), [])

    def test_browser_executable_request_matches_installed_browser_window(self):
        for path, desktop, name, window_class in (
            ('/app/chromium/chrome', 'org.chromium.Chromium', 'Chromium', 'chromium'),
            ('/app/extra/chrome', 'com.google.Chrome', 'Google Chrome', 'google-chrome'),
        ):
            app_id = desktop + '.desktop'
            requests = [{'kind': 'idle', 'app': path, 'reason': 'Video'}]
            apps = [{'id': app_id, 'name': name, 'window_class': window_class}]
            windows = [{'desktop': desktop, 'class': window_class, 'output': 'other'}]
            with self.subTest(path=path):
                self.assertEqual(
                    matching_inhibitions(requests, [], apps, windows, True, 'TV'), [])
                result = matching_inhibitions(requests, [], apps, windows, True, 'other')
                self.assertEqual(len(result), 1)
                self.assertFalse(result[0]['locationUnknown'])
                self.assertFalse(result[0]['identityUnknown'])
                for exceptions in ([path], [app_id]):
                    self.assertEqual(
                        matching_inhibitions(requests, exceptions, apps, windows, True, 'other'), [])

    def test_ambiguous_names_and_unknown_window_outputs_block_safely(self):
        requests = [{'kind': 'idle', 'app': 'Player', 'reason': 'Playing'}]
        apps = [{'id': 'one.desktop', 'name': 'Player'},
                {'id': 'two.desktop', 'name': 'Player'}]
        windows = [{'desktop': 'one', 'class': '', 'output': 'other'}]
        self.assertTrue(matching_inhibitions(
            requests, ['one.desktop'], apps, windows, True, 'TV')[0]['locationUnknown'])
        apps.pop()
        windows[0]['output'] = 'unknown'
        self.assertTrue(matching_inhibitions(
            requests, [], apps, windows, True, 'TV')[0]['locationUnknown'])

    def test_bad_window_snapshot_is_rejected(self):
        with self.assertRaises(ValueError):
            decode_windows('[{"desktop": "foo", "output": "TV"}]')

    def test_async_status_errors_timeout_and_late_reply(self):
        callbacks = []
        interface = Mock()
        interface.Get.side_effect = lambda *a, **kw: callbacks.append(kw)
        dbus = SimpleNamespace(Interface=lambda *_: interface, DBusException=RuntimeError)
        clock = [0]
        monitor = PlasmaInhibitions(Mock(), dbus, clock=lambda: clock[0])
        monitor.poll(0)
        callbacks[-1]['reply_handler']([('idle', 'player', 'Playing', 'block', 1)])
        self.assertIsNone(monitor.health(0))
        self.assertEqual(monitor.requests[0]['reason'], 'Playing')
        monitor.poll(2)
        monitor.poll(11)
        callbacks[1]['reply_handler']([])
        self.assertIn('timed out', monitor.health(11))
        callbacks[-1]['error_handler']('unavailable')
        self.assertIn('unavailable', monitor.health(11))
        clock[0] = 13
        monitor.poll(13)
        callbacks[-1]['reply_handler']([])
        self.assertIsNone(monitor.health(13))


if __name__ == '__main__':
    unittest.main(verbosity=2)
