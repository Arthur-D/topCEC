#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Optional KDE control panel for the topCEC user service."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from PySide6.QtCore import (
    QObject, Property, QProcess, QStandardPaths, QUrl, Signal, Slot,
)
from PySide6.QtDBus import (
    QDBusConnection, QDBusInterface, QDBusMessage, QDBusPendingCallWatcher,
)
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtQml import QQmlApplicationEngine

from configuration import (
    DEFAULT_CONFIG, SCHEMA_VERSION, default_config_path, load_config, save_config,
    validate_config,
)

SERVICE = 'net.local.CecActivity'
OBJECT = '/net/local/CecActivity'
INTERFACE = 'net.local.CecActivity'
APP_ID = 'net.local.topcec'
HOST_UPDATE_COMMAND = (
    "bash -c 'set -e; "
    'IFS= read -r -p "Full path to your existing topCEC checkout (without quotes): " checkout || '
    '{ echo "No checkout path supplied; no changes made." >&2; exit 1; }; '
    'case "$checkout" in /*) ;; '
    '*) echo "Enter an absolute checkout path; no changes made." >&2; exit 1 ;; esac; '
    'cd -- "$checkout" || '
    '{ echo "Checkout not found; no changes made." >&2; exit 1; }; '
    'prefix=$(git rev-parse --show-prefix) && test "$prefix" = "" && '
    'test "$(git branch --show-current)" = main && '
    'test -f packaging/install-user.sh || '
    '{ echo "Choose the official topCEC repository root on main; no changes made." >&2; exit 1; }; '
    'case "$(git remote get-url origin)" in '
    'https://github.com/Arthur-D/topCEC|https://github.com/Arthur-D/topCEC.git|'
    'git@github.com:Arthur-D/topCEC.git) ;; '
    '*) echo "Expected the official Arthur-D/topCEC origin; no changes made." >&2; exit 1 ;; esac; '
    "git pull --ff-only origin main; bash packaging/install-user.sh; systemctl --user restart topcec.service'"
)


