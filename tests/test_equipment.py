# SPDX-License-Identifier: GPL-3.0-or-later
"""Hardware-free host inventory tests."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'cec-tv'))
import equipment


class EquipmentChecks(unittest.TestCase):
    def test_installed_apps_include_hidden_entries_and_deduplicate_ids(self):
        def entry(identity, name):
            return SimpleNamespace(get_id=lambda: identity, get_display_name=lambda: name)
        gio = SimpleNamespace(AppInfo=SimpleNamespace(get_all=lambda: [
            entry('one.desktop', 'One'), entry('one.desktop', 'Duplicate'),
            entry('hidden.desktop', 'Hidden'), entry(None, 'No ID')]))
        with patch.dict(sys.modules, {'gi.repository': SimpleNamespace(Gio=gio)}):
            self.assertEqual(equipment.discover_apps(), [
                {'id': 'hidden.desktop', 'name': 'Hidden'},
                {'id': 'one.desktop', 'name': 'One'}])

    def test_discovered_apps_expose_startup_window_class(self):
        app = SimpleNamespace(get_id=lambda: 'player.desktop',
                             get_display_name=lambda: 'Player',
                             get_startup_wm_class=lambda: 'PlayerWindow')
        gio = SimpleNamespace(AppInfo=SimpleNamespace(get_all=lambda: [app]))
        with patch.dict(sys.modules, {'gi.repository': SimpleNamespace(Gio=gio)}):
            self.assertEqual(equipment.discover_apps(), [
                {'id': 'player.desktop', 'name': 'Player', 'window_class': 'PlayerWindow'}])

    def test_discovered_steam_ids_come_from_launchers_or_desktop_ids(self):
        def entry(identity, command):
            return SimpleNamespace(get_id=lambda: identity, get_display_name=lambda: identity,
                                   get_commandline=lambda: command)
        gio = SimpleNamespace(AppInfo=SimpleNamespace(get_all=lambda: [
            entry('game.desktop', 'steam "steam://rungameid/553850"'),
            entry('steam_app_123.desktop', 'steam'),
            entry('other.desktop', 'steam steam://rungameid/553850extra')]))
        with patch.dict(sys.modules, {'gi.repository': SimpleNamespace(Gio=gio)}):
            self.assertEqual(equipment.discover_apps(), [
                {'id': 'game.desktop', 'name': 'game.desktop', 'steam_id': '553850'},
                {'id': 'other.desktop', 'name': 'other.desktop'},
                {'id': 'steam_app_123.desktop', 'name': 'steam_app_123.desktop',
                 'steam_id': '123'}])

    def test_inventory_uses_stable_paths_names_and_connected_displays(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('dev/input/by-id', 'dev/input/by-path', 'dev/serial/by-id',
                         'sys/class/input/event7/device'):
                (root / name).mkdir(parents=True)
            (root / 'dev/input/event7').touch()
            stable = root / 'dev/input/by-id/usb-keyboard-event-kbd'
            stable.symlink_to('../event7')
            (root / 'dev/input/by-path/platform-event-kbd').symlink_to('../event7')
            (root / 'sys/class/input/event7/device/name').write_text('Test keyboard')
            (root / 'sys/class/input/event7/device/capabilities').mkdir()
            (root / 'sys/class/input/event7/device/capabilities/abs').write_text('0')
            adapter = root / 'dev/serial/by-id/usb-Pulse-Eight_CEC_Adapter'
            adapter.touch()
            (root / 'dev/serial/by-id/usb-unrelated-serial').touch()
            (root / 'dev/serial/by-id/usb-stale-CEC').symlink_to('/nonexistent/cec')
            output = (
                '\x1b[32mOutput: 1 DP-2\x1b[0m\n enabled\n connected\n'
                'Output: 2 HDMI-A-1\n disabled\n connected\n'
                'Output: 3 DP-3\n disabled\n disconnected\n')
            with patch.object(equipment, 'Path', side_effect=lambda path: root / str(path).lstrip('/')), \
                    patch.object(equipment.subprocess, 'run', return_value=SimpleNamespace(
                        returncode=0, stdout=output, stderr='')) as command:
                inventory = equipment.discover_equipment()
                adapter.unlink()
                (root / 'dev/input/event7').unlink()
                unplugged = equipment.discover_equipment()
                self.assertEqual(unplugged['adapters'], [])
                self.assertEqual(unplugged['inputs'], [])
                adapter.touch()
                (root / 'dev/input/event7').touch()
                self.assertEqual(equipment.discover_equipment(), inventory)
            self.assertEqual(inventory['outputs'], [
                {'path': 'DP-2', 'label': 'DP-2'},
                {'path': 'HDMI-A-1', 'label': 'HDMI-A-1 (disabled)'}])
            self.assertEqual(inventory['adapters'], [
                {'path': str(adapter), 'label': adapter.name}])
            self.assertEqual(inventory['inputs'], [{
                'path': str(stable), 'label': f'Test keyboard - {stable}',
                'aliases': [str(root / 'dev/input/by-path/platform-event-kbd'),
                            str(root / 'dev/input/event7')],
                'axes': [],
            }])
            self.assertEqual(inventory['errors'], [])
            self.assertEqual(command.call_count, 3)
            command.assert_called_with(
                ['kscreen-doctor', '-o'], capture_output=True, text=True, timeout=5)

    def test_no_equipment_or_failed_discovery_never_invents_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for error in (FileNotFoundError('kscreen-doctor'),
                          subprocess.TimeoutExpired('kscreen-doctor', 5)):
                with self.subTest(error=error), \
                        patch.object(equipment, 'Path', side_effect=lambda path: root / str(path).lstrip('/')), \
                        patch.object(equipment.subprocess, 'run', side_effect=error):
                    inventory = equipment.discover_equipment()
                for key in ('outputs', 'adapters', 'inputs'):
                    self.assertEqual(inventory[key], [])
                self.assertIn('Display discovery:', inventory['errors'][0])
                self.assertNotIn('event10', json.dumps(inventory))
                self.assertNotIn('HDMI-A-2', json.dumps(inventory))

    def test_input_without_stable_alias_is_listed_even_without_readable_name(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'dev/input').mkdir(parents=True)
            event = root / 'dev/input/event8'
            event.touch()
            with patch.object(equipment, 'Path', side_effect=lambda path: root / str(path).lstrip('/')), \
                    patch.object(equipment.subprocess, 'run', return_value=SimpleNamespace(
                        returncode=0, stdout='', stderr='')):
                inventory = equipment.discover_equipment()
            self.assertEqual(inventory['inputs'][0]['path'], str(event))
            self.assertIn('event8', inventory['inputs'][0]['label'])
            self.assertTrue(inventory['errors'])

    def test_axes_are_read_from_sysfs_without_opening_input_devices(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            device = root / 'sys/class/input/event3/device'
            (device / 'capabilities').mkdir(parents=True)
            (device / 'capabilities/abs').write_text('21')
            with patch.object(equipment, 'Path', side_effect=lambda path: root / str(path).lstrip('/')):
                axes = equipment._input_axes(Path('/dev/input/event3'))
            self.assertEqual(axes, [{'code': 0, 'name': 'ABS_X'},
                                    {'code': 5, 'name': 'ABS_RZ'}])

    def test_denied_metadata_enumeration_is_reported_not_called_empty_detection(self):
        def denied(directory):
            raise PermissionError(13, 'Permission denied', directory)

        with patch.object(equipment, '_entries', side_effect=denied), \
                patch.object(equipment.subprocess, 'run', return_value=SimpleNamespace(
                    returncode=1, stdout='', stderr='Compositor unavailable')):
            inventory = equipment.discover_equipment()
        self.assertEqual(len(inventory['errors']), 3)
        self.assertIn('Compositor unavailable', inventory['errors'][0])
        self.assertIn('CEC adapter discovery', inventory['errors'][1])
        self.assertIn('Input device discovery', inventory['errors'][2])
        self.assertEqual(inventory['inputs'], [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
