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
    QObject, Property, QProcess, QSettings, QTimer, QStandardPaths, QUrl, Signal, Slot,
)
from PySide6.QtDBus import (
    QDBusConnection, QDBusInterface, QDBusMessage, QDBusPendingCallWatcher,
)
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtQml import QQmlApplicationEngine

from activity_policy import DEFAULT_TIMEOUT
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
    adapter = str(values['adapter']).strip()
    timeout_seconds = (
        None if timeout_mode == 'never'
        else int(values.get('timeoutMinutes', DEFAULT_TIMEOUT / 60)) * 60)
    if timeout_mode == 'kde':
        timeout_seconds = current['timeout_seconds']
    config = {
        'schema_version': 1,
        'target_output': str(values['targetOutput']).strip(),
        'timeout_seconds': timeout_seconds,
        'mapping_ttl_seconds': current['mapping_ttl_seconds'],
        'devices': [item.strip() for item in str(values['devices']).splitlines()
                    if item.strip()],
        'consider_input_devices': values.get(
            'considerInputDevices', current['consider_input_devices']),
        'mouse_output': values.get('mouseOutput', current['mouse_output']),
        'mouse_outputs': values.get(
            'mouseOutputs', None if 'mouseOutput' in values else current['mouse_outputs']),
        'mute_labels': [item.strip() for item in str(values['muteLabels']).splitlines()
                        if item.strip()],
        'firefox_audio_blocks_standby': values.get(
            'firefoxAudioBlocksStandby', current['firefox_audio_blocks_standby']),
        'chromium_audio_blocks_standby': values.get(
            'chromiumAudioBlocksStandby', current['chromium_audio_blocks_standby']),
        'firefox_video_blocks_standby': values.get(
            'firefoxVideoBlocksStandby', current['firefox_video_blocks_standby']),
        'chromium_video_blocks_standby': values.get(
            'chromiumVideoBlocksStandby', current['chromium_video_blocks_standby']),
        'idle_inhibition_apps': values.get(
            'idleInhibitionApps', current['idle_inhibition_apps']),
        'idle_inhibition_exceptions': values.get(
            'idleInhibitionExceptions', current['idle_inhibition_exceptions']),
        'force_inhibition_apps': values.get(
            'forceInhibitionApps', current['force_inhibition_apps']),
        'allow_standby_on_unknown_app_status': values.get(
            'allowStandbyOnUnknownAppStatus',
            current['allow_standby_on_unknown_app_status']),
        'cec_enabled': bool(adapter),
        'cec_port': adapter,
        'kde_timeout': timeout_mode == 'kde',
        'require_snapshot': True,
        'axis_deadzone_percent': float(values['axisDeadzone']),
        'rz_deadzone_percent': float(values['rzDeadzone']),
        'device_axis_deadzones': values.get(
            'deviceAxisDeadzones', current['device_axis_deadzones']),
    }
    return validate_config(config)


