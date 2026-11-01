#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Optional KDE control panel for the topCEC user service."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from PySide6.QtCore import QObject, Property, QUrl, Signal, Slot
from PySide6.QtDBus import QDBusConnection, QDBusInterface, QDBusMessage
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

from configuration import (
    DEFAULT_CONFIG, default_config_path, load_config, save_config,
    validate_config,
)

SERVICE = 'net.local.CecActivity'
OBJECT = '/net/local/CecActivity'
INTERFACE = 'net.local.CecActivity'


def available_outputs():
    try:
        result = subprocess.run(
            ['kscreen-doctor', '-o'], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return []
    if result.returncode:
        return []
    return list(dict.fromkeys(re.findall(
        r'^\s*Output:\s+\d+\s+([^\s]+)', result.stdout, re.MULTILINE)))


def available_adapters():
    directory = Path('/dev/serial/by-id')
    try:
        return sorted(str(path) for path in directory.iterdir())
    except OSError:
        return []


def config_from_settings(current, values):
    timeout_mode = values.get('timeoutMode', 'kde')
    if timeout_mode not in ('kde', 'custom', 'never'):
        raise ValueError('Unknown inactivity timeout mode')
    timeout_seconds = (
        None if timeout_mode == 'never'
        else int(values.get('timeoutMinutes', 10)) * 60)
    if timeout_mode == 'kde':
        timeout_seconds = current['timeout_seconds']
    config = {
        'schema_version': 1,
        'target_output': str(values['targetOutput']).strip(),
        'timeout_seconds': timeout_seconds,
        'mapping_ttl_seconds': current['mapping_ttl_seconds'],
        'devices': [item.strip() for item in str(values['devices']).splitlines()
                    if item.strip()],
        'mute_labels': [item.strip() for item in str(values['muteLabels']).splitlines()
                        if item.strip()],
        'cec_enabled': True,
        'cec_port': str(values['adapter']).strip(),
        'kde_timeout': timeout_mode == 'kde',
        'require_snapshot': True,
        'axis_deadzone_percent': float(values['axisDeadzone']),
        'rz_deadzone_percent': float(values['rzDeadzone']),
    }
    return validate_config(config)


class GuiBackend(QObject):
    changed = Signal()

    def __init__(self, config_path=None, dbus_only=None):
        super().__init__()
        self.dbus_only = (
            os.environ.get('TOPCEC_DBUS_ONLY') == '1'
            if dbus_only is None else bool(dbus_only))
        self.config_path = Path(config_path) if config_path else default_config_path()
        self.config = {'schema_version': 1, **DEFAULT_CONFIG}
        self._service_status = 'Checking service'
        self._power_state = 'unknown'
        self._standby_reason = 'Waiting for service status'
        self._diagnostics = 'No service diagnostics received.'
        self._action_message = ''
        self._simulation_mode = False
        self._service_data = {}
        self.outputs = available_outputs() if not self.dbus_only else []
        self.adapters = available_adapters() if not self.dbus_only else []
        if not self.dbus_only and self.config_path.exists():
            try:
                self.config = {'schema_version': 1, **load_config(self.config_path)}
            except ValueError as error:
                self._action_message = 'Configuration error: ' + str(error)
        if self.config['target_output'] not in self.outputs:
            self.outputs.insert(0, self.config['target_output'])
        if self.config['cec_port'] not in self.adapters:
            self.adapters.insert(0, self.config['cec_port'])

    @Property(str, notify=changed)
    def serviceStatus(self):
        return self._service_status

    @Property(str, notify=changed)
    def powerState(self):
        return self._power_state

    @Property(str, notify=changed)
    def standbyReason(self):
        return self._standby_reason

    @Property(str, notify=changed)
    def diagnostics(self):
        return self._diagnostics

    @Property(str, notify=changed)
    def actionMessage(self):
        return self._action_message

    @Property(bool, notify=changed)
    def simulationMode(self):
        return self._simulation_mode

    @Property(bool, notify=changed)
    def settingsEnabled(self):
        return not self.dbus_only or self._service_status in ('active', 'running')

    @Property('QVariantList', notify=changed)
    def outputOptions(self):
        return self.outputs

    @Property('QVariantList', notify=changed)
    def adapterOptions(self):
        return self.adapters

    @Slot(str, result='QVariant')
    def setting(self, key):
        return self.config.get(key)

    @Slot(result=int)
    def timeoutMinutes(self):
        return max(1, round((self.config['timeout_seconds'] or 600) / 60))

    @Slot(result=bool)
    def usesKdeTimeout(self):
        return self.config['kde_timeout']

    @Slot(result=str)
    def deviceList(self):
        return '\n'.join(self.config['devices'])

    @Slot(result=str)
    def muteLabelList(self):
        return '\n'.join(self.config['mute_labels'])

    @Slot(bool)
    def setSimulationMode(self, enabled):
        self._simulation_mode = bool(enabled)
        self._action_message = (
            'Manual actions are preview-only; the running service is unchanged.'
            if enabled else '')
        self.changed.emit()

    def _service_interface(self):
        return QDBusInterface(
            SERVICE, OBJECT, INTERFACE, QDBusConnection.sessionBus())

    @staticmethod
    def _reply_error(reply):
        if reply.type() == QDBusMessage.MessageType.ErrorMessage:
            return reply.errorMessage()
        return None

    @Slot()
    def refresh(self):
        unit_state = 'unavailable'
        if not self.dbus_only:
            try:
                result = subprocess.run(
                    ['systemctl', '--user', 'is-active', 'topcec.service'],
                    capture_output=True, text=True, timeout=3)
                unit_state = result.stdout.strip() or 'inactive'
                self._service_status = unit_state
            except (OSError, subprocess.TimeoutExpired) as error:
                unit_state = 'unknown'
                self._service_status = 'systemd status unavailable: ' + str(error)

        interface = self._service_interface()
        if not interface.isValid():
            self._service_data = {}
            self._power_state = 'unavailable'
            self._standby_reason = 'Monitor D-Bus service is not available'
            self._diagnostics = (
                self._standby_reason if self.dbus_only else
                f'Service: {unit_state}\n{self._standby_reason}')
            self.changed.emit()
            return
        reply = interface.call('GetStatus')
        error = self._reply_error(reply)
        if error:
            self._standby_reason = 'Cannot read monitor status: ' + error
            self._diagnostics = self._standby_reason
            self.changed.emit()
            return
        try:
            self._service_data = json.loads(str(reply.arguments()[0]))
        except (IndexError, TypeError, json.JSONDecodeError) as error:
            self._standby_reason = 'Invalid monitor status response: ' + str(error)
            self._diagnostics = self._standby_reason
            self.changed.emit()
            return

        try:
            config_reply = interface.call('GetConfig')
            config_error = self._reply_error(config_reply)
            if config_error:
                raise ValueError(config_error)
            self.config = validate_config(json.loads(
                str(config_reply.arguments()[0])))
            self.outputs = [self.config['target_output']]
            self.adapters = [self.config['cec_port']]
        except (IndexError, TypeError, ValueError, json.JSONDecodeError) as error:
            self._standby_reason = 'Cannot read service configuration: ' + str(error)
            self._diagnostics = self._standby_reason
            self.changed.emit()
            return

        self._service_status = self._service_data.get('service', 'running')
        self._power_state = self._service_data.get('power_state', 'unknown')
        reason = self._service_data.get('fail_safe_reason')
        self._standby_reason = (
            'Automatic standby allowed' if not reason
            else 'Automatic standby blocked: ' + str(reason))
        diagnostic_items = [
            f"Service: {self._service_status}",
            f"Scan: {self._service_data.get('scan_status') or 'healthy'}",
            f"CEC fault: {self._service_data.get('cec_fault') or 'none'}",
            f"Pending action: {self._service_data.get('pending_action') or 'none'}",
        ]
        self._diagnostics = '\n'.join(diagnostic_items)
        self.changed.emit()

    @Slot(str)
    def requestPower(self, action):
        if action not in ('on', 'off'):
            self._action_message = 'Unsupported manual action: ' + action
        elif self._simulation_mode:
            self._action_message = f'Simulation: would request TV {action}. No command sent.'
        elif not self._service_data.get('cec_enabled'):
            self._action_message = 'Live CEC control is unavailable.'
        else:
            reply = self._service_interface().call('RequestPower', action)
            error = self._reply_error(reply)
            self._action_message = (
                'Request queued: TV ' + action if error is None
                else 'Request rejected: ' + error)
        self.changed.emit()

    @Slot('QVariantMap')
    def applySettings(self, values):
        config_saved = False
        try:
            validated = config_from_settings(self.config, values)
            if self.dbus_only:
                interface = self._service_interface()
                if not interface.isValid():
                    raise RuntimeError('topCEC host service is not available')
                reply = interface.call('ApplySettings', json.dumps({
                    'schema_version': 1, **validated,
                }, sort_keys=True))
                error = self._reply_error(reply)
                if error:
                    raise RuntimeError(error)
            else:
                save_config(
                    self.config_path, {'schema_version': 1, **validated})
                config_saved = True
                self.config = validated
                result = subprocess.run(
                    ['systemctl', '--user', 'restart', 'topcec.service'],
                    capture_output=True, text=True, timeout=60)
                if result.returncode:
                    raise RuntimeError(result.stderr.strip() or result.stdout.strip())
            self.config = validated
            self._action_message = (
                'Settings saved; topcec.service restart queued.')
        except (KeyError, OSError, TypeError, ValueError, RuntimeError,
                subprocess.TimeoutExpired) as error:
            self._action_message = (
                'Settings saved, but service restart failed: ' + str(error)
                if config_saved else 'Could not apply settings: ' + str(error))
        self.refresh()
        self.changed.emit()


def main():
    app = QGuiApplication(sys.argv)
    app.setApplicationName('topCEC')
    backend = GuiBackend()
    backend.refresh()
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty('topcec', backend)
    engine.load(QUrl.fromLocalFile(str(Path(__file__).with_name('topcec.qml'))))
    if not engine.rootObjects():
        return 2
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