def application_icon():
    installed = QStandardPaths.locate(
        QStandardPaths.StandardLocation.GenericDataLocation,
        f'icons/hicolor/scalable/apps/{APP_ID}.svg')
    fallback = QIcon(installed or str(Path(__file__).with_name(f'{APP_ID}.svg')))
    return QIcon.fromTheme(APP_ID, fallback)


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
    equipmentChanged = Signal()
    configurationChanged = Signal()
    settingsSaved = Signal()

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
        self._connection_state = 'connecting'
        self._connection_message = 'Connecting to the topCEC host service.'
        self._action_message = ''
        self._settings_in_flight = False
        self._settings_generation = 0
        self._config_source = 'unknown' if self.dbus_only else 'defaults'
        self._simulation_mode = False
        self._service_data = {}
        self._equipment = {'outputs': [], 'adapters': [], 'inputs': []}
        self._equipment_known = False
        self._missing_capabilities = set()
        self._equipment_message = (
            'Equipment has not been reported by the host. Configured values may '
            'be saved settings or defaults; they are not proof of detection.')
        self._refresh_in_flight = False
        self._refresh_generation = 0
        self._owner_watch_registered = False
        self._pending_watchers = []
        self._native_probe = QProcess(self)
        self._native_probe.finished.connect(
            lambda *_: self._native_service_probe_finished())
        self._native_probe.errorOccurred.connect(
            lambda *_: self._native_service_probe_failed())
        self._native_probe_running = False
        self._native_probe_generation = 0
        self._ensure_owner_watch()
        self.outputs = available_outputs() if not self.dbus_only else []
        self.adapters = available_adapters() if not self.dbus_only else []
        if not self.dbus_only:
            self._equipment['outputs'] = [{'path': path, 'label': path} for path in self.outputs]
            self._equipment['adapters'] = [{'path': path, 'label': path} for path in self.adapters]
        if not self.dbus_only and self.config_path.exists():
            try:
                self.config = {'schema_version': 1, **load_config(self.config_path)}
                self._config_source = 'saved'
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
    def connectionState(self):
        return self._connection_state

    @Property(str, notify=changed)
    def connectionMessage(self):
        return self._connection_message

    @Property(bool, notify=changed)
    def backendAvailable(self):
        return self._connection_state == 'connected'

    @Property(bool, notify=changed)
    def dbusOnly(self):
        return self.dbus_only

    @Property(str, notify=changed)
    def powerState(self):
        return self._power_state

    @Property(str, notify=changed)
    def standbyReason(self):
        return self._standby_reason

    @Property(str, notify=changed)
    def inputPermissionMessage(self):
        help_data = self._service_data.get('input_permission_help')
        if isinstance(help_data, dict) and help_data.get('message'):
            return help_data['message']
        reason = self._service_data.get('fail_safe_reason', '')
        if (self._service_status == 'configuration-only'
                and isinstance(reason, str) and reason.startswith('Cannot read input:')):
            return (
                'The host backend reported an input-access error but did not '
                'provide detailed permission guidance. Check that the selected '
                'device is correct and readable by the host user. Update the '
                'host backend from the repository root with '
                'bash packaging/install-user.sh, then restart topcec.service '
                'to obtain host-verified guidance. Updating only the Flatpak '
                'does not update the host backend. No input-group command can '
                'be recommended without checking device ownership and membership.')
        return ''

    @Property(str, notify=changed)
    def inputPermissionCommand(self):
        help_data = self._service_data.get('input_permission_help')
        return help_data.get('command', '') if isinstance(help_data, dict) else ''

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
        return not self._settings_in_flight and (not self.dbus_only or (
            self.backendAvailable and self._service_status in (
                'active', 'running', 'configuration-only')))

    @Property(str, notify=changed)
    def configurationSource(self):
        return self._config_source

    @Property('QVariantList', notify=changed)
    def outputOptions(self):
        return self.outputs

    @Property('QVariantList', notify=changed)
    def adapterOptions(self):
        return self.adapters

    @Property('QVariantList', notify=equipmentChanged)
    def detectedOutputs(self):
        return self._equipment['outputs']

    @Property('QVariantList', notify=equipmentChanged)
    def detectedAdapters(self):
        return self._equipment['adapters']

    @Property('QVariantList', notify=equipmentChanged)
    def detectedInputs(self):
        return self._equipment['inputs']

    @Property(str, notify=equipmentChanged)
    def equipmentMessage(self):
        return self._equipment_message

    @Property(bool, notify=equipmentChanged)
    def equipmentAvailabilityKnown(self):
        return self._equipment_known

    @Property(str, notify=equipmentChanged)
    def equipmentRecoveryCommands(self):
        return HOST_UPDATE_COMMAND if self._missing_capabilities else ''

    @Property(str, notify=equipmentChanged)
    def compatibilityMessage(self):
        return (
            'The running host backend lacks required GUI capabilities: '
            + ', '.join(sorted(self._missing_capabilities)) +
            '. Update the host installation and restart the service. '
            'Updating only Flatpak is insufficient.'
            if self._missing_capabilities else '')

    def _capability_error(self, method, reply):
        error = self._reply_error(reply)
        missing = set(self._missing_capabilities)
        if error is not None and reply.errorName() == 'org.freedesktop.DBus.Error.UnknownMethod':
            missing.add(method)
            error = (
                'The running host backend does not support ' + method +
                '. Update the host backend and restart topcec.service.')
        elif error is None:
            missing.discard(method)
        if missing != self._missing_capabilities:
            self._missing_capabilities = missing
            self.equipmentChanged.emit()
        return error

    def _set_equipment(self, equipment, message):
        known = equipment is not None and not equipment.get('errors')
        equipment = equipment or {'outputs': [], 'adapters': [], 'inputs': []}
        if (equipment != self._equipment or message != self._equipment_message
                or known != self._equipment_known):
            self._equipment = equipment
            self._equipment_message = message
            self._equipment_known = known
            self.equipmentChanged.emit()

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
        return '' if self._config_source == 'defaults' else '\n'.join(self.config['devices'])

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

    @Slot(str)
    def copyText(self, text):
        QGuiApplication.clipboard().setText(text)

    def _service_interface(self):
        return QDBusInterface(
            SERVICE, OBJECT, INTERFACE, QDBusConnection.sessionBus())

    def _ensure_owner_watch(self):
        if self._owner_watch_registered:
            return
        bus = QDBusConnection.sessionBus()
        if bus.isConnected():
            self._owner_watch_registered = bus.connect(
                'org.freedesktop.DBus', '/org/freedesktop/DBus',
                'org.freedesktop.DBus', 'NameOwnerChanged', self,
                '1_name_owner_changed(QString,QString,QString)')

    @Slot(str, str, str)
    def _name_owner_changed(self, name, old_owner, new_owner):
        if name != SERVICE or old_owner == new_owner:
            return
        self._refresh_generation += 1
        self._refresh_in_flight = False
        self._service_data = {}
        self._missing_capabilities.clear()
        self._set_equipment(None, 'Host equipment inventory will refresh after reconnection.')
        self._power_state = 'unavailable'
        if self._action_message == 'Saving settings through the host service.':
            self._action_message = (
                'The connection changed while saving settings. Reconnect and '
                'verify the saved configuration.')
        if new_owner:
            self._connection_state = 'connecting'
            self._connection_message = 'The topCEC service appeared; reconnecting.'
            self._service_status = 'Connecting'
            self._standby_reason = self._connection_message
            self._diagnostics = self._connection_message
            self.changed.emit()
            self.refresh()
        else:
            self._set_unavailable()

    @staticmethod
    def _reply_error(reply):
        if reply.type() == QDBusMessage.MessageType.ErrorMessage:
            return reply.errorMessage()
        return None

    def _async_call(self, interface, method, callback, *arguments):
        watcher = QDBusPendingCallWatcher(
            interface.asyncCallWithArgumentList(method, list(arguments)), self)
        self._pending_watchers.append(watcher)

        def finished(completed):
            if completed in self._pending_watchers:
                self._pending_watchers.remove(completed)
            callback(completed.reply())

        watcher.finished.connect(finished)

    def _start_native_service_probe(self):
        if self._native_probe_running:
            self._native_probe_generation = self._refresh_generation
            return
        self._native_probe_running = True
        self._native_probe_generation = self._refresh_generation
        self._native_probe.start(
            'systemctl', [
                '--user', 'show', '--property=LoadState',
                '--property=ActiveState', '--value', 'topcec.service',
            ])

    def _native_service_probe_finished(self):
        generation = self._native_probe_generation
        self._native_probe_running = False
        if generation != self._refresh_generation or self.backendAvailable:
            return
        output = bytes(self._native_probe.readAllStandardOutput()).decode(
            'utf-8', errors='replace')
        error_output = bytes(self._native_probe.readAllStandardError()).decode(
            'utf-8', errors='replace').strip()
        values = output.splitlines()
        if self._native_probe.exitCode() or len(values) < 2:
            details = error_output or output.strip()
            self._service_status = 'unknown'
            self._connection_message = (
                'The topCEC service is unavailable; systemd status could not be '
                'determined' + (': ' + details if details else '.'))
        else:
            load_state, active_state = values[:2]
            if load_state == 'not-found':
                self._service_status = 'not-installed'
                self._connection_message = (
                    'The topCEC user service is not installed.')
            elif load_state == 'loaded' and active_state != 'active':
                self._service_status = 'stopped'
                self._connection_message = (
                    'The topCEC user service is installed but stopped '
                    f'({active_state or "inactive"}).')
            else:
                self._service_status = 'unknown'
                self._connection_message = (
                    'The topCEC service is not reachable over session D-Bus.')
        self._standby_reason = self._connection_message
        self._diagnostics = self._connection_message
        self.changed.emit()

    def _native_service_probe_failed(self):
        generation = self._native_probe_generation
        self._native_probe_running = False
        if generation != self._refresh_generation or self.backendAvailable:
            return
        self._service_status = 'unknown'
        self._connection_message = (
            'The topCEC service is unavailable; systemd status could not be determined.')
        self._standby_reason = self._connection_message
        self._diagnostics = self._connection_message
        self.changed.emit()

    def _set_unavailable(self):
        self._set_equipment(None, 'Host equipment discovery is unavailable while disconnected.')
        self._service_data = {}
        self._power_state = 'unavailable'
        if self.dbus_only:
            self._service_status = 'unavailable'
            self._connection_message = (
                'The topCEC service is unavailable. The Flatpak cannot determine '
                'whether it is installed or stopped.')
        else:
            self._service_status = 'Checking service'
            self._connection_message = (
                'The topCEC service is unavailable; checking the user systemd unit.')
            self._start_native_service_probe()
        self._connection_state = 'unavailable'
        self._standby_reason = self._connection_message
        self._diagnostics = self._connection_message
        self._refresh_in_flight = False
        self.changed.emit()

    def _set_connection_error(self, message):
        self._set_equipment(None, 'Host equipment discovery is unavailable: ' + message)
        self._service_data = {}
        self._service_status = 'connection error'
        self._power_state = 'unavailable'
        self._connection_state = 'error'
        self._connection_message = message
        self._standby_reason = message
        self._diagnostics = message
        self._refresh_in_flight = False
        self.changed.emit()

    def _connection_failed(self, generation, error):
        if generation != self._refresh_generation:
            return
        self._set_connection_error(
            'Unable to use the topCEC service: ' + str(error) +
            '. Check the session D-Bus connection and service logs.')

    def _status_reply(self, generation, interface, reply):
        if generation != self._refresh_generation:
            return
        error = self._capability_error('GetStatus', reply)
        if error:
            self._connection_failed(generation, error)
            return
        try:
            self._service_data = json.loads(str(reply.arguments()[0]))
        except (IndexError, TypeError, json.JSONDecodeError) as error:
            self._connection_failed(
                generation, 'Invalid monitor status response: ' + str(error))
            return
        self._async_call(
            interface, 'GetConfig',
            lambda config_reply: self._config_reply(
                generation, config_reply, interface))

    def _config_reply(self, generation, reply, interface=None):
        if generation != self._refresh_generation:
            return
        error = self._capability_error('GetConfig', reply)
        if error:
            self._connection_failed(
                generation, 'Cannot read service configuration: ' + error)
            return
        try:
            config = validate_config(json.loads(str(reply.arguments()[0])))
        except (IndexError, TypeError, ValueError, json.JSONDecodeError) as error:
            self._connection_failed(
                generation, 'Cannot read service configuration: ' + str(error))
            return

        stored = self._service_data.get('configuration_saved')
        source = 'saved' if stored is True else ('defaults' if stored is False else 'unknown')
        config_changed = (config != self.config or not self.backendAvailable
                          or source != self._config_source)
        self._config_source = source
        self.config = config
        self.outputs = list(dict.fromkeys([config['target_output'], *self.outputs]))
        self.adapters = list(dict.fromkeys([config['cec_port'], *self.adapters]))
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
        self._connection_state = 'connected'
        self._connection_message = (
            'Connected for configuration only. Monitoring could not start. '
            'Correct the input devices and their host read permissions, then '
            'save settings to restart the service.'
            if self._service_status == 'configuration-only'
            else 'Connected to the topCEC host service.')
        self._refresh_in_flight = interface is not None
        self.changed.emit()
        if config_changed:
            self.configurationChanged.emit()
        if interface is not None:
            self._async_call(
                interface, 'GetEquipment',
                lambda equipment_reply: self._equipment_reply(generation, equipment_reply))

    def _equipment_reply(self, generation, reply):
        if generation != self._refresh_generation:
            return
        self._refresh_in_flight = False
        error = self._capability_error('GetEquipment', reply)
        if error:
            error_name = reply.errorName()
            if error_name == 'org.freedesktop.DBus.Error.UnknownMethod':
                self._set_equipment(None,
                    'The running host backend does not support equipment discovery. '
                    'Update the host backend and restart topcec.service. '
                    'Updating only the Flatpak or reloading systemd does not update '
                    'the running backend. Equipment availability is unknown; '
                    'your settings remain editable.')
            else:
                print('Host equipment discovery failed: ' + error, file=sys.stderr)
                self._set_equipment(None,
                    'Host equipment discovery could not be read'
                    + (' (' + error_name + ')' if error_name else '') +
                    '. Equipment availability is unknown. Check the host service '
                    'logs and retry; your settings remain editable.')
            return
        try:
            equipment = json.loads(str(reply.arguments()[0]))
            if not isinstance(equipment, dict):
                raise ValueError('Inventory must be an object')
            for key in ('outputs', 'adapters', 'inputs'):
                if not isinstance(equipment.get(key), list) or any(
                        not isinstance(item, dict)
                        or not isinstance(item.get('path'), str)
                        or not isinstance(item.get('label'), str)
                        or not isinstance(item.get('aliases', []), list)
                        or any(not isinstance(alias, str) for alias in item.get('aliases', []))
                        for item in equipment[key]):
                    raise ValueError('Invalid ' + key + ' inventory')
            errors = equipment.get('errors')
            if not isinstance(errors, list) or any(not isinstance(item, str) for item in errors):
                raise ValueError('Invalid equipment diagnostics')
        except (IndexError, TypeError, ValueError) as error:
            self._set_equipment(None, 'Invalid host equipment response: ' + str(error))
        else:
            self._set_equipment(equipment,
                'Equipment refreshes automatically from the host. '
                'Your selections are retained, not replaced. ' +
                ('Undetected equipment has unknown availability because discovery '
                 'did not complete successfully. Discovery diagnostics: ' + '; '.join(errors) if errors else
                 'An empty list means no equipment was detected by that discovery method.'))

    @Slot()
    def refresh(self):
        if self._refresh_in_flight or self._settings_in_flight:
            return
        self._ensure_owner_watch()
        self._refresh_generation += 1
        generation = self._refresh_generation
        self._refresh_in_flight = True
        if not self.backendAvailable:
            self._connection_state = 'connecting'
            self._connection_message = 'Connecting to the topCEC host service.'
        bus = QDBusConnection.sessionBus()
        if not bus.isConnected():
            self._connection_failed(generation, 'session D-Bus is disconnected')
            return
        interface = self._service_interface()
        if not interface.isValid():
            self._set_unavailable()
            return
        self._async_call(
            interface, 'GetStatus',
            lambda reply: self._status_reply(generation, interface, reply))

    @Slot()
    def retryConnection(self):
        self._refresh_in_flight = False
        self._connection_state = 'connecting'
        self._connection_message = 'Retrying the topCEC host service connection.'
        self.changed.emit()
        self.refresh()

    @Slot(str)
    def requestPower(self, action):
        description = 'on' if action == 'on' else 'standby'
        if action not in ('on', 'off'):
            self._action_message = 'Unsupported manual action: ' + action
        elif self._simulation_mode:
            self._action_message = f'Simulation: would request TV {description}. No command sent.'
        elif not self.backendAvailable:
            self._action_message = 'Cannot control the TV while the topCEC service is disconnected.'
        elif not self._service_data.get('cec_enabled'):
            self._action_message = 'Live CEC control is unavailable.'
        else:
            interface = self._service_interface()
            if not interface.isValid():
                self._set_unavailable()
                self._action_message = (
                    'Cannot control the TV because the topCEC service disconnected.')
            else:
                generation = self._refresh_generation
                self._action_message = 'Sending TV power request.'
                self._async_call(
                    interface, 'RequestPower',
                    lambda reply: self._power_reply(
                        generation, description, reply), action)
        self.changed.emit()

    def _power_reply(self, generation, description, reply):
        if generation != self._refresh_generation:
            return
        error = self._capability_error('RequestPower', reply)
        self._action_message = (
            'Request queued: TV ' + description if error is None
            else 'Request rejected: ' + error)
        self.changed.emit()

    def _settings_reply(self, generation, reply):
        if generation != self._settings_generation:
            return
        self._settings_in_flight = False
        error = self._capability_error('ApplySettings', reply)
        if error:
            self._action_message = 'Could not apply settings: ' + error
            self.changed.emit()
            return
        try:
            result = json.loads(str(reply.arguments()[0]))
            if not isinstance(result, dict) or result.get('accepted') is not True:
                raise ValueError('Host did not confirm that settings were saved')
            config = result['config']
            # Older hosts returned the complete configuration without its version.
            if isinstance(config, dict) and config.keys() == DEFAULT_CONFIG.keys():
                config = {'schema_version': SCHEMA_VERSION, **config}
            saved = validate_config(config)
        except (IndexError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            self._action_message = 'Could not confirm saved settings: ' + str(error)
            self.changed.emit()
            return
        self._refresh_generation += 1
        self._refresh_in_flight = False
        self.config = saved
        self._config_source = 'saved'
        self._action_message = 'Settings saved; topcec.service restart queued.'
        self.changed.emit()
        self.settingsSaved.emit()
        self.refresh()

    @Slot('QVariantMap')
    def applySettings(self, values):
        if self._settings_in_flight:
            return
        config_saved = False
        try:
            validated = config_from_settings(self.config, values)
            if self.dbus_only:
                if not self.backendAvailable:
                    raise RuntimeError('topCEC host service is not available')
                interface = self._service_interface()
                if not interface.isValid():
                    self._set_unavailable()
                    raise RuntimeError('topCEC host service is not available')
                serialized = json.dumps({
                    'schema_version': 1, **validated,
                }, sort_keys=True)
                self._action_message = 'Saving settings through the host service.'
                self._refresh_generation += 1
                self._refresh_in_flight = False
                self._settings_generation += 1
                self._settings_in_flight = True
                self.changed.emit()
                generation = self._settings_generation
                self._async_call(
                    interface, 'ApplySettings',
                    lambda reply: self._settings_reply(
                        generation, reply), serialized)
                return
            else:
                save_config(
                    self.config_path, {'schema_version': 1, **validated})
                config_saved = True
                self.config = validated
                self._config_source = 'saved'
                result = subprocess.run(
                    ['systemctl', '--user', 'restart', 'topcec.service'],
                    capture_output=True, text=True, timeout=60)
                if result.returncode:
                    raise RuntimeError(result.stderr.strip() or result.stdout.strip())
            self.config = validated
            self.settingsSaved.emit()
            self._action_message = (
                'Settings saved; topcec.service restart queued.')
        except (KeyError, OSError, TypeError, ValueError, RuntimeError,
                subprocess.TimeoutExpired) as error:
            self._settings_in_flight = False
            self._action_message = (
                'Settings saved, but service restart failed: ' + str(error)
                if config_saved else 'Could not apply settings: ' + str(error))
        self.refresh()
        self.changed.emit()


def main():
    app = QGuiApplication(sys.argv)
    app.setApplicationName('topCEC')
    app.setDesktopFileName(APP_ID)
    app.setWindowIcon(application_icon())
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