class GuiBackend(QObject):
    changed = Signal()
    appsChanged = Signal()
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
        self._chromium_audio_supported = None
        self._browser_video_supported = None
        self._browser_setup = {}
        self._browser_setup_message = ''
        self._browser_setup_pending = False
        self._browser_setup_generation = 0
        self._service_status = 'Checking service'
        self._power_state = 'unknown'
        self._simulated_action = None
        self._standby_reason = 'Waiting for service status'
        self._diagnostics = 'No service diagnostics received.'
        self._connection_state = 'connecting'
        self._connection_message = 'Connecting to the topCEC host service.'
        self._action_message = ''
        self._settings_in_flight = False
        self._settings_generation = 0
        self._saving_inputs_only = False
        self._retrying_monitoring = False
        self._failed_input_draft = None
        self._submitted_input_draft = None
        self._input_preferences = QSettings(
            str(self.config_path) + '.input-draft.ini', QSettings.Format.IniFormat)
        self._input_save_timer = QTimer(self)
        self._input_save_timer.setInterval(500)
        self._input_save_timer.timeout.connect(self._save_pending_inputs)
        self._input_save_timer.start()
        self._status_poll_timer = QTimer(self)
        self._status_poll_timer.setInterval(5000)
        self._status_poll_timer.timeout.connect(self._poll_service_status)
        self._status_poll_timer.start()
        self._status_poll_in_flight = False
        self._config_source = 'unknown' if self.dbus_only else 'defaults'
        self._host_supports_idle_exceptions = None
        self._host_supports_unknown_app_policy = None
        self._service_data = {}
        self._equipment = {'outputs': [], 'adapters': [], 'inputs': []}
        self._equipment_known = False
        self._adapter_inventory_known = False
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
        if self.config['target_output'] and self.config['target_output'] not in self.outputs:
            self.outputs.insert(0, self.config['target_output'])
        if self.config['cec_port'] and self.config['cec_port'] not in self.adapters:
            self.adapters.insert(0, self.config['cec_port'])

    @Property(QIcon, constant=True)
    def applicationIcon(self):
        return application_icon()

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
    def liveSettingsAvailable(self):
        return self.backendAvailable and self._service_data.get('settings_apply') == 'live'

    @Property(bool, notify=changed)
    def automaticIdleInhibition(self):
        return not self.backendAvailable or self._host_supports_idle_exceptions is not False

    @Property(bool, notify=changed)
    def dbusOnly(self):
        return self.dbus_only

    @Property(str, notify=changed)
    def powerState(self):
        if self._simulated_action:
            return ('On' if self._simulated_action == 'on' else 'Off') + ' (simulated)'
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
    def blockedInputPath(self):
        help_data = self._service_data.get('input_permission_help')
        path = help_data.get('path') if isinstance(help_data, dict) else None
        return path if isinstance(path, str) else ''

    @Property(bool, notify=changed)
    def monitoringRetryAvailable(self):
        return (self.backendAvailable and self._service_status == 'configuration-only'
                and self._config_source == 'saved')

    @Property(str, notify=changed)
    def diagnostics(self):
        return self._diagnostics

    @Property(str, notify=changed)
    def actionMessage(self):
        return self._action_message

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
        known = equipment is not None and not any(
            not error.startswith('Input axis discovery (')
            for error in equipment.get('errors', []))
        adapter_known = equipment is not None and not any(
            error.startswith('CEC adapter discovery:') for error in equipment.get('errors', []))
        equipment = equipment or {'outputs': [], 'adapters': [], 'inputs': []}
        if (equipment != self._equipment or message != self._equipment_message
                or known != self._equipment_known
                or adapter_known != self._adapter_inventory_known):
            self._equipment = equipment
            self._equipment_message = message
            self._equipment_known = known
            self._adapter_inventory_known = adapter_known
            if self.backendAvailable:
                self._update_diagnostics()
                self.changed.emit()
            self.equipmentChanged.emit()

    @Slot(str, result='QVariant')
    def setting(self, key):
        return self.config.get(key)

    @Slot(result=int)
    def timeoutMinutes(self):
        return max(1, round((self.config['timeout_seconds'] or DEFAULT_TIMEOUT) / 60))

    @Slot(result=bool)
    def usesKdeTimeout(self):
        return self.config['kde_timeout']

    @Property(str, notify=changed)
    def plasmaTimeoutLabel(self):
        label = 'Follow Plasma power setting'
        if self._service_data.get('plasma_timeout_fallback') is True:
            seconds = self.config['timeout_seconds']
            if seconds is None:
                return label + ' (unavailable; standby disabled)'
            minutes = seconds / 60
            unit = 'minute' if minutes == 1 else 'minutes'
            return f'{label} (unavailable; using {minutes:g} {unit})'
        if self._service_data.get('plasma_timeout_read') is not True:
            return label
        seconds = self._service_data.get('plasma_timeout_seconds')
        if seconds is None:
            return label + ' (disabled)'
        if type(seconds) is not int or seconds <= 0:
            return label
        minutes = seconds / 60
        unit = 'minute' if minutes == 1 else 'minutes'
        return f'{label} ({minutes:g} {unit})'

    @Property(bool, notify=changed)
    def firefoxPlaybackActive(self):
        return self._service_data.get('playback_active') is True

    @Property(str, notify=changed)
    def firefoxAudioStatusMessage(self):
        if (not self.backendAvailable
                or self._service_status not in ('running', 'configuration-only')):
            return 'Firefox audio status is unavailable while monitoring is stopped.'
        if 'firefox_audio_error' not in self._service_data:
            return 'Firefox audio status is unavailable. Update the host service.'
        error = self._service_data['firefox_audio_error']
        if error:
            return ('Firefox audio status is unknown. TV standby is allowed by your setting.'
                    if self.config['allow_standby_on_unknown_app_status']
                    else 'Firefox audio status is unknown. TV standby is blocked.')
        return ''

    @Property(str, notify=changed)
    def firefoxAccessibilityHelp(self):
        error = self._service_data.get('firefox_audio_error')
        if (not self.config['firefox_audio_blocks_standby'] or not error
                or 'WebExtension' in error):
            return ''
        return (
            'If AT-SPI cannot read Firefox, open about:config in Firefox and set '
            'accessibility.force_disabled to -1, then fully quit and restart Firefox. '
            'For Firefox Flatpak, you may also need to launch it each time with: '
            'flatpak run --env=GNOME_ACCESSIBILITY=1 org.mozilla.firefox. '
            'A fresh Firefox profile must finish the welcome dialog first.')

    @Property(str, notify=changed)
    def chromiumAudioStatusMessage(self):
        errors = self._service_data.get('chromium_audio_errors')
        if isinstance(errors, dict) and errors:
            outcome = ('TV standby is allowed by your setting.'
                       if self.config['allow_standby_on_unknown_app_status']
                       else 'TV standby is blocked.')
            return ('Browser audio status is unknown. ' + outcome + ' '
                    'See Diagnostics for details.')
        return ''

    @Property(str, notify=changed)
    def browserSetupMessage(self):
        return self._browser_setup_message

    @Property(str, notify=changed)
    def browserSetupPath(self):
        return self._browser_setup.get('extension', '')

    @Property(bool, notify=changed)
    def browserSetupPending(self):
        return self._browser_setup_pending

    @Property('QVariant', notify=changed)
    def browserExtensionReports(self):
        reports = self._service_data.get('browser_extension_reports')
        return reports if isinstance(reports, dict) else {}

    @Slot()
    def resetBrowserSetup(self):
        self._browser_setup_generation += 1
        self._browser_setup = {}
        self._browser_setup_message = ''
        self._browser_setup_pending = False
        self.changed.emit()

    @Slot(str, bool, str, bool)
    def setupBrowser(self, browser, flatpak, extension_id, grant_access):
        if self._browser_setup_pending:
            return
        if not self.backendAvailable:
            self._browser_setup_message = 'Connect to the host service before setting up a browser.'
            self.changed.emit()
            return
        interface = self._service_interface()
        if not interface.isValid():
            self._browser_setup_message = 'The topCEC host service is not available.'
            self.changed.emit()
            return
        self._browser_setup_generation += 1
        generation = self._browser_setup_generation
        self._browser_setup_pending = True
        self._browser_setup_message = 'Preparing browser setup...'
        self.changed.emit()
        request = json.dumps({'browser': browser, 'flatpak': flatpak,
                              'extension_id': extension_id.strip(),
                              'grant_access': grant_access})
        self._async_call(interface, 'SetupBrowser',
                         lambda reply: self._browser_setup_reply(generation, reply), request)

    def _browser_setup_reply(self, generation, reply):
        if generation != self._browser_setup_generation:
            return
        self._browser_setup_pending = False
        error = self._reply_error(reply)
        if error:
            if reply.errorName() == 'org.freedesktop.DBus.Error.UnknownMethod':
                error = 'Update the host backend and restart topcec.service to use browser setup.'
            self._browser_setup_message = 'Browser setup failed: ' + error
        else:
            try:
                result = json.loads(str(reply.arguments()[0]))
                if (not isinstance(result, dict) or not isinstance(result.get('extension'), str)
                        or type(result.get('registered')) is not bool
                        or type(result.get('flatpak')) is not bool
                        or type(result.get('access_granted')) is not bool):
                    raise ValueError('Invalid host response')
            except (IndexError, TypeError, ValueError) as error:
                self._browser_setup_message = 'Browser setup failed: ' + str(error)
            else:
                self._browser_setup = result
                if result.get('browser') == 'firefox':
                    self._browser_setup_message = (
                        'The Firefox native host is installed with topCEC. Load the add-on '
                        'temporarily from the folder below; Firefox removes temporary add-ons '
                        'when it closes. A Mozilla-signed XPI is required for permanent '
                        'installation.')
                    if result['flatpak']:
                        self._browser_setup_message += (
                            ' Firefox Flatpak also needs native-messaging proxy support.')
                elif not result['registered']:
                    self._browser_setup_message = (
                        'Load the extension from the folder below, then paste its extension ID.')
                elif result['flatpak'] and not result['access_granted']:
                    self._browser_setup_message = (
                        'Native host registered. Flatpak access still needs to be granted; '
                        'select the permission below and register again, then restart the browser.')
                else:
                    self._browser_setup_message = (
                        'Native host registered. Fully quit and restart the browser, '
                        'then enable its audio option above.')
        self.changed.emit()

    @Property('QVariantList', notify=appsChanged)
    def installedApps(self):
        apps = self._service_data.get('installed_apps')
        if not isinstance(apps, list):
            return []
        return [app for app in apps if isinstance(app, dict)
                and isinstance(app.get('id'), str) and isinstance(app.get('name'), str)]

    @Property('QVariantList', notify=changed)
    def observedApps(self):
        apps = self._service_data.get('observed_apps')
        if not isinstance(apps, list):
            return []
        return [app for app in apps if isinstance(app, dict)
                and isinstance(app.get('id'), str) and isinstance(app.get('name'), str)]

    @Property('QVariantList', notify=changed)
    def activeInhibitorApps(self):
        apps = self._service_data.get('active_inhibitor_apps')
        return [app['id'] for app in apps
                if isinstance(app, dict) and isinstance(app.get('id'), str)] \
            if isinstance(apps, list) else []

    @Property(str, notify=changed)
    def inhibitionHistoryMessage(self):
        return str(self._service_data.get('inhibition_history_error') or '')

    @Property(str, notify=changed)
    def appDiscoveryMessage(self):
        if not self.backendAvailable:
            return 'Installed apps are unavailable while the host service is disconnected.'
        error = self._service_data.get('installed_apps_error')
        if error:
            return str(error)
        if not isinstance(self._service_data.get('installed_apps'), list):
            return 'The host has not reported installed apps. Update the host service.'
        return '' if self.installedApps else 'No installed apps detected.'

    @Property('QVariantList', notify=changed)
    def blockingApps(self):
        apps = self._service_data.get('blocking_apps')
        if not isinstance(apps, list):
            apps = []
        if self.firefoxPlaybackActive:
            apps = [*apps, {
                'app': 'Mozilla Firefox', 'reason': 'Audio',
                'identityUnknown': False, 'locationUnknown': False,
            }]
        displayed = []
        for app in apps:
            if (not isinstance(app, dict)
                    or not isinstance(app.get('app'), str)
                    or not isinstance(app.get('reason'), str)
                    or not isinstance(app.get('locationUnknown'), bool)):
                continue
            item = dict(app)
            if item['reason'] in ('Audio', 'Video'):
                existing = next((shown for shown in displayed
                                 if shown['app'] == item['app']
                                 and shown['reason'] in ('Audio', 'Video',
                                                         'Audio and video')), None)
                if existing:
                    if existing['reason'] != item['reason']:
                        existing['reason'] = 'Audio and video'
                    existing['identityUnknown'] = (
                        existing.get('identityUnknown', False)
                        or item.get('identityUnknown', False))
                    existing['locationUnknown'] = (
                        existing['locationUnknown'] or item['locationUnknown'])
                    continue
            displayed.append(item)
        return displayed

    @Property(str, notify=changed)
    def eventLog(self):
        entries = self._service_data.get('event_log')
        if not isinstance(entries, list):
            return 'No events have been reported by the host service.'
        lines = []
        for entry in entries:
            if (not isinstance(entry, dict)
                    or not isinstance(entry.get('time'), str)
                    or not isinstance(entry.get('message'), str)):
                continue
            lines.append(f"{entry['time']}  {entry['message']}")
        return '\n'.join(lines) if lines else 'No events have been reported yet.'

    @Property(str, notify=changed)
    def inhibitionsMessage(self):
        if not self.backendAvailable:
            return 'Plasma idle-inhibition status is unavailable.'
        error = self._service_data.get('inhibitions_error')
        if error:
            return str(error)
        if 'blocking_apps' not in self._service_data:
            return 'The host has not reported Plasma idle-inhibition status.'
        return ''

    @Property(str, notify=changed)
    def standbyBlockMessage(self):
        reason = self._service_data.get('fail_safe_reason')
        if (self.backendAvailable and self._service_status == 'running'
                and isinstance(reason, str) and reason
                and not reason.startswith('App standby block: ')):
            return 'Automatic standby blocked: ' + reason
        return ''

    def _set_service_data(self, data):
        previous = self._service_data.get('installed_apps')
        self._service_data = data
        if previous != data.get('installed_apps'):
            self.appsChanged.emit()

    @Slot(result=str)
    def deviceList(self):
        pending = self._input_preferences.value('pending')
        if pending is not None:
            return pending
        return '' if self._config_source == 'defaults' else '\n'.join(self.config['devices'])

    @Slot(str)
    def rememberInputDraft(self, devices):
        self._failed_input_draft = None
        self._input_preferences.setValue('pending', devices)
        self._input_preferences.sync()
        self._save_pending_inputs()

    @Slot(result=bool)
    def hasInputDraft(self):
        return self._input_preferences.contains('pending')

    def _save_pending_inputs(self):
        if (not self.hasInputDraft() or self._settings_in_flight
                or (self.dbus_only and not self.backendAvailable)):
            return
        if self.deviceList() == self._failed_input_draft:
            return
        self.applySettings({'devices': self.deviceList()}, inputs_only=True)

    @Slot(result=str)
    def muteLabelList(self):
        return '\n'.join(self.config['mute_labels'])

    @Slot(str)
    def simulatePower(self, action):
        if action not in ('on', 'off'):
            self._action_message = 'Unsupported simulation action: ' + action
        else:
            self._simulated_action = action
            self._action_message = ''
            if self.backendAvailable:
                self._update_diagnostics()
        self.changed.emit()

    @Slot(str)
    def copyText(self, text):
        QGuiApplication.clipboard().setText(text)

    def _service_interface(self):
        return QDBusInterface(
            SERVICE, OBJECT, INTERFACE, QDBusConnection.sessionBus())

    @Slot()
    def _poll_service_status(self):
        if (not self.backendAvailable
                or self._refresh_in_flight
                or self._settings_in_flight or self._status_poll_in_flight):
            return
        interface = self._service_interface()
        if not interface.isValid():
            self.refresh()
            return
        self._status_poll_in_flight = True
        generation = self._refresh_generation
        self._async_call(
            interface, 'GetStatus',
            lambda reply: self._status_poll_reply(generation, reply))

    def _status_poll_reply(self, generation, reply):
        self._status_poll_in_flight = False
        if generation != self._refresh_generation:
            return
        error = self._reply_error(reply)
        if error:
            self._connection_failed(generation, error)
            return
        try:
            data = json.loads(str(reply.arguments()[0]))
            if not isinstance(data, dict):
                raise ValueError('Status response must be an object')
            read = data.get('plasma_timeout_read', False)
            seconds = data.get('plasma_timeout_seconds')
            fallback = data.get('plasma_timeout_fallback', False)
            if (type(read) is not bool or type(fallback) is not bool
                    or (seconds is not None and
                        (type(seconds) is not int or seconds <= 0))
                    or (seconds is not None and not read)):
                raise ValueError('Invalid Plasma timeout status')
        except (IndexError, TypeError, ValueError, json.JSONDecodeError) as error:
            self._connection_failed(
                generation, 'Invalid monitor status response: ' + str(error))
            return
        self._set_service_data({**self._service_data, **data})
        self._service_status = self._service_data.get('service', self._service_status)
        self._power_state = self._service_data.get('power_state', self._power_state)
        reason = self._service_data.get('fail_safe_reason')
        self._standby_reason = (
            'Automatic standby allowed' if not reason
            else 'Automatic standby blocked: ' + str(reason))
        self._update_diagnostics()
        self.changed.emit()

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
        self._status_poll_in_flight = False
        self._failed_input_draft = None
        self._refresh_in_flight = False
        self._set_service_data({})
        self._host_supports_idle_exceptions = None
        self._host_supports_unknown_app_policy = None
        self._missing_capabilities.clear()
        self._set_equipment(None, 'Host equipment inventory will refresh after reconnection.')
        self._power_state = 'unavailable'
        if self._settings_in_flight:
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
        self._set_service_data({})
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
        self._status_poll_in_flight = False
        self.changed.emit()

    def _set_connection_error(self, message):
        self._set_equipment(None, 'Host equipment discovery is unavailable: ' + message)
        self._set_service_data({})
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
            data = json.loads(str(reply.arguments()[0]))
            if not isinstance(data, dict):
                raise ValueError('Status response must be an object')
            self._set_service_data(data)
        except (IndexError, TypeError, ValueError, json.JSONDecodeError) as error:
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
            raw_config = json.loads(str(reply.arguments()[0]))
            config = validate_config(raw_config)
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
        self._host_supports_idle_exceptions = 'idle_inhibition_exceptions' in raw_config
        self._host_supports_unknown_app_policy = (
            'allow_standby_on_unknown_app_status' in raw_config)
        self._chromium_audio_supported = 'chromium_audio_blocks_standby' in raw_config
        self._browser_video_supported = (
            'firefox_video_blocks_standby' in raw_config
            and 'chromium_video_blocks_standby' in raw_config)
        self.outputs = list(dict.fromkeys(
            ([config['target_output']] if config['target_output'] else []) + self.outputs))
        self.adapters = list(dict.fromkeys(
            ([config['cec_port']] if config['cec_port'] else []) + self.adapters))
        self._service_status = self._service_data.get('service', 'running')
        self._power_state = self._service_data.get('power_state', 'unknown')
        reason = self._service_data.get('fail_safe_reason')
        self._standby_reason = (
            'Automatic standby allowed' if not reason
            else 'Automatic standby blocked: ' + str(reason))
        self._connection_state = 'connected'
        self._update_diagnostics()
        self._connection_message = (
            'Connected for configuration only. Settings and standby diagnostics remain '
            'available without a CEC adapter. Correct input-device access and apply '
            'settings to resume monitoring.'
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

    def _update_diagnostics(self):
        fault = self._service_data.get('cec_fault')
        if not fault and self._adapter_inventory_known and not self._equipment['adapters']:
            fault = 'adapter not found'
        pending = self._service_data.get('pending_action') or 'none'
        if self._simulated_action:
            pending = ('on' if self._simulated_action == 'on' else 'standby') + ' (simulated)'
        audio_error = self._service_data.get('firefox_audio_error')
        audio_enabled = self.config['firefox_audio_blocks_standby']
        diagnostic_items = [
            f"Scan: {self._service_data.get('scan_status') or 'healthy'}",
            'Firefox audio: ' + (
                ('disabled' if not audio_enabled else audio_error or 'healthy')
                if 'firefox_audio_error' in self._service_data else 'not reported'),
            f"CEC fault: {fault or 'none'}",
            f"Pending action: {pending}",
            f"Settings error: {self._service_data.get('settings_error') or 'none'}",
        ]
        if self._service_data.get('monitoring_error'):
            diagnostic_items.append('Monitoring: ' + str(self._service_data['monitoring_error']))
        if self.firefoxAccessibilityHelp:
            diagnostic_items.append('Firefox accessibility: ' + self.firefoxAccessibilityHelp)
        errors = self._service_data.get('chromium_audio_errors')
        if isinstance(errors, dict):
            for browser, error in sorted(errors.items()):
                diagnostic_items.append(f'{browser} audio: {error}')
            if errors:
                diagnostic_items.append(
                    'Run the browser extension setup script described in the README, '
                    'load the unpacked extension, and rerun setup with its extension ID. '
                    'For Flatpak, run the printed browser-media D-Bus override and '
                    'fully quit and restart the browser.')
        errors = self._service_data.get('chromium_video_errors')
        if isinstance(errors, dict):
            for browser, error in sorted(errors.items()):
                diagnostic_items.append(f'{browser} video: {error}')
        self._diagnostics = '\n'.join(diagnostic_items)

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
                        or ('axes' in item and item['axes'] is not None
                            and (not isinstance(item['axes'], list) or any(
                                not isinstance(axis, dict)
                                or type(axis.get('code')) is not int
                                or not 0 <= axis['code'] < 47
                                or not isinstance(axis.get('name'), str)
                                for axis in item['axes'])))
                        for item in equipment[key]):
                    raise ValueError('Invalid ' + key + ' inventory')
            errors = equipment.get('errors')
            if not isinstance(errors, list) or any(not isinstance(item, str) for item in errors):
                raise ValueError('Invalid equipment diagnostics')
        except (IndexError, TypeError, ValueError) as error:
            self._set_equipment(None, 'Invalid host equipment response: ' + str(error))
        else:
            availability_errors = [
                error for error in errors if not error.startswith('Input axis discovery (')]
            self._set_equipment(equipment,
                'Equipment refreshes automatically from the host. '
                'Your selections are retained, not replaced. ' +
                ('Undetected equipment has unknown availability because discovery '
                 'did not complete successfully. ' if availability_errors else
                 'An empty list means no equipment was detected by that discovery method. ') +
                ('Discovery diagnostics: ' + '; '.join(errors) if errors else ''))

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
        self._failed_input_draft = None
        self._refresh_in_flight = False
        self._connection_state = 'connecting'
        self._connection_message = 'Retrying the topCEC host service connection.'
        self.changed.emit()
        self.refresh()

    @Slot()
    def retryMonitoring(self):
        if self.monitoringRetryAvailable:
            self.applySettings({}, retry_monitoring=True)

    @Slot(str)
    def requestPower(self, action):
        description = 'on' if action == 'on' else 'standby'
        if action not in ('on', 'off'):
            self._action_message = 'Unsupported manual action: ' + action
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
                self._simulated_action = None
                self._update_diagnostics()
                self._action_message = ''
                self._async_call(
                    interface, 'RequestPower',
                    lambda reply: self._power_reply(
                        generation, description, reply), action)
        self.changed.emit()

    def _power_reply(self, generation, description, reply):
        if generation != self._refresh_generation:
            return
        error = self._capability_error('RequestPower', reply)
        self._action_message = '' if error is None else 'Request rejected: ' + error
        self.changed.emit()

    def _settings_reply(self, generation, reply):
        if generation != self._settings_generation:
            return
        self._settings_in_flight = False
        error = self._capability_error('ApplySettings', reply)
        if error:
            if self._saving_inputs_only:
                self._failed_input_draft = self._submitted_input_draft
            self._action_message = 'Could not apply settings: ' + error
            self.changed.emit()
            return
        try:
            result = json.loads(str(reply.arguments()[0]))
            if not isinstance(result, dict) or result.get('accepted') is not True:
                raise ValueError('Host did not confirm that settings were saved')
            config = result['config']
            # Older hosts returned the complete configuration without its version.
            optional = {'consider_input_devices', 'mouse_output', 'mouse_outputs',
                        'firefox_audio_blocks_standby', 'idle_inhibition_apps',
                        'idle_inhibition_exceptions', 'force_inhibition_apps',
                        'chromium_audio_blocks_standby', 'firefox_video_blocks_standby',
                        'chromium_video_blocks_standby',
                        'allow_standby_on_unknown_app_status'}
            if (isinstance(config, dict) and set(DEFAULT_CONFIG) - optional <= set(config)
                    and set(config) <= set(DEFAULT_CONFIG)):
                config = {'schema_version': SCHEMA_VERSION, **config}
            saved = validate_config(config)
        except (IndexError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            if self._saving_inputs_only:
                self._failed_input_draft = self._submitted_input_draft
            self._action_message = 'Could not confirm saved settings: ' + str(error)
            self.changed.emit()
            return
        self._refresh_generation += 1
        self._refresh_in_flight = False
        self.config = saved
        self._config_source = 'saved'
        if not self._retrying_monitoring:
            self._failed_input_draft = None
        self._action_message = (
            '' if result.get('applied_live') is True else
            'Settings saved by an older backend; it may restart the service. '
            'Update the host backend for live settings.')
        self.changed.emit()
        if (not self._retrying_monitoring
                and self._input_preferences.value('pending') == self._submitted_input_draft):
            self._input_preferences.remove('pending')
            self._input_preferences.sync()
        if not self.hasInputDraft():
            if self._saving_inputs_only or self._retrying_monitoring:
                self.configurationChanged.emit()
            else:
                self.settingsSaved.emit()
        self.refresh()

    @Slot('QVariantMap')
    def applySettings(self, values, inputs_only=False, retry_monitoring=False):
        if self._settings_in_flight:
            return
        config_saved = False
        self._saving_inputs_only = inputs_only
        self._retrying_monitoring = retry_monitoring
        try:
            if retry_monitoring:
                validated = validate_config({'schema_version': SCHEMA_VERSION, **self.config})
            elif inputs_only:
                validated = validate_config({
                    'schema_version': SCHEMA_VERSION, **self.config,
                    'devices': values['devices'].splitlines(),
                })
            else:
                validated = config_from_settings(self.config, values)
            self._submitted_input_draft = '\n'.join(validated['devices'])
            if self.backendAvailable:
                interface = self._service_interface()
                if not interface.isValid():
                    self._set_unavailable()
                    raise RuntimeError('topCEC host service is not available')
                payload = {'schema_version': 1, **validated}
                if not payload['device_axis_deadzones']:
                    del payload['device_axis_deadzones']
                if not self.automaticIdleInhibition:
                    del payload['idle_inhibition_exceptions']
                if self._host_supports_unknown_app_policy is False:
                    if payload['allow_standby_on_unknown_app_status']:
                        raise RuntimeError(
                            'Allowing standby with unknown app status requires an '
                            'updated host backend. Update it and restart topcec.service.')
                    del payload['allow_standby_on_unknown_app_status']
                if self._browser_video_supported is False:
                    if (payload['firefox_video_blocks_standby']
                            or payload['chromium_video_blocks_standby']):
                        raise RuntimeError(
                            'Browser video detection requires an updated host backend. '
                            'Update it and restart topcec.service.')
                    del payload['firefox_video_blocks_standby']
                    del payload['chromium_video_blocks_standby']
                if self._chromium_audio_supported is False:
                    if payload['chromium_audio_blocks_standby']:
                        raise RuntimeError(
                            'Chromium browser audio detection requires an updated '
                            'host backend. Update it and restart topcec.service.')
                    del payload['chromium_audio_blocks_standby']
                serialized = json.dumps(payload, sort_keys=True)
                self._action_message = ('Retrying monitoring with the saved settings.'
                                        if retry_monitoring else
                                        'Saving settings through the host service.')
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
                if self.dbus_only:
                    raise RuntimeError('topCEC host service is not available')
                save_config(
                    self.config_path, {'schema_version': 1, **validated})
                config_saved = True
                self.config = validated
                self._config_source = 'saved'
            self.config = validated
            if self._input_preferences.value('pending') == '\n'.join(validated['devices']):
                self._input_preferences.remove('pending')
                self._input_preferences.sync()
            if inputs_only:
                self.configurationChanged.emit()
            else:
                self.settingsSaved.emit()
            self._action_message = (
                'Settings saved for the next service start; the host backend is offline.')
        except (KeyError, OSError, TypeError, ValueError, RuntimeError,
                subprocess.TimeoutExpired) as error:
            self._settings_in_flight = False
            if inputs_only:
                self._failed_input_draft = values.get('devices')
            self._action_message = (
                'Settings saved, but could not be confirmed: ' + str(error)
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
