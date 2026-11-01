"""Hardware-free tests for GUI settings and manual-control safety."""
# SPDX-License-Identifier: GPL-3.0-or-later
import json
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'cec-tv'))

from cec_power_state import CecPowerStateMachine
from configuration import DEFAULT_CONFIG, validate_config
from monitor import request_manual_power
import topcec_gui
from topcec_gui import GuiBackend, config_from_settings


class GuiChecks(unittest.TestCase):
    def setUp(self):
        self.config = DEFAULT_CONFIG.copy()
        self.values = {
            'targetOutput': 'HDMI-A-2',
            'adapter': '/dev/serial/by-id/adapter',
            'timeoutMode': 'custom',
            'timeoutMinutes': 12,
            'devices': '/dev/input/event1\n/dev/input/event2',
            'muteLabels': 'Mute tab',
            'axisDeadzone': 3,
            'rzDeadzone': 6,
        }

    def test_gui_settings_produce_strict_live_service_config(self):
        config = config_from_settings(self.config, self.values)
        self.assertEqual(config['timeout_seconds'], 720)
        self.assertEqual(config['devices'], ['/dev/input/event1', '/dev/input/event2'])
        self.assertTrue(config['cec_enabled'])
        self.assertTrue(config['require_snapshot'])
        self.assertFalse(config['kde_timeout'])
        self.assertEqual(config['rz_deadzone_percent'], 6.0)

    def test_kde_and_disabled_timeout_modes(self):
        kde = config_from_settings(
            self.config, {**self.values, 'timeoutMode': 'kde'})
        self.assertTrue(kde['kde_timeout'])
        disabled = config_from_settings(
            self.config, {**self.values, 'timeoutMode': 'never'})
        self.assertIsNone(disabled['timeout_seconds'])
        self.assertFalse(disabled['kde_timeout'])

    def test_invalid_settings_are_rejected(self):
        with self.assertRaises(ValueError):
            config_from_settings(self.config, {**self.values, 'timeoutMode': 'other'})
        with self.assertRaises(ValueError):
            config_from_settings(self.config, {**self.values, 'devices': ''})

    def test_manual_on_is_allowed_during_failsafe(self):
        power = SimpleNamespace(
            state_machine=CecPowerStateMachine(), pending=None, request=Mock())
        request_manual_power(power, 'on', 'Firefox snapshot unavailable')
        power.request.assert_called_once_with('on')

    def test_manual_off_requires_safe_monitor_and_no_recovery(self):
        power = SimpleNamespace(
            state_machine=CecPowerStateMachine(), pending=None, request=Mock())
        with self.assertRaisesRegex(RuntimeError, 'Firefox snapshot'):
            request_manual_power(power, 'off', 'Firefox snapshot unavailable')
        power.request.assert_not_called()

        with self.assertRaisesRegex(RuntimeError, 'recovery'):
            power.pending = 'on'
            request_manual_power(power, 'off', None)
        power.request.assert_not_called()

    def test_manual_off_is_queued_only_when_safe(self):
        def request(action):
            power.pending = action

        power = SimpleNamespace(
            state_machine=CecPowerStateMachine(), pending=None, request=request)
        request_manual_power(power, 'off', None)
        self.assertEqual(power.pending, 'off')

    def test_manual_off_cannot_follow_an_inflight_wake_or_duplicate_standby(self):
        state = CecPowerStateMachine()
        power = SimpleNamespace(
            state_machine=state, pending=None, process=object(), sent='on',
            request=Mock())
        with self.assertRaisesRegex(RuntimeError, 'recovery'):
            request_manual_power(power, 'off', None)
        power.sent = 'off'
        with self.assertRaisesRegex(RuntimeError, 'already in progress'):
            request_manual_power(power, 'off', None)
        power.request.assert_not_called()

    def test_simulation_mode_previews_without_calling_service(self):
        backend = GuiBackend(dbus_only=True)
        backend._service_data = {'cec_enabled': True}
        backend.setSimulationMode(True)
        with patch.object(backend, '_service_interface') as service:
            backend.requestPower('off')
        service.assert_not_called()
        self.assertIn('Simulation:', backend.actionMessage)

    def test_settings_are_applied_through_host_service(self):
        backend = GuiBackend(dbus_only=True)
        interface = Mock()
        interface.isValid.return_value = True
        interface.call.return_value = Mock()
        with patch.object(backend, '_service_interface', return_value=interface), \
                patch.object(backend, 'refresh') as refresh, \
                patch.object(backend, '_reply_error', return_value=None):
            backend.applySettings(self.values)
        name, serialized = interface.call.call_args.args
        self.assertEqual(name, 'ApplySettings')
        config = validate_config(json.loads(serialized))
        self.assertEqual(config['target_output'], 'HDMI-A-2')
        self.assertTrue(config['require_snapshot'])
        self.assertIn('restart queued', backend.actionMessage)
        refresh.assert_called_once()

    def test_native_gui_can_configure_before_service_starts(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(topcec_gui, 'available_outputs', return_value=[]), \
                patch.object(topcec_gui, 'available_adapters', return_value=[]), \
                patch.object(topcec_gui.subprocess, 'run', return_value=SimpleNamespace(
                    returncode=0, stdout='', stderr='')) as run:
            path = Path(directory) / 'config.json'
            backend = GuiBackend(path, dbus_only=False)
            self.assertTrue(backend.settingsEnabled)
            backend.applySettings(self.values)
            self.assertEqual(validate_config(json.loads(
                path.read_text(encoding='utf-8')))['target_output'], 'HDMI-A-2')
            run.assert_any_call(
                ['systemctl', '--user', 'restart', 'topcec.service'],
                capture_output=True, text=True, timeout=60)

    def test_native_gui_reports_saved_config_if_service_restart_fails(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(topcec_gui, 'available_outputs', return_value=[]), \
                patch.object(topcec_gui, 'available_adapters', return_value=[]), \
                patch.object(topcec_gui.subprocess, 'run', return_value=SimpleNamespace(
                    returncode=1, stdout='', stderr='unit not installed')):
            path = Path(directory) / 'config.json'
            backend = GuiBackend(path, dbus_only=False)
            backend.applySettings(self.values)
            self.assertTrue(path.is_file())
            self.assertIn('Settings saved, but service restart failed',
                          backend.actionMessage)

    def test_dbus_only_client_does_not_access_host_paths_or_commands(self):
        interface = Mock()
        interface.isValid.return_value = False
        with patch.dict(os.environ, {'TOPCEC_DBUS_ONLY': '1'}), \
                patch.object(topcec_gui, 'load_config',
                             side_effect=AssertionError('host config read')), \
                patch.object(topcec_gui, 'available_outputs',
                             side_effect=AssertionError('host output scan')), \
                patch.object(topcec_gui, 'available_adapters',
                             side_effect=AssertionError('host adapter scan')), \
                patch.object(topcec_gui.subprocess, 'run',
                             side_effect=AssertionError('host command')), \
                patch.object(GuiBackend, '_service_interface',
                             return_value=interface):
            with tempfile.TemporaryDirectory() as directory:
                config_path = Path(directory) / 'host-config.json'
                backend = GuiBackend(config_path)
                backend.refresh()
                backend.applySettings(self.values)
                self.assertFalse(config_path.exists())
        self.assertFalse(backend.settingsEnabled)
        self.assertIn('host service is not available', backend.actionMessage)

    def test_flatpak_manifest_only_grants_the_host_control_bus_name(self):
        manifest = (ROOT / 'packaging/flatpak/net.local.topcec.yml').read_text(
            encoding='utf-8')
        launcher = (ROOT / 'packaging/flatpak/topcec-gui').read_text(
            encoding='utf-8')
        self.assertIn('app-id: net.local.topcec', manifest)
        self.assertIn('--talk-name=net.local.CecActivity', manifest)
        self.assertIn('base: io.qt.PySide.BaseApp', manifest)
        self.assertIn('runtime-version: "6.11"', manifest)
        self.assertIn('base-version: "6.11"', manifest)
        self.assertIn("os.environ['TOPCEC_DBUS_ONLY'] = '1'", launcher)
        self.assertIn('org.kde.Platform', manifest)
        self.assertIn('cec-tv/configuration.py', manifest)
        self.assertIn('cec-tv/topcec_gui.py', manifest)
        self.assertIn('cec-tv/topcec.qml', manifest)
        for forbidden_permission in (
                '--filesystem=host', '--device=all', '--socket=session-bus',
                '--talk-name=org.freedesktop.systemd1',
                '--talk-name=org.kde.KWin'):
            self.assertNotIn(forbidden_permission, manifest)

    def test_kirigami_window_loads_offscreen(self):
        app = QGuiApplication.instance() or QGuiApplication([])
        backend = GuiBackend(dbus_only=True)
        engine = QQmlApplicationEngine()
        engine.rootContext().setContextProperty('topcec', backend)
        engine.load(QUrl.fromLocalFile(
            str(ROOT / 'cec-tv' / 'topcec.qml')))
        self.assertEqual(len(engine.rootObjects()), 1)
        self.assertIsNotNone(app)


if __name__ == '__main__':
    unittest.main(verbosity=2)
