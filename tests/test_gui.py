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
from PySide6.QtCore import QMetaObject, QObject, QPointF, Qt, QUrl, QStandardPaths, SIGNAL
from PySide6.QtGui import QAccessible, QFontMetricsF, QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine, QQmlExpression
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtQuick import QQuickItem

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'cec-tv'))

from cec_power_state import CecPowerStateMachine
from configuration import DEFAULT_CONFIG, load_config, save_config, validate_config
from monitor import request_manual_power
import topcec_gui
from topcec_gui import GuiBackend, config_from_settings


class GuiChecks(unittest.TestCase):
    def app_row(self, engine, window, index):
        engine.rootContext().setContextProperty(
            'appChoicesList', window.findChild(QObject, 'installedAppsScroll'))
        return QQmlExpression(engine.rootContext(), window,
                              f'appChoicesList.itemAtIndex({index})').evaluate()[0]

    def test_settings_are_saved_automatically_after_changes(self):
        app = QGuiApplication.instance() or QGuiApplication([])
        backend = GuiBackend(dbus_only=True)
        backend._connection_state = 'connected'
        backend._service_status = 'running'
        engine = QQmlApplicationEngine()
        engine.rootContext().setContextProperty('topcec', backend)
        engine.load(QUrl.fromLocalFile(str(ROOT / 'cec-tv/topcec.qml')))
        window = engine.rootObjects()[0]
        self.assertIsNone(window.findChild(QObject, 'saveSettingsButton'))
        backend._equipment_reply(0, self.reply({
            'outputs': [{'path': 'TV', 'label': 'TV'}],
            'adapters': [{'path': '/dev/mock-cec', 'label': 'CEC'}],
            'inputs': [],
            'errors': [],
        }))
        app.processEvents()
        timeout = window.findChild(QObject, 'timeoutMinutes')
        timeout.setProperty('value', 13)
        QMetaObject.invokeMethod(timeout, 'valueModified')
        self.assertTrue(window.property('settingsDirty'))

        requests = []
        interface = Mock(isValid=Mock(return_value=True))
        with patch.object(backend, '_service_interface', return_value=interface), \
                patch.object(backend, '_async_call', side_effect=lambda _, method, callback, *args:
                             requests.append((method, callback, args))), \
                patch.object(backend, 'refresh'):
            QTest.qWait(350)
            self.assertEqual(len(requests), 1)
            method, callback, arguments = requests.pop()
            self.assertEqual(method, 'ApplySettings')
            callback(self.reply({
                'accepted': True,
                'applied_live': True,
                'config': json.loads(arguments[0]),
            }))
        self.assertFalse(window.property('settingsDirty'))
        engine.deleteLater()

    def test_autosave_retains_unavailable_equipment_and_empty_input_selection(self):
        app = QGuiApplication.instance() or QGuiApplication([])
        for saved_status in (True, None):
            with self.subTest(configuration_saved=saved_status):
                backend = GuiBackend(dbus_only=True)
                backend._service_data = {'service': 'running'}
                if saved_status is not None:
                    backend._service_data['configuration_saved'] = saved_status
                initial = {**DEFAULT_CONFIG, 'target_output': 'TV-SAVED',
                           'cec_port': '/dev/saved-adapter', 'devices': []}
                backend._config_reply(0, self.reply({'schema_version': 1, **initial}))
                backend._set_equipment({
                    'outputs': [{'path': 'OTHER', 'label': 'Other display'}],
                    'adapters': [{'path': '/dev/other', 'label': 'Other adapter'}],
                    'inputs': [], 'errors': [],
                }, '')
                engine = QQmlApplicationEngine()
                engine.rootContext().setContextProperty('topcec', backend)
                engine.load(QUrl.fromLocalFile(str(ROOT / 'cec-tv/topcec.qml')))
                window = engine.rootObjects()[0]
                self.assertTrue(window.property('equipmentReady'))
                self.assertEqual(window.findChild(QObject, 'outputField').property('valueToSave'),
                                 initial['target_output'])
                self.assertEqual(window.findChild(QObject, 'adapterField').property('valueToSave'),
                                 initial['cec_port'])
                requests = []
                interface = Mock(isValid=Mock(return_value=True))
                with patch.object(backend, '_service_interface', return_value=interface), \
                        patch.object(backend, '_async_call', side_effect=lambda _, method, callback, *args:
                                     requests.append((method, callback, args))), \
                        patch.object(backend, 'refresh'):
                    QQmlExpression(engine.rootContext(), window,
                                   'setIdleApp("player.desktop", true)').evaluate()
                    QTest.qWait(350)
                    self.assertEqual(len(requests), 1)
                    method, callback, arguments = requests.pop()
                    self.assertEqual(method, 'ApplySettings')
                    saved = json.loads(arguments[0])
                    self.assertEqual(saved['target_output'], initial['target_output'])
                    self.assertEqual(saved['cec_port'], initial['cec_port'])
                    self.assertEqual(saved['devices'], [])
                    self.assertEqual(saved['idle_inhibition_apps'], ['player.desktop'])
                    callback(self.reply({'accepted': True, 'applied_live': True,
                                         'config': saved}))
                    self.assertFalse(window.property('settingsDirty'))
                    self.assertEqual(backend.config['idle_inhibition_apps'], ['player.desktop'])
                engine.deleteLater()
                app.processEvents()

    def test_standby_edits_autosave_after_inflight_save(self):
        app = QGuiApplication.instance() or QGuiApplication([])
        backend = GuiBackend(dbus_only=True)
        backend._connection_state = 'connected'
        backend._service_status = 'running'
        backend._config_source = 'saved'
        backend.config = {
            **DEFAULT_CONFIG, 'target_output': 'HDMI-A-2', 'cec_port': '/dev/mock-cec',
            'devices': [], 'consider_input_devices': False}
        backend._service_data = {
            'installed_apps': [{'id': 'firefox.desktop', 'name': 'Mozilla Firefox'}],
            'observed_apps': [], 'active_inhibitor_apps': [],
        }
        backend._set_equipment({
            'outputs': [{'path': 'HDMI-A-2', 'label': 'TV'},
                        {'path': 'DP-1', 'label': 'Monitor'}],
            'adapters': [{'path': '/dev/mock-cec', 'label': 'Adapter'}],
            'inputs': [], 'errors': [],
        }, '')
        engine = QQmlApplicationEngine()
        engine.rootContext().setContextProperty('topcec', backend)
        engine.load(QUrl.fromLocalFile(str(ROOT / 'cec-tv/topcec.qml')))
        window = engine.rootObjects()[0]
        window.show()
        window.setProperty('currentSection', 2)
        app.processEvents()
        firefox_row = self.app_row(engine, window, 0)
        firefox_audio = firefox_row.findChild(QObject, 'firefoxAudio')
        window.findChild(QObject, 'autoSaveTimer').setProperty('interval', 250)
        requests = []
        interface = Mock(isValid=Mock(return_value=True))
        with patch.object(backend, '_service_interface', return_value=interface), \
                patch.object(backend, '_async_call', side_effect=lambda _, method, callback, *args:
                             requests.append((method, callback, args))), \
                patch.object(backend, 'refresh'):
            QQmlExpression(engine.rootContext(), window, 'setMouseDisplay("DP-1", true)').evaluate()
            QTest.qWait(160)
            QQmlExpression(engine.rootContext(), window, 'setIdleApp("player.desktop", true)').evaluate()
            QTest.qWait(130)
            self.assertEqual(requests, [])
            QMetaObject.invokeMethod(firefox_audio, 'click')
            QTest.qWait(130)
            self.assertEqual(requests, [])
            QTest.qWait(160)
            self.assertEqual(len(requests), 1)
            method, callback, arguments = requests.pop()
            self.assertEqual(method, 'ApplySettings')
            first = json.loads(arguments[0])
            self.assertIn('DP-1', first['mouse_outputs'])

            QQmlExpression(engine.rootContext(), window, 'setMouseDisplay("DP-1", false)').evaluate()
            QQmlExpression(engine.rootContext(), window, 'setIdleApp("player.desktop", false)').evaluate()
            QMetaObject.invokeMethod(firefox_audio, 'click')
            QTest.qWait(300)
            self.assertEqual(requests, [])
            callback(self.reply({'accepted': True, 'applied_live': True, 'config': first}))
            QTest.qWait(300)
            self.assertEqual(len(requests), 1)
            method, callback, arguments = requests.pop()
            latest = json.loads(arguments[0])
            self.assertEqual(method, 'ApplySettings')
            self.assertNotIn('DP-1', latest['mouse_outputs'])
            self.assertEqual(latest['idle_inhibition_apps'], [])
            self.assertFalse(latest['firefox_audio_blocks_standby'])
            callback(self.reply({'accepted': True, 'applied_live': True, 'config': latest}))
            self.assertFalse(window.property('settingsDirty'))
        engine.deleteLater()

    def test_native_and_flatpak_live_apply_use_host_without_systemctl(self):
        app = QGuiApplication.instance() or QGuiApplication([])
        for dbus_only in (False, True):
            with self.subTest(dbus_only=dbus_only), \
                    patch.object(topcec_gui, 'available_outputs', return_value=[]), \
                    patch.object(topcec_gui, 'available_adapters', return_value=[]):
                backend = GuiBackend(dbus_only=dbus_only)
                backend._connection_state = 'connected'
                backend._service_status = 'running'
                engine = QQmlApplicationEngine()
                engine.rootContext().setContextProperty('topcec', backend)
                engine.load(QUrl.fromLocalFile(str(ROOT / 'cec-tv/topcec.qml')))
                window = engine.rootObjects()[0]
                helper = window.findChild(QObject, 'inputSaveHelp')
                self.assertFalse(helper.property('visible'))
                backend._service_data['settings_apply'] = 'live'
                backend.changed.emit()
                self.assertTrue(backend.liveSettingsAvailable)
                self.assertFalse(helper.property('visible'))
                window.setProperty('settingsDirty', True)
                requests = []
                interface = Mock(isValid=Mock(return_value=True))
                with patch.object(backend, '_service_interface', return_value=interface), \
                        patch.object(backend, '_async_call', side_effect=lambda _, method, callback, *args:
                                     requests.append((method, callback, args))), \
                        patch.object(backend, 'refresh'), \
                        patch.object(topcec_gui.subprocess, 'run',
                                     side_effect=AssertionError('No systemctl')), \
                        patch.object(topcec_gui, 'save_config',
                                     side_effect=AssertionError('Connected GUI must not write host config')):
                    backend.applySettings(self.values)
                    method, callback, args = requests.pop()
                    self.assertEqual(method, 'ApplySettings')
                    self.assertFalse(backend.settingsEnabled)
                    callback(self.reply({'accepted': True, 'applied_live': True,
                                         'config': json.loads(args[0])}))
                self.assertEqual(backend.actionMessage, '')
                self.assertFalse(window.findChild(QObject, 'actionFeedback').property('visible'))
                self.assertFalse(window.property('settingsDirty'))
                self.assertTrue(backend.settingsEnabled)
                self.assertIsNone(window.findChild(QObject, 'saveSettingsButton'))
                backend._connection_state = 'unavailable'
                backend.changed.emit()
                self.assertFalse(backend.liveSettingsAvailable)
                self.assertIn('remain pending', helper.property('text'))
                engine.deleteLater()

    def test_chromium_settings_require_a_compatible_host(self):
        app = QGuiApplication.instance() or QGuiApplication([])
        backend = GuiBackend(dbus_only=True)
        old_config = {'schema_version': 1, **DEFAULT_CONFIG}
        del old_config['chromium_audio_blocks_standby']
        backend._config_reply(0, self.reply(old_config))
        interface = Mock(isValid=Mock(return_value=True))
        with patch.object(backend, 'refresh'), \
                patch.object(backend, '_service_interface', return_value=interface), \
                patch.object(backend, '_async_call') as call:
            backend.applySettings({**self.values, 'chromiumAudioBlocksStandby': ['chrome']})
            self.assertFalse(call.called)
            self.assertIn('updated host backend', backend.actionMessage)
            backend.applySettings(self.values)
            payload = json.loads(call.call_args.args[3])
            self.assertNotIn('chromium_audio_blocks_standby', payload)

        backend._settings_in_flight = False
        backend._config_reply(backend._refresh_generation, self.reply(
            {'schema_version': 1, **DEFAULT_CONFIG, 'chromium_audio_blocks_standby': ['chrome']}))
        with patch.object(backend, '_service_interface', return_value=interface), \
                patch.object(backend, '_async_call') as call:
            backend.applySettings({**self.values, 'chromiumAudioBlocksStandby': []})
            payload = json.loads(call.call_args.args[3])
            self.assertEqual(payload['chromium_audio_blocks_standby'], [])

    def test_rejected_live_input_draft_is_retained_without_repeated_open_attempts(self):
        self.autosave_patch.stop()
        backend = GuiBackend(dbus_only=True)
        backend._connection_state = 'connected'
        backend._service_status = 'running'
        requests = []
        interface = Mock(isValid=Mock(return_value=True))
        with patch.object(backend, '_service_interface', return_value=interface), \
                patch.object(backend, '_async_call', side_effect=lambda _, method, callback, *args:
                             requests.append((method, callback, args))), \
                patch.object(backend, 'refresh'):
            original = dict(backend.config)
            backend.rememberInputDraft('/dev/input/denied')
            _, callback, _ = requests.pop()
            callback(topcec_gui.QDBusMessage.createError(
                'net.local.CecActivity.Error', 'Settings not applied: Permission denied'))
            self.assertIn('Permission denied', backend.actionMessage)
            self.assertTrue(backend.hasInputDraft())
            self.assertEqual(backend.config, original)
            for _ in range(3):
                backend._save_pending_inputs()
            self.assertEqual(requests, [])
            backend.rememberInputDraft('/dev/input/second')
            _, callback, _ = requests.pop()
            backend.rememberInputDraft('/dev/input/latest')
            callback(topcec_gui.QDBusMessage.createError(
                'net.local.CecActivity.Error', 'Second input failed'))
            backend._save_pending_inputs()
            _, callback, arguments = requests.pop()
            saved = json.loads(arguments[0])
            self.assertEqual(saved['devices'], ['/dev/input/latest'])
            callback(self.reply({'accepted': True, 'applied_live': True, 'config': saved}))
            self.assertFalse(backend.hasInputDraft())
            self.assertEqual(backend.actionMessage, '')

    def test_auto_input_save_queues_latest_selection_and_preserves_other_settings(self):
        app = QGuiApplication.instance() or QGuiApplication([])
        self.autosave_patch.stop()
        backend = GuiBackend(dbus_only=True)
        backend._connection_state = 'connected'
        backend.config['timeout_seconds'] = 73
        requests = []
        interface = Mock()
        interface.isValid.return_value = True
        with patch.object(backend, '_service_interface', return_value=interface), \
                patch.object(backend, '_async_call', side_effect=lambda _, method, callback, *args:
                             requests.append((callback, json.loads(args[0])))), \
                patch.object(backend, 'refresh'):
            backend.rememberInputDraft('/dev/input/keyboard')
            backend.rememberInputDraft('/dev/input/keyboard\n/dev/input/mouse')
            self.assertEqual(len(requests), 1)
            callback, first = requests.pop()
            self.assertEqual(first['timeout_seconds'], 73)
            self.assertEqual(first['cec_enabled'], DEFAULT_CONFIG['cec_enabled'])
            callback(self.reply({'accepted': True, 'config': first}))
            self.assertTrue(backend.hasInputDraft())
            backend._save_pending_inputs()
            callback, second = requests.pop()
            self.assertEqual(second['devices'], ['/dev/input/keyboard', '/dev/input/mouse'])
            callback(self.reply({'accepted': True, 'config': second}))
            self.assertFalse(backend.hasInputDraft())
            backend.rememberInputDraft('')
            callback, empty = requests.pop()
            self.assertEqual(empty['devices'], [])
            callback(self.reply({'accepted': True, 'config': empty}))
            self.assertFalse(backend.hasInputDraft())
            self.assertEqual(backend.deviceList(), '')

    def test_native_offline_input_selection_is_saved_and_failures_remain_pending(self):
        self.autosave_patch.stop()
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(topcec_gui, 'available_outputs', return_value=[]), \
                patch.object(topcec_gui, 'available_adapters', return_value=[]):
            path = Path(directory) / 'config.json'
            initial = {**DEFAULT_CONFIG, 'devices': ['/dev/input/old'],
                       'timeout_seconds': 73}
            save_config(path, {'schema_version': 1, **initial})
            backend = GuiBackend(path, dbus_only=False)
            backend._connection_state = 'unavailable'
            with patch.object(backend, 'refresh'):
                with patch.object(topcec_gui, 'save_config', side_effect=OSError('disk full')) as save:
                    backend.rememberInputDraft('/dev/input/new')
                    self.assertTrue(backend.hasInputDraft())
                    self.assertIn('disk full', backend.actionMessage)
                    backend._save_pending_inputs()
                    self.assertEqual(save.call_count, 1)
                    self.assertEqual(load_config(path)['devices'], ['/dev/input/old'])
                backend.rememberInputDraft('/dev/input/new')
                self.assertFalse(backend.hasInputDraft())
                saved = load_config(path)
                self.assertEqual(saved['devices'], ['/dev/input/new'])
                self.assertEqual(saved['timeout_seconds'], 73)

    @staticmethod
    def reply(value):
        return SimpleNamespace(
            type=lambda: topcec_gui.QDBusMessage.MessageType.ReplyMessage,
            arguments=lambda: [json.dumps(value)])

    @staticmethod
    def input_choice(engine, window, path):
        repeater = window.findChild(QObject, 'inputChoices')
        engine.rootContext().setContextProperty('inputRepeater', repeater)
        for index in range(repeater.property('count')):
            item = QQmlExpression(
                engine.rootContext(), window, f'inputRepeater.itemAt({index})').evaluate()[0]
            if item.objectName() == 'inputChoice:' + path:
                return item
        raise AssertionError('Input choice not found: ' + path)

    def test_input_selection_save_restart_alias_change_and_hotplug_end_to_end(self):
        app = QGuiApplication.instance() or QGuiApplication([])
        with tempfile.TemporaryDirectory() as directory:
            host_path = Path(directory) / 'host' / 'config.json'
            initial = {'schema_version': 1, **DEFAULT_CONFIG,
                       'target_output': 'OLD-DISPLAY',
                       'devices': ['/dev/input/event10']}
            save_config(host_path, initial)
            backend = GuiBackend(dbus_only=True)
            backend._service_data = {'service': 'running', 'configuration_saved': True}
            backend._config_reply(0, self.reply(initial))
            engine = QQmlApplicationEngine()
            engine.rootContext().setContextProperty('topcec', backend)
            engine.load(QUrl.fromLocalFile(str(ROOT / 'cec-tv/topcec.qml')))
            window = engine.rootObjects()[0]
            window.show()
            paths = window.findChild(QObject, 'devicesField')
            inventory = {
                'outputs': [{'path': 'eDP-1', 'label': 'Laptop display'}],
                'adapters': [],
                'inputs': [
                    {'path': '/dev/input/by-path/keyboard', 'label': 'Keyboard',
                     'aliases': ['/dev/input/event10']},
                    {'path': '/dev/input/by-id/mouse', 'label': 'Mouse',
                     'aliases': ['/dev/input/event20']}],
                'errors': [],
            }
            backend._equipment_reply(0, self.reply(inventory))
            window.setProperty('currentSection', 3)
            app.processEvents()
            keyboard = self.input_choice(engine, window, '/dev/input/by-path/keyboard')
            mouse = self.input_choice(engine, window, '/dev/input/by-id/mouse')
            self.assertTrue(keyboard.property('checked'))
            self.assertFalse(mouse.property('checked'))
            QMetaObject.invokeMethod(mouse, 'forceActiveFocus')
            QTest.keyClick(window, Qt.Key.Key_Space)
            self.assertTrue(mouse.property('checked'))
            self.assertTrue(mouse.property('activeFocus'))
            self.assertIs(self.input_choice(engine, window, '/dev/input/by-id/mouse'), mouse)
            self.assertTrue(backend.hasInputDraft())

            # Model a pre-save GetConfig already in flight, then the host's real
            # atomic persistence and an owner change before its save reply arrives.
            old_generation = backend._refresh_generation
            backend._refresh_in_flight = True
            requests = []
            interface = Mock()
            interface.isValid.return_value = True
            with patch.object(backend, '_service_interface', return_value=interface), \
                    patch.object(backend, '_async_call', side_effect=lambda _, method, callback, *args:
                                 requests.append((method, callback, args))), \
                    patch.object(backend, 'refresh'):
                window.setProperty('settingsDirty', True)
                engine.rootContext().setContextProperty('saveWindow', window)
                expression = QQmlExpression(
                    engine.rootContext(), window, 'saveWindow.applySettings()')
                expression.evaluate()
                self.assertFalse(expression.hasError(), expression.error().toString())
                method, callback, arguments = requests.pop()
                self.assertEqual(method, 'ApplySettings')
                submitted = json.loads(arguments[0])
                self.assertEqual(submitted['target_output'], initial['target_output'])
                self.assertEqual(submitted['cec_port'], initial['cec_port'])
                self.assertEqual(submitted['devices'],
                                 ['/dev/input/by-path/keyboard', '/dev/input/by-id/mouse'])
                saved = save_config(host_path, submitted)
                self.assertFalse(backend.settingsEnabled)
                backend._config_reply(old_generation, self.reply(initial))
                self.assertEqual(paths.property('text'), '/dev/input/event10\n/dev/input/by-id/mouse')
                backend._name_owner_changed(topcec_gui.SERVICE, ':1.10', '')
                backend._name_owner_changed(topcec_gui.SERVICE, '', ':1.11')
                callback(self.reply({'accepted': True, 'config': saved}))
                backend._config_reply(old_generation, self.reply(initial))
                self.assertEqual(backend.config['devices'], saved['devices'])
            self.assertFalse(window.property('settingsDirty'))
            self.assertEqual(paths.property('text'), '\n'.join(saved['devices']))
            self.assertEqual(load_config(host_path)['devices'], saved['devices'])

            # A new GUI reads the freshly started backend's stored configuration.
            fresh = GuiBackend(dbus_only=True)
            fresh._service_data = {'service': 'running', 'configuration_saved': True}
            fresh._config_reply(0, self.reply({'schema_version': 1, **load_config(host_path)}))
            fresh_engine = QQmlApplicationEngine()
            fresh_engine.rootContext().setContextProperty('topcec', fresh)
            fresh_engine.load(QUrl.fromLocalFile(str(ROOT / 'cec-tv/topcec.qml')))
            fresh_window = fresh_engine.rootObjects()[0]
            # A by-id alias now exists, event numbers changed, and event10 is audio.
            changed = {**inventory, 'inputs': [
                {'path': '/dev/input/by-id/keyboard', 'label': 'Keyboard',
                 'aliases': ['/dev/input/by-path/keyboard', '/dev/input/event7']},
                {'path': '/dev/input/by-id/mouse', 'label': 'Mouse',
                 'aliases': ['/dev/input/event8']},
                {'path': '/dev/input/event10', 'label': 'Audio', 'aliases': []}]}
            fresh._equipment_reply(0, self.reply(changed))
            self.assertTrue(self.input_choice(fresh_engine, fresh_window, '/dev/input/by-id/keyboard').property('checked'))
            self.assertTrue(self.input_choice(fresh_engine, fresh_window, '/dev/input/by-id/mouse').property('checked'))
            self.assertFalse(self.input_choice(fresh_engine, fresh_window, '/dev/input/event10').property('checked'))
            retained = fresh_window.findChild(QObject, 'devicesField').property('text')
            fresh._equipment_reply(0, self.reply({**changed, 'inputs': []}))
            self.assertEqual(fresh_window.findChild(QObject, 'inputChoices').property('count'), 0)
            self.assertEqual(fresh_window.findChild(QObject, 'devicesField').property('text'), retained)
            self.assertIn('unlisted', fresh_window.findChild(QObject, 'retainedInputs').property('text').lower())
            fresh._equipment_reply(0, self.reply(changed))
            self.assertTrue(self.input_choice(fresh_engine, fresh_window, '/dev/input/by-id/keyboard').property('checked'))
            self.assertEqual(load_config(host_path)['devices'], saved['devices'])
            fresh_engine.deleteLater()
            engine.deleteLater()

    def test_save_confirmation_errors_and_new_drafts_are_not_discarded(self):
        app = QGuiApplication.instance() or QGuiApplication([])
        backend = GuiBackend(dbus_only=True)
        backend._connection_state = 'connected'
        backend._service_status = 'running'
        engine = QQmlApplicationEngine()
        engine.rootContext().setContextProperty('topcec', backend)
        engine.load(QUrl.fromLocalFile(str(ROOT / 'cec-tv/topcec.qml')))
        window = engine.rootObjects()[0]
        window.setProperty('settingsDirty', True)
        original = dict(backend.config)
        for payload in ({}, {'accepted': False}, {'accepted': True, 'config': {}}):
            backend._settings_reply(0, self.reply(payload))
            self.assertIn('Could not confirm', backend.actionMessage)
            self.assertTrue(window.property('settingsDirty'))
            self.assertEqual(backend.config, original)
        draft = window.findChild(QObject, 'devicesField')
        signature = QQmlExpression(engine.rootContext(), window, 'JSON.stringify(settingsValues())').evaluate()[0]
        window.setProperty('submittedSettings', signature)
        draft.setProperty('text', '/dev/input/by-id/new-draft')
        backend._settings_reply(0, self.reply({
            'accepted': True, 'config': {'schema_version': 1, **original}}))
        self.assertTrue(window.property('settingsDirty'))
        self.assertEqual(draft.property('text'), '/dev/input/by-id/new-draft')
        engine.deleteLater()

    def test_unsaved_host_defaults_do_not_check_detected_audio_inputs(self):
        app = QGuiApplication.instance() or QGuiApplication([])
        backend = GuiBackend(dbus_only=True)
        backend._service_data = {'service': 'running', 'configuration_saved': False}
        backend._config_reply(0, self.reply({'schema_version': 1, **DEFAULT_CONFIG}))
        engine = QQmlApplicationEngine()
        engine.rootContext().setContextProperty('topcec', backend)
        engine.load(QUrl.fromLocalFile(str(ROOT / 'cec-tv/topcec.qml')))
        window = engine.rootObjects()[0]
        audio_paths = ['/dev/input/audio1', '/dev/input/audio2']
        backend._equipment_reply(0, self.reply({
            'outputs': [{'path': 'TV', 'label': 'TV'}],
            'adapters': [{'path': '/dev/mock-cec', 'label': 'CEC'}],
            'inputs': [{'path': path, 'label': 'Audio'} for path in audio_paths],
            'errors': []}))
        self.assertEqual(window.findChild(QObject, 'devicesField').property('text'), '')
        for path in audio_paths:
            self.assertFalse(self.input_choice(engine, window, path).property('checked'))
        self.assertEqual(window.findChild(QObject, 'outputField').property('currentIndex'), 0)
        self.assertEqual(window.findChild(QObject, 'adapterField').property('currentIndex'), 0)
        self.assertIsNone(window.findChild(QObject, 'saveSettingsButton'))
        self.assertEqual(backend.config['devices'], DEFAULT_CONFIG['devices'])

        # With no equipment detected, defaults stay unselected and unshown.
        keyboard_path = '/dev/input/by-id/keyboard'
        backend._equipment_reply(0, self.reply({
            'outputs': [],
            'adapters': [],
            'inputs': [{'path': keyboard_path, 'label': 'Keyboard'}],
            'errors': []}))
        self.assertEqual(window.findChild(QObject, 'outputField').property('currentIndex'), -1)
        self.assertEqual(window.findChild(QObject, 'adapterField').property('currentIndex'), -1)
        self.assertEqual(window.findChild(QObject, 'outputField').property('displayText'),
                         'No display has been detected')
        self.assertEqual(window.findChild(QObject, 'adapterField').property('displayText'),
                         'No CEC adapter has been detected')
        self.assertFalse(window.findChild(QObject, 'displaySummary').property('visible'))
        self.assertTrue(window.findChild(QObject, 'adapterSummary').property('visible'))
        self.assertEqual(window.findChild(QObject, 'adapterSummary').property('description'),
                         'No CEC adapter detected')
        keyboard = self.input_choice(engine, window, keyboard_path)
        keyboard.setProperty('checked', True)
        QMetaObject.invokeMethod(keyboard, 'toggled')
        app.processEvents()
        window.setProperty('settingsDirty', True)
        with patch.object(backend, 'applySettings') as apply:
            engine.rootContext().setContextProperty('saveWindow', window)
            expression = QQmlExpression(
                engine.rootContext(), window, 'saveWindow.applySettings()')
            expression.evaluate()
            self.assertFalse(expression.hasError(), expression.error().toString())
        values = apply.call_args.args[0]
        self.assertEqual(values['targetOutput'], 'TV')
        self.assertEqual(values['adapter'], '/dev/mock-cec')
        self.assertEqual(values['devices'], keyboard_path)
        engine.deleteLater()

    def test_overview_distinguishes_saved_unknown_missing_detected_and_default_equipment(self):
        app = QGuiApplication.instance() or QGuiApplication([])
        backend = GuiBackend(dbus_only=True)
        backend._service_data = {'service': 'running', 'configuration_saved': True}
        config = {'schema_version': 1, **DEFAULT_CONFIG,
                  'target_output': 'HDMI-A-1', 'cec_port': '/dev/mock-cec',
                  'devices': ['/dev/input/event1', '/dev/input/event2']}
        engine = QQmlApplicationEngine()
        engine.rootContext().setContextProperty('topcec', backend)
        engine.load(QUrl.fromLocalFile(str(ROOT / 'cec-tv/topcec.qml')))
        window = engine.rootObjects()[0]
        display = window.findChild(QObject, 'displaySummary')
        adapter = window.findChild(QObject, 'adapterSummary')
        self.assertEqual(display.property('description'), 'Display detection unavailable')
        self.assertEqual(adapter.property('description'), 'CEC adapter detection unavailable')
        self.assertFalse(display.property('visible'))
        backend._config_reply(0, self.reply(config))
        self.assertEqual(display.property('description'), 'Display detection unavailable')
        self.assertEqual(adapter.property('description'), 'CEC adapter detection unavailable')
        self.assertFalse(display.property('visible'))
        backend._equipment_reply(0, self.reply({
            'outputs': [], 'adapters': [], 'inputs': [], 'errors': []}))
        self.assertEqual(display.property('description'), 'No display detected')
        self.assertEqual(adapter.property('description'), 'No CEC adapter detected')
        self.assertFalse(display.property('visible'))
        self.assertTrue(adapter.property('visible'))
        backend._equipment_reply(0, self.reply({
            'outputs': [{'path': config['target_output'], 'label': 'Detected TV'}],
            'adapters': [{'path': config['cec_port'], 'label': 'Detected adapter'}],
            'inputs': [], 'errors': []}))
        self.assertEqual(display.property('description'), config['target_output'])
        self.assertEqual(adapter.property('description'), config['cec_port'])
        copied, _ = QQmlExpression(engine.rootContext(), window, 'copyPageText()').evaluate()
        self.assertIn(config['target_output'], copied)
        self.assertIn(config['cec_port'], copied)
        self.assertNotIn('Enter display name manually', copied)
        backend._service_data['configuration_saved'] = False
        backend._config_reply(0, self.reply(config))
        self.assertEqual(display.property('description'), config['target_output'])
        self.assertEqual(adapter.property('description'), config['cec_port'])
        self.assertTrue(display.property('visible'))
        self.assertTrue(adapter.property('visible'))
        self.assertIsNotNone(app)
        engine.deleteLater()

    def test_input_choices_are_expanded_and_copyable(self):
        app = QGuiApplication.instance() or QGuiApplication([])
        self.addCleanup(app.clipboard().setText, app.clipboard().text())
        backend = GuiBackend(dbus_only=True)
        backend._connection_state = 'connected'
        backend._service_status = 'running'
        backend.config = {**backend.config, 'devices': ['/dev/input/by-id/0']}
        engine = QQmlApplicationEngine()
        engine.rootContext().setContextProperty('topcec', backend)
        engine.load(QUrl.fromLocalFile(str(ROOT / 'cec-tv/topcec.qml')))
        window = engine.rootObjects()[0]
        window.show()
        inventory = {'outputs': [], 'adapters': [], 'errors': [],
                     'inputs': [{'path': f'/dev/input/by-id/{index}', 'label': f'Device {index}'}
                                for index in range(18)]}
        backend._equipment_reply(0, self.reply(inventory))
        window.setProperty('currentSection', 3)
        app.processEvents()
        self.assertTrue(window.findChild(QObject, 'inputSection').property('visible'))
        self.assertEqual(window.findChild(QObject, 'inputChoices').property('count'), 18)
        paths = window.findChild(QObject, 'devicesField')
        self.assertFalse(paths.property('visible'))
        QMetaObject.invokeMethod(window.findChild(QObject, 'manualPathsToggle'), 'click')
        self.assertTrue(paths.property('visible'))
        self.assertFalse(window.findChild(QObject, 'inputSaveHelp').property('visible'))
        self.assertIsNone(window.findChild(QObject, 'inputChooserToggle'))
        self.assertIsNone(window.findChild(QObject, 'manualInputs'))
        first = self.input_choice(engine, window, '/dev/input/by-id/0')
        last = self.input_choice(engine, window, '/dev/input/by-id/17')
        self.assertTrue(first.property('checked'))
        self.assertTrue(last.property('visible'))
        QMetaObject.invokeMethod(last, 'forceActiveFocus')
        app.processEvents()
        self.assertTrue(last.property('activeFocus'))
        engine.rootContext().setContextProperty(
            'pageForInputScroll', window.findChild(QObject, 'settingsPage'))
        engine.rootContext().setContextProperty('inputChoiceItem', last)
        top = QQmlExpression(
            engine.rootContext(), window,
            'inputChoiceItem.mapToItem(pageForInputScroll.flickable.contentItem, 0, 0).y')
        scroll = QQmlExpression(
            engine.rootContext(), window, 'pageForInputScroll.flickable.contentY')
        viewport = QQmlExpression(
            engine.rootContext(), window, 'pageForInputScroll.flickable.height')
        self.assertGreaterEqual(top.evaluate()[0], scroll.evaluate()[0])
        self.assertLessEqual(
            top.evaluate()[0] + last.property('height'),
            scroll.evaluate()[0] + viewport.evaluate()[0])
        last.setProperty('checked', True)
        QMetaObject.invokeMethod(last, 'toggled')
        self.assertTrue(last.property('checked'))
        QMetaObject.invokeMethod(window.findChild(QObject, 'copySelectedInputs'), 'clicked')
        self.assertEqual(app.clipboard().text(), '/dev/input/by-id/0\n/dev/input/by-id/17')
        engine.deleteLater()

    def test_plasma_navigation_preserves_drafts_and_exposes_recovery_at_compact_width(self):
        app = QGuiApplication.instance() or QGuiApplication([])
        self.addCleanup(app.clipboard().setText, app.clipboard().text())
        backend = GuiBackend(dbus_only=True)
        backend._service_data = {
            'service': 'configuration-only',
            'configuration_saved': True,
            'cec_enabled': False,
            'fail_safe_reason': 'Cannot read input: Permission denied',
            'input_permission_help': {
                'message': 'The host verified that input device access is blocked.',
                'command': 'sudo usermod -aG input -- test-user',
            },
        }
        config = {'schema_version': 1, **DEFAULT_CONFIG,
                  'kde_timeout': False,
                  'target_output': 'HDMI-A-1', 'cec_port': '/dev/mock-cec',
                  'devices': ['/dev/input/event1', '/dev/input/event2']}
        backend._config_reply(0, self.reply(config))
        engine = QQmlApplicationEngine()
        qml_warnings = []
        engine.warnings.connect(lambda warnings: qml_warnings.extend(str(item) for item in warnings))
        engine.rootContext().setContextProperty('topcec', backend)
        engine.load(QUrl.fromLocalFile(str(ROOT / 'cec-tv/topcec.qml')))
        window = engine.rootObjects()[0]
        window.resize(980, 900)
        window.show()
        backend._equipment_reply(0, self.reply({
            'outputs': [{'path': config['target_output'], 'label': 'Detected display'}],
            'adapters': [{'path': config['cec_port'], 'label': 'Detected CEC adapter'}],
            'inputs': [{'path': path, 'label': 'Detected input'}
                       for path in config['devices']],
            'errors': [],
        }))
        app.processEvents()
        QTest.qWait(50)

        drawer = window.findChild(QObject, 'navigationDrawer')
        self.assertFalse(drawer.property('modal'))
        app_header = window.findChild(QQuickItem, 'appIdentityHeader')
        page_header = window.findChild(QQuickItem, 'pageToolbar')
        self.assertAlmostEqual(
            app_header.mapToScene(QPointF(0, 0)).y(),
            page_header.mapToScene(QPointF(0, 0)).y(), delta=1)
        self.assertAlmostEqual(
            app_header.mapToScene(QPointF(0, app_header.height())).y(),
            page_header.mapToScene(QPointF(0, page_header.height())).y(), delta=1)
        engine.rootContext().setContextProperty('testAppHeader', app_header)
        geometry_expression = QQmlExpression(
            engine.rootContext(), window,
            'JSON.stringify(testAppHeader.contentItem.children.map(item => ({'
            'name: item.objectName, visible: item.visible, x: item.x, y: item.y,'
            'width: item.width, height: item.height})))')
        geometry, _ = geometry_expression.evaluate()
        self.assertFalse(geometry_expression.hasError(), geometry_expression.error().toString())
        items = {item['name']: item for item in json.loads(geometry)}
        logo = items['appIdentityLogo']
        name = items['appIdentityName']
        self.assertTrue(logo['visible'])
        self.assertLessEqual(logo['x'] + logo['width'], name['x'])
        self.assertAlmostEqual(
            logo['y'] + logo['height'] / 2,
            name['y'] + name['height'] / 2, delta=1)
        self.assertEqual(window.property('currentSection'), 0)
        self.assertTrue(window.findChild(QObject, 'overviewSummary').property('visible'))
        equipment = window.findChild(QObject, 'equipmentSection')
        standby = window.findChild(QObject, 'standbySection')
        self.assertFalse(equipment.property('visible'))
        self.assertFalse(standby.property('visible'))
        for name, label in (
                ('equipmentNavigation', 'Display'),
                ('standbyNavigation', 'Standby'),
                ('inputNavigation', 'Input')):
            self.assertEqual(window.findChild(QObject, name).property('text'), label)
        for name in ('equipmentFormCard', 'standbyFormCard'):
            card = window.findChild(QObject, name)
            self.assertIsNotNone(card)
        self.assertEqual(window.findChild(QObject, 'serviceStatusLabel').property('text'),
                         'Configuration only,')
        self.assertEqual(
            window.findChild(QObject, 'powerStateLabel').property('text'),
            'No CEC-enabled TV detected')
        self.assertEqual(
            window.findChild(QObject, 'serviceStatusLabel').property('lineCount'), 1)
        power_state = window.findChild(QQuickItem, 'powerStateLabel')
        monitoring = window.findChild(QQuickItem, 'monitoringStatusRow')
        service_status = window.findChild(QQuickItem, 'serviceStatusLabel')
        self.assertAlmostEqual(
            service_status.mapToScene(QPointF(0, 0)).y(),
            power_state.mapToScene(QPointF(0, 0)).y(), delta=1)
        self.assertLess(
            service_status.mapToScene(QPointF(0, 0)).x(),
            power_state.mapToScene(QPointF(0, 0)).x())
        backend._power_state = 'turning_on'
        backend._service_status = 'running'
        backend.changed.emit()
        app.processEvents()
        self.assertEqual(service_status.property('text'), 'Monitoring,')
        self.assertEqual(power_state.property('text'), 'turning on')
        turn_on = window.findChild(QObject, 'tvOnButton')
        self.assertTrue(turn_on.property('enabled'))
        adapter = window.findChild(QObject, 'adapterField')
        backend._set_equipment({
            'outputs': [], 'adapters': [], 'inputs': [], 'errors': [],
        }, 'Equipment refreshed')
        app.processEvents()
        self.assertTrue(adapter.property('acceptable'))
        self.assertFalse(adapter.property('detected'))
        self.assertFalse(turn_on.property('enabled'))
        self.assertEqual(service_status.property('text'), 'Monitoring,')
        self.assertEqual(power_state.property('text'), 'No CEC adapter selected')
        backend._set_equipment(None, 'Equipment detection failed')
        app.processEvents()
        self.assertEqual(power_state.property('text'), 'CEC adapter detection unavailable')
        backend._set_equipment({
            'outputs': [], 'adapters': [
                {'path': config['cec_port'], 'label': 'Detected CEC adapter'}],
            'inputs': [{'path': path, 'label': 'Detected input'}
                       for path in config['devices']],
            'errors': [],
        }, 'Equipment refreshed')
        app.processEvents()
        self.assertEqual(power_state.property('text'), 'No display detected')
        backend._set_equipment({
            'outputs': [{'path': 'DP-1', 'label': 'Other display'}],
            'adapters': [{'path': config['cec_port'], 'label': 'Detected CEC adapter'}],
            'inputs': [{'path': path, 'label': 'Detected input'}
                       for path in config['devices']],
            'errors': [],
        }, 'Equipment refreshed')
        app.processEvents()
        self.assertEqual(power_state.property('text'), 'No display selected')
        backend._set_equipment({
            'outputs': [{'path': config['target_output'], 'label': 'Detected display'}],
            'adapters': [{'path': config['cec_port'], 'label': 'Detected CEC adapter'}],
            'inputs': [{'path': path, 'label': 'Detected input'}
                       for path in config['devices']],
            'errors': [],
        }, 'Equipment refreshed')
        app.processEvents()
        self.assertTrue(turn_on.property('enabled'))
        self.assertEqual(power_state.property('text'), 'turning on')
        backend._power_state = 'unknown'
        backend._service_status = 'configuration-only'
        backend.changed.emit()
        app.processEvents()
        self.assertFalse(window.findChild(QObject, 'diagnosticsWarningBanner').property('visible'))
        self.assertFalse(window.findChild(QObject, 'applyFooter').property('visible'))
        self.assertIsNone(window.findChild(QObject, 'saveSettingsButton'))
        self.assertEqual(window.findChild(QObject, 'settingsSaveStatus').property('text'),
                         'All changes saved.')

        QMetaObject.invokeMethod(window.findChild(QObject, 'configureEquipmentButton'), 'clicked')
        app.processEvents()
        self.assertEqual(window.property('currentSection'), 1)
        self.assertTrue(equipment.property('visible'))
        self.assertFalse(standby.property('visible'))
        self.assertFalse(window.findChild(QObject, 'overviewSummary').property('visible'))
        self.assertTrue(window.findChild(QObject, 'outputField').property('visible'))
        backend._action_message = 'Settings not applied: mock input permission failure'
        backend.changed.emit()
        feedback = window.findChild(QObject, 'actionFeedback')
        self.assertTrue(feedback.property('visible'))
        self.assertIn('permission failure', feedback.property('text'))
        backend._action_message = ''
        backend.changed.emit()

        manual_output = window.findChild(QObject, 'manualOutput')
        self.assertTrue(manual_output.property('visible'))
        self.assertTrue(window.findChild(QObject, 'manualAdapter').property('visible'))
        manual_output.setProperty('checked', True)
        output = window.findChild(QObject, 'outputField')
        output.setProperty('editText', 'DRAFT-DISPLAY')
        window.setProperty('settingsDirty', True)
        QMetaObject.invokeMethod(window.findChild(QObject, 'standbyNavigation'), 'trigger')
        app.processEvents()
        self.assertEqual(window.property('currentSection'), 2)
        self.assertFalse(equipment.property('visible'))
        self.assertTrue(standby.property('visible'))
        QMetaObject.invokeMethod(window.findChild(QObject, 'inputNavigation'), 'trigger')
        app.processEvents()
        self.assertEqual(window.property('currentSection'), 3)
        self.assertTrue(window.findChild(QObject, 'inputSection').property('visible'))
        self.assertFalse(window.findChild(QObject, 'devicesField').property('visible'))

        QMetaObject.invokeMethod(window.findChild(QObject, 'standbyNavigation'), 'trigger')
        app.processEvents()
        timeout = window.findChild(QObject, 'timeoutMode')
        minutes = window.findChild(QObject, 'timeoutMinutes')
        self.assertTrue(minutes.property('visible'))
        backend._status_poll_reply(0, self.reply({
            'plasma_timeout_read': True,
            'plasma_timeout_seconds': 600,
        }))
        timeout.setProperty('currentIndex', 0)
        self.assertEqual(timeout.property('currentText'),
                         'Follow Plasma power setting (10 minutes)')
        backend._status_poll_reply(0, self.reply({
            'plasma_timeout_read': True,
            'plasma_timeout_seconds': 300,
        }))
        self.assertEqual(timeout.property('currentText'),
                         'Follow Plasma power setting (5 minutes)')
        backend._status_poll_reply(0, self.reply({
            'plasma_timeout_read': False,
            'plasma_timeout_seconds': None,
            'plasma_timeout_fallback': True,
        }))
        self.assertEqual(timeout.property('currentText'),
                         'Follow Plasma power setting (unavailable; using 5 minutes)')
        self.assertFalse(minutes.property('visible'))
        timeout.setProperty('currentIndex', 1)
        self.assertTrue(minutes.property('visible'))

        self.assertFalse(window.findChild(QObject, 'simulateOnButton').property('visible'))
        self.assertFalse(window.findChild(QObject, 'simulateOffButton').property('visible'))
        QMetaObject.invokeMethod(window.findChild(QObject, 'firefoxToggle'), 'click')
        self.assertTrue(window.findChild(QObject, 'labelsField').property('visible'))

        self.assertIn('Saving changes...', window.findChild(QObject, 'settingsSaveStatus').property('text'))

        window.resize(430, 760)
        app.processEvents()
        QTest.qWait(50)
        self.assertTrue(drawer.property('modal'))
        self.assertTrue(window.findChild(QObject, 'navigationButton').property('visible'))
        self.assertGreaterEqual(window.width(), window.property('minimumWidth'))
        caption = window.findChild(QQuickItem, 'muteLabelsCaption')
        editor = window.findChild(QQuickItem, 'labelsField')
        self.assertGreaterEqual(editor.y(), caption.y() + caption.height() - 1)
        self.assertLessEqual(editor.x() + editor.width(), editor.parentItem().width() + 1)
        QMetaObject.invokeMethod(window.findChild(QObject, 'overviewNavigation'), 'trigger')
        app.processEvents()
        QMetaObject.invokeMethod(window.findChild(QObject, 'diagnosticsNavigation'), 'trigger')
        app.processEvents()
        QTest.qWait(80)
        self.assertEqual(window.property('currentSection'), 4)
        self.assertTrue(window.findChild(QObject, 'diagnosticsPanel').property('visible'))
        warning = window.findChild(QObject, 'diagnosticsWarningBanner')
        self.assertTrue(warning.property('visible'))
        self.assertIn('Cannot read input: Permission denied', warning.property('text'))
        self.assertIn('Monitoring is inactive.', warning.property('text'))
        simulate_on = window.findChild(QObject, 'simulateOnButton')
        simulate_off = window.findChild(QObject, 'simulateOffButton')
        self.assertTrue(simulate_on.property('visible'))
        self.assertTrue(simulate_off.property('visible'))
        self.assertEqual(simulate_off.property('text'), 'Simulate standby')
        QMetaObject.invokeMethod(simulate_on, 'click')
        self.assertEqual(backend.actionMessage, '')
        self.assertEqual(window.findChild(QObject, 'powerStateLabel').property('text'),
                         'On (simulated)')
        self.assertIn('Pending action: on (simulated)', backend.diagnostics)
        QMetaObject.invokeMethod(simulate_off, 'click')
        self.assertEqual(backend.actionMessage, '')
        self.assertEqual(window.findChild(QObject, 'powerStateLabel').property('text'),
                         'Off (simulated)')
        self.assertIn('Pending action: standby (simulated)', backend.diagnostics)
        self.assertFalse(window.findChild(QObject, 'actionDiagnostics').property('visible'))
        diagnostics = window.findChild(QObject, 'backendDiagnostics')
        self.assertIn('Scan:', diagnostics.property('text'))
        self.assertNotIn('Service:', diagnostics.property('text'))
        self.assertFalse(diagnostics.property('visible'))
        standby_diagnostics = window.findChild(QObject, 'standbyDiagnostics')
        diagnostics_warning = window.findChild(QObject, 'diagnosticsWarningBanner')
        self.assertTrue(diagnostics_warning.property('visible'))
        self.assertEqual(diagnostics_warning.property('text'), warning.property('text'))
        self.assertFalse(standby_diagnostics.property('visible'))
        backend._standby_reason = backend._connection_message
        backend.changed.emit()
        app.processEvents()
        self.assertFalse(standby_diagnostics.property('visible'))
        self.assertTrue(window.findChild(QObject, 'inputPermissionHelp').property('visible'))
        self.assertEqual(window.findChild(QObject, 'inputPermissionCommand').property('text'),
                         backend.inputPermissionCommand)
        engine.rootContext().setContextProperty('pageForScrollTest',
                                                window.findChild(QObject, 'settingsPage'))
        scroll_expression = QQmlExpression(
            engine.rootContext(), window, 'pageForScrollTest.flickable.contentY')
        self.assertEqual(scroll_expression.evaluate()[0], 0)
        self.assertEqual(output.property('editText'), 'DRAFT-DISPLAY')
        self.assertTrue(window.property('settingsDirty'))
        QMetaObject.invokeMethod(window.findChild(QObject, 'equipmentNavigation'), 'trigger')
        app.processEvents()
        self.assertEqual(window.property('currentSection'), 1)
        self.assertEqual(output.property('editText'), 'DRAFT-DISPLAY')
        copy = window.findChild(QObject, 'copyPageButton')
        copy_accessible = QAccessible.queryAccessibleInterface(copy)
        self.assertEqual(copy_accessible.text(QAccessible.Text.Name), 'Copy page text')
        QMetaObject.invokeMethod(copy, 'clicked')
        self.assertIn('Config only', app.clipboard().text())
        self.assertIn('Saving changes...', app.clipboard().text())
        self.assertEqual(qml_warnings, [])
        engine.deleteLater()

    def test_navigation_toggle_and_sidebar_recover_after_resizing(self):
        app = QGuiApplication.instance() or QGuiApplication([])
        backend = GuiBackend(dbus_only=True)
        engine = QQmlApplicationEngine()
        warnings = []
        engine.warnings.connect(lambda items: warnings.extend(str(item) for item in items))
        engine.rootContext().setContextProperty('topcec', backend)
        engine.load(QUrl.fromLocalFile(str(ROOT / 'cec-tv/topcec.qml')))
        window = engine.rootObjects()[0]
        window.resize(980, 800)
        window.show()
        drawer = window.findChild(QObject, 'navigationDrawer')
        button = window.findChild(QQuickItem, 'navigationButton')
        close_button = window.findChild(QQuickItem, 'drawerNavigationButton')
        engine.rootContext().setContextProperty('testDrawer', drawer)
        handle_visible = QQmlExpression(engine.rootContext(), window, 'testDrawer.handle.visible')

        def wait_until(predicate):
            for _ in range(100):
                if predicate():
                    return True
                QTest.qWait(20)
            return predicate()

        def click(item):
            self.assertTrue(item.isVisible())
            point = item.mapToScene(QPointF(item.width() / 2, item.height() / 2)).toPoint()
            QTest.mouseClick(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
            QTest.qWait(350)

        self.assertTrue(wait_until(lambda: drawer.property('opened')))
        self.assertTrue(button.isVisible())
        self.assertEqual(QAccessible.queryAccessibleInterface(button).text(QAccessible.Text.Name),
                         'Hide navigation')
        click(button)
        self.assertFalse(drawer.property('visible'))
        self.assertEqual(QAccessible.queryAccessibleInterface(button).text(QAccessible.Text.Name),
                         'Show navigation')
        click(button)
        self.assertTrue(drawer.property('opened'))

        for _ in range(2):
            window.resize(430, 760)
            QTest.qWait(350)
            self.assertTrue(drawer.property('modal'))
            self.assertFalse(drawer.property('visible'))
            click(button)
            self.assertTrue(drawer.property('opened'))
            self.assertFalse(handle_visible.evaluate()[0])
            click(close_button)
            self.assertFalse(drawer.property('visible'))
            window.resize(980, 800)
            QTest.qWait(350)
            self.assertFalse(drawer.property('modal'))
            self.assertTrue(drawer.property('opened'))
            self.assertTrue(button.isVisible())

        for width in (430, 980, 430, 980):
            window.resize(width, 800)
            QTest.qWait(20)
        QTest.qWait(350)
        self.assertTrue(drawer.property('opened'))

        window.resize(430, 760)
        QTest.qWait(350)
        click(button)
        window.resize(980, 800)
        QTest.qWait(350)
        self.assertTrue(drawer.property('opened'))

        self.assertFalse(handle_visible.hasError(), handle_visible.error().toString())
        self.assertEqual(warnings, [])
        window.close()
        engine.deleteLater()
        app.processEvents()

    def test_diagnostics_disclosures_and_full_report_at_wide_and_compact_sizes(self):
        app = QGuiApplication.instance() or QGuiApplication([])
        self.addCleanup(app.clipboard().setText, app.clipboard().text())
        with patch.object(topcec_gui, 'available_outputs', return_value=[]), \
                patch.object(topcec_gui, 'available_adapters', return_value=[]):
            backend = GuiBackend(dbus_only=False)
        backend._connection_state = 'connected'
        backend._service_status = 'running'
        backend._service_data = {
            'scan_status': 'Ready',
            'input_permission_help': {
                'path': '/dev/input/by-id/keyboard', 'message': 'Input access was denied.',
            },
        }
        backend._set_equipment({
            'outputs': [{'path': 'HDMI-A-1', 'label': 'HDMI-A-1'}],
            'adapters': [{'path': '/dev/cec', 'label': 'CEC adapter'}],
            'inputs': [{'path': '/dev/input/event1', 'label': 'Keyboard',
                        'aliases': ['/dev/input/by-id/keyboard']},
                       {'path': '/dev/input/event2', 'label': 'Controller'}],
            'errors': [],
        }, 'Equipment refreshed')
        engine = QQmlApplicationEngine()
        engine.rootContext().setContextProperty('topcec', backend)
        engine.load(QUrl.fromLocalFile(str(ROOT / 'cec-tv/topcec.qml')))
        window = engine.rootObjects()[0]
        window.setProperty('currentSection', 4)
        window.show()
        details = window.findChild(QQuickItem, 'backendDiagnostics')
        devices = window.findChild(QQuickItem, 'diagnosticInputList')
        details_toggle = window.findChild(QObject, 'diagnosticDetailsToggle')
        inputs_toggle = window.findChild(QObject, 'diagnosticInputsToggle')
        copy = window.findChild(QObject, 'copyPageButton')
        for width, height in ((1200, 900), (380, 760)):
            window.resize(width, height)
            QTest.qWait(100)
            self.assertFalse(details.property('visible'))
            self.assertFalse(devices.property('visible'))
            self.assertEqual(copy.property('text'), 'Copy diagnostics')
            QMetaObject.invokeMethod(copy, 'click')
            report = app.clipboard().text()
            for expected in ('Host service: Connected', 'Monitoring: Active', 'TV power:',
                             'Pending action: none', 'Keyboard · /dev/input/event1 · Access blocked',
                             'Controller · /dev/input/event2', 'Input access was denied.'):
                self.assertIn(expected, report)
            QMetaObject.invokeMethod(details_toggle, 'click')
            QMetaObject.invokeMethod(inputs_toggle, 'click')
            QTest.qWait(50)
            self.assertTrue(details.property('visible'))
            self.assertTrue(details.property('readOnly'))
            self.assertTrue(devices.property('visible'))
            self.assertIn('Keyboard · Access blocked', devices.property('text'))
            self.assertNotIn('Controller · Access blocked', devices.property('text'))
            self.assertLessEqual(details.x() + details.width(), details.parentItem().width() + 1)
            QMetaObject.invokeMethod(details_toggle, 'click')
            QMetaObject.invokeMethod(inputs_toggle, 'click')
        window.setProperty('currentSection', 3)
        self.assertIn('Access blocked', self.input_choice(engine, window, '/dev/input/event1').property('text'))
        self.assertNotIn('Access blocked', self.input_choice(engine, window, '/dev/input/event2').property('text'))
        window.setProperty('currentSection', 4)
        self.assertFalse(window.findChild(QObject, 'connectionDiagnostics').property('visible'))
        for name, value in (('diagnosticsDisplays', 'HDMI-A-1'),
                            ('diagnosticsAdapters', 'CEC adapter · /dev/cec')):
            self.assertIn(value, window.findChild(QObject, name).property('description'))
        self.assertFalse(window.findChild(QObject, 'equipmentDiagnostics').property('visible'))
        backend._set_equipment({'outputs': [], 'adapters': [], 'inputs': [], 'errors': []}, '')
        self.assertIn('None detected', window.findChild(QObject, 'diagnosticsDisplays').property('description'))
        backend._set_equipment(None, 'Device detection failed')
        self.assertIn('Detection unavailable', window.findChild(QObject, 'diagnosticsInputs').property('description'))
        self.assertTrue(window.findChild(QObject, 'equipmentDiagnostics').property('visible'))
        backend._connection_state = 'unavailable'
        backend._connection_message = 'Service unavailable'
        backend.changed.emit()
        self.assertTrue(window.findChild(QObject, 'connectionDiagnostics').property('visible'))
        engine.deleteLater()

    def test_qml_accessibility_roles_names_and_keyboard_focus_remain_available(self):
        app = QGuiApplication.instance() or QGuiApplication([])
        was_active = QAccessible.isActive()
        QAccessible.setActive(True)
        self.addCleanup(QAccessible.setActive, was_active)
        backend = GuiBackend(dbus_only=True)
        backend._connection_state = 'connected'
        backend._service_status = 'configuration-only'
        engine = QQmlApplicationEngine()
        engine.rootContext().setContextProperty('topcec', backend)
        engine.load(QUrl.fromLocalFile(str(ROOT / 'cec-tv/topcec.qml')))
        window = engine.rootObjects()[0]
        window.setProperty('currentSection', 3)
        window.show()
        app.processEvents()
        for name, role, label in (
                ('outputField', QAccessible.Role.ComboBox, 'Display detection unavailable'),
                ('devicesField', QAccessible.Role.EditableText, 'Input device paths (one per line)')):
            with self.subTest(control=name):
                interface = QAccessible.queryAccessibleInterface(window.findChild(QObject, name))
                self.assertIsNotNone(interface)
                self.assertEqual(interface.role(), role)
                self.assertEqual(interface.text(QAccessible.Text.Name), label)
        self.assertIsNone(window.findChild(QObject, 'saveSettingsButton'))
        QMetaObject.invokeMethod(window.findChild(QObject, 'manualPathsToggle'), 'click')
        control = window.findChild(QQuickItem, 'devicesField')
        QMetaObject.invokeMethod(control, 'forceActiveFocus')
        self.assertTrue(control.property('activeFocus'))
        self.assertTrue(control.property('visible'))
        engine.deleteLater()

    def test_gui_launchers_preserve_accessibility_and_diagnostics(self):
        sources = '\n'.join((ROOT / path).read_text() for path in (
            'cec-tv/topcec_gui.py', 'packaging/flatpak/topcec-gui',
            'net.local.topcec.yml', 'packaging/flatpak/pyside.yml',
        ))
        for disabled in ('QT_ACCESSIBILITY=0', 'QT_LINUX_ACCESSIBILITY_ALWAYS_ON=0',
                         'NO_AT_BRIDGE=1', 'qt.accessibility.atspi=false',
                         'qt.accessibility.atspi.warning=false'):
            self.assertNotIn(disabled, sources)
        self.assertNotIn('qInstallMessageHandler', sources)

    def test_detected_and_manual_devices_are_selected_and_editable(self):
        app = QGuiApplication.instance() or QGuiApplication([])
        backend = GuiBackend(dbus_only=True)
        backend._connection_state = 'connected'
        backend._service_status = 'configuration-only'
        backend._config_source = 'saved'
        backend.config = {**backend.config, 'target_output': 'OLD-DISPLAY',
                          'cec_port': '/dev/old-CEC',
                          'devices': ['/dev/input/old']}
        original = dict(backend.config)
        engine = QQmlApplicationEngine()
        engine.rootContext().setContextProperty('topcec', backend)
        engine.load(QUrl.fromLocalFile(str(ROOT / 'cec-tv/topcec.qml')))
        window = engine.rootObjects()[0]
        output = window.findChild(QObject, 'outputField')
        adapter = window.findChild(QObject, 'adapterField')
        inputs = window.findChild(QObject, 'inputChoices')
        paths = window.findChild(QObject, 'devicesField')
        self.assertIsNone(window.findChild(QObject, 'saveSettingsButton'))
        engine.rootContext().setContextProperty('choices', inputs)

        def inventory(outputs, adapters, devices, errors=None):
            backend._equipment_reply(0, SimpleNamespace(
                type=lambda: topcec_gui.QDBusMessage.MessageType.ReplyMessage,
                arguments=lambda: [json.dumps({
                    'outputs': outputs, 'adapters': adapters, 'inputs': devices,
                    'errors': errors or [],
                })]))
            app.processEvents()

        def select(field):
            field.setProperty('currentIndex', 0)
            engine.rootContext().setContextProperty('selection', field)
            expression = QQmlExpression(engine.rootContext(), window, 'selection.activated(0)')
            expression.evaluate()
            self.assertFalse(expression.hasError(), expression.error().toString())

        detected_outputs = [{'path': 'DP-NEW', 'label': 'Connected display'}]
        detected_adapters = [{'path': '/dev/real-CEC', 'label': 'Connected adapter'}]
        detected_inputs = [{'path': '/dev/input/by-id/real', 'label': 'Connected keyboard'}]
        inventory(detected_outputs, detected_adapters, detected_inputs)
        for field in (output, adapter):
            self.assertEqual(field.property('count'), 1)
            self.assertEqual(field.property('currentIndex'), -1)
            self.assertFalse(field.property('editable'))
            self.assertIn('Choose a detected', field.property('displayText'))
        device = QQmlExpression(
            engine.rootContext(), window, 'choices.itemAt(0)').evaluate()[0]
        self.assertFalse(device.property('checked'))
        self.assertEqual(paths.property('text'), '\n'.join(original['devices']))
        self.assertEqual(backend.config, original)

        select(output)
        select(adapter)
        device.setProperty('checked', True)
        QMetaObject.invokeMethod(device, 'toggled')
        # Choosing actual hardware must not silently erase retained paths.
        self.assertIn(original['devices'][0], paths.property('text'))
        QMetaObject.invokeMethod(window.findChild(QObject, 'removeUndetectedInputs'), 'clicked')
        self.assertEqual(paths.property('text'), '/dev/input/by-id/real')
        with patch.object(backend, 'applySettings') as apply:
            engine.rootContext().setContextProperty('settingsWindow', window)
            expression = QQmlExpression(
                engine.rootContext(), window, 'settingsWindow.applySettings()')
            expression.evaluate()
            self.assertFalse(expression.hasError(), expression.error().toString())
        values = apply.call_args.args[0]
        self.assertEqual(values['targetOutput'], 'DP-NEW')
        self.assertEqual(values['adapter'], '/dev/real-CEC')
        self.assertEqual(values['devices'], '/dev/input/by-id/real')
        self.assertEqual(backend.config, original)

        inventory([], [], [])
        self.assertEqual(output.property('currentIndex'), -1)
        self.assertEqual(adapter.property('currentIndex'), -1)
        self.assertEqual(inputs.property('count'), 0)
        self.assertEqual(paths.property('text'), '/dev/input/by-id/real')
        self.assertEqual(output.property('valueToSave'), 'DP-NEW')
        self.assertIsNone(window.findChild(QObject, 'saveSettingsButton'))
        self.assertTrue(window.property('settingsDirty'))
        inventory([{'path': 'OTHER-DISPLAY', 'label': 'Another display'}],
                  [{'path': '/dev/other-CEC', 'label': 'Another adapter'}],
                  [{'path': '/dev/input/other', 'label': 'Another keyboard'}])
        self.assertEqual(output.property('currentIndex'), -1)
        self.assertEqual(adapter.property('currentIndex'), -1)
        self.assertEqual(output.property('valueToSave'), 'DP-NEW')
        other = QQmlExpression(
            engine.rootContext(), window, 'choices.itemAt(0)').evaluate()[0]
        self.assertFalse(other.property('checked'))
        inventory([], [], [], ['Display discovery unavailable'])
        self.assertFalse(window.findChild(QObject, 'retainedOutput').property('visible'))
        inventory(detected_outputs, detected_adapters, detected_inputs)
        self.assertEqual(output.property('currentIndex'), 0)
        self.assertEqual(adapter.property('currentIndex'), 0)
        self.assertTrue(window.property('equipmentReady'))

        # Display and adapter drafts remain separate from detected selections.
        window.findChild(QObject, 'manualOutput').setProperty('checked', True)
        output.setProperty('editText', 'MANUAL-DRAFT')
        inventory([], [], [])
        self.assertFalse(window.property('equipmentReady'))
        window.findChild(QObject, 'manualAdapter').setProperty('checked', True)
        self.assertTrue(output.property('editable'))
        self.assertEqual(output.property('editText'), 'MANUAL-DRAFT')
        self.assertEqual(adapter.property('editText'), '/dev/real-CEC')
        self.assertTrue(window.property('equipmentReady'))
        self.assertEqual(backend.config, original)
        window.findChild(QObject, 'manualOutput').setProperty('checked', False)
        self.assertFalse(window.property('equipmentReady'))
        engine.deleteLater()

    def test_selected_axes_have_independent_drafts_and_manual_paths_scroll(self):
        app = QGuiApplication.instance() or QGuiApplication([])
        backend = GuiBackend(dbus_only=True)
        backend._connection_state = 'connected'
        backend._service_status = 'running'
        backend._config_source = 'saved'
        backend.config = {
            **backend.config, 'target_output': 'DP-1', 'cec_port': '/dev/mock-cec',
            'devices': ['/dev/input/wheel'],
            'device_axis_deadzones': {'/dev/input/wheel': {'0': 12}}}
        backend._set_equipment({
            'outputs': [{'path': 'DP-1', 'label': 'Display'}],
            'adapters': [{'path': '/dev/mock-cec', 'label': 'Adapter'}],
            'errors': [],
            'inputs': [
                {'path': '/dev/input/wheel', 'label': 'Wheel',
                 'axes': [{'code': 0, 'name': 'ABS_X'}, {'code': 5, 'name': 'ABS_RZ'}]},
                {'path': '/dev/input/other', 'label': 'Other',
                 'axes': [{'code': 1, 'name': 'ABS_Y'}]},
            ],
        }, '')
        engine = QQmlApplicationEngine()
        engine.rootContext().setContextProperty('topcec', backend)
        engine.load(QUrl.fromLocalFile(str(ROOT / 'cec-tv/topcec.qml')))
        window = engine.rootObjects()[0]
        window.setProperty('currentSection', 3)
        QMetaObject.invokeMethod(window.findChild(QObject, 'manualPathsToggle'), 'click')
        paths = window.findChild(QObject, 'devicesField')
        paths.setProperty('text', '\n'.join(['/dev/input/wheel'] * 30))
        app.processEvents()
        scroll = window.findChild(QObject, 'devicesScroll')
        self.assertGreater(scroll.property('contentHeight'), scroll.property('height'))
        rows = window.findChild(QObject, 'axisChoices')
        self.assertEqual(rows.property('count'), 2)
        engine.rootContext().setContextProperty('axisRows', rows)
        first = QQmlExpression(engine.rootContext(), window, 'axisRows.itemAt(0)').evaluate()[0]
        second = QQmlExpression(engine.rootContext(), window, 'axisRows.itemAt(1)').evaluate()[0]
        self.assertEqual(first.property('value'), 12)
        self.assertEqual(second.property('value'), 0)
        second.setProperty('value', 0)
        QMetaObject.invokeMethod(second, 'valueModified')
        expression = QQmlExpression(engine.rootContext(), window, 'JSON.stringify(settingsValues().deviceAxisDeadzones)')
        draft = json.loads(expression.evaluate()[0])
        self.assertEqual(draft, {'/dev/input/wheel': {'0': 12, '5': 0}})
        self.assertTrue(window.property('settingsDirty'))
        with patch.object(backend, '_service_interface', return_value=Mock(isValid=lambda: True)), \
                patch.object(backend, '_async_call') as call:
            QQmlExpression(engine.rootContext(), window, 'topcec.applySettings(settingsValues())').evaluate()
            self.assertTrue(call.called, backend.actionMessage)
            sent = json.loads(call.call_args.args[3])
            self.assertEqual(sent['device_axis_deadzones'], draft)
        paths.setProperty('text', '/dev/input/other')
        app.processEvents()
        self.assertEqual(rows.property('count'), 1)
        self.assertEqual(json.loads(expression.evaluate()[0]), draft)
        engine.deleteLater()

    def test_missing_required_capabilities_show_update_without_guessing_from_transport_errors(self):
        app = QGuiApplication.instance() or QGuiApplication([])
        methods = ('GetStatus', 'GetConfig', 'GetEquipment', 'ApplySettings', 'RequestPower')
        for method in methods:
            for error_name in ('org.freedesktop.DBus.Error.UnknownMethod',
                               'org.freedesktop.DBus.Error.NoReply',
                               'org.freedesktop.DBus.Error.AccessDenied'):
                with self.subTest(method=method, error=error_name):
                    backend = GuiBackend(dbus_only=True)
                    backend._connection_state = 'connected'
                    backend._service_status = 'running'
                    original = dict(backend.config)
                    reply = topcec_gui.QDBusMessage.createError(error_name, 'failed')
                    if method == 'GetStatus':
                        backend._status_reply(0, Mock(), reply)
                    elif method == 'GetConfig':
                        backend._config_reply(0, reply)
                    elif method == 'GetEquipment':
                        with patch.object(topcec_gui.sys, 'stderr'):
                            backend._equipment_reply(0, reply)
                    elif method == 'ApplySettings':
                        backend._settings_reply(0, reply)
                    else:
                        backend._power_reply(0, 'on', reply)
                    self.assertEqual(backend.config, original)
                    missing = error_name.endswith('.UnknownMethod')
                    self.assertEqual(bool(backend.equipmentRecoveryCommands), missing)
                    self.assertEqual(bool(backend.compatibilityMessage), missing)
                    if missing:
                        self.assertIn(method, backend.compatibilityMessage)
                        # The shared update panel remains accessible even if status
                        # or configuration capabilities force the setup view.
                        engine = QQmlApplicationEngine()
                        engine.rootContext().setContextProperty('topcec', backend)
                        engine.load(QUrl.fromLocalFile(str(ROOT / 'cec-tv/topcec.qml')))
                        window = engine.rootObjects()[0]
                        copy = window.findChild(QObject, 'copyEquipmentRecoveryCommands')
                        self.assertTrue(copy.property('visible'))
                        engine.deleteLater()
                        backend._capability_error(method, topcec_gui.QDBusMessage())
                        self.assertEqual(backend.equipmentRecoveryCommands, '')

    def test_old_backend_and_discovery_failure_mean_unknown_not_missing_hardware(self):
        app = QGuiApplication.instance() or QGuiApplication([])
        self.addCleanup(app.clipboard().setText, app.clipboard().text())
        backend = GuiBackend(dbus_only=True)
        backend._connection_state = 'connected'
        backend._service_status = 'running'
        backend._config_source = 'saved'
        backend.config = {**backend.config, 'target_output': 'OLD-DISPLAY',
                          'cec_port': '/dev/old-CEC',
                          'devices': ['/dev/input/old']}
        engine = QQmlApplicationEngine()
        engine.rootContext().setContextProperty('topcec', backend)
        engine.load(QUrl.fromLocalFile(str(ROOT / 'cec-tv/topcec.qml')))
        window = engine.rootObjects()[0]
        output = window.findChild(QObject, 'outputField')
        adapter = window.findChild(QObject, 'adapterField')
        devices = window.findChild(QObject, 'devicesField')
        repeater = window.findChild(QObject, 'inputChoices')
        engine.rootContext().setContextProperty('choices', repeater)
        configured = dict(backend.config)
        window.findChild(QObject, 'manualOutput').setProperty('checked', True)
        window.findChild(QObject, 'manualAdapter').setProperty('checked', True)
        output.setProperty('editText', 'DRAFT-OUTPUT')
        adapter.setProperty('editText', '/dev/manual-CEC')
        window.setProperty('settingsDirty', True)
        original_devices = devices.property('text')
        traceback = (
            'Traceback (most recent call last):\n'
            'File "/usr/lib64/python3.15/site-packages/dbus/service.py", line 659\n'
            'dbus.exceptions.UnknownMethodException: Unknown method: GetEquipment '
            'is not a valid method of interface net.local.CecActivity')
        backend._equipment_reply(0, topcec_gui.QDBusMessage.createError(
            'org.freedesktop.DBus.Error.UnknownMethod', traceback))
        app.processEvents()
        self.assertIn('running host backend does not support', backend.equipmentMessage)
        self.assertNotIn('Traceback', backend.equipmentMessage)
        self.assertNotIn('/usr/lib64', backend.equipmentMessage)
        self.assertIn('availability is unknown', backend.equipmentMessage)
        self.assertFalse(backend.equipmentAvailabilityKnown)
        self.assertEqual(output.property('currentIndex'), -1)
        self.assertEqual(adapter.property('currentIndex'), -1)
        self.assertIn('availability unknown',
                      window.findChild(QObject, 'retainedOutput').property('text'))
        self.assertIn('availability unknown',
                      window.findChild(QObject, 'retainedAdapter').property('text'))
        self.assertEqual(repeater.property('count'), 0)
        self.assertIn('availability unknown', window.findChild(QObject, 'retainedInputs').property('text'))
        commands = window.findChild(QObject, 'equipmentRecoveryCommands')
        copy = window.findChild(QObject, 'copyEquipmentRecoveryCommands')
        self.assertTrue(commands.property('visible'))
        self.assertTrue(commands.property('selectByMouse'))
        self.assertTrue(commands.property('readOnly'))
        self.assertEqual(commands.property('text'), topcec_gui.HOST_UPDATE_COMMAND)
        self.assertEqual(len(commands.property('text').splitlines()), 1)
        instructions = window.findChild(QObject, 'hostUpdateInstructions').property('text')
        self.assertIn('from any directory', instructions)
        self.assertIn('full absolute path', instructions)
        self.assertIn('without quotes', instructions)
        self.assertIn('read -r -p', commands.property('text'))
        self.assertNotIn('.copilot', commands.property('text'))
        with patch.object(topcec_gui.subprocess, 'run',
                          side_effect=AssertionError('copy must not execute commands')):
            QMetaObject.invokeMethod(copy, 'clicked')
        self.assertEqual(app.clipboard().text(), commands.property('text'))

        def inventory(errors):
            backend._equipment_reply(0, SimpleNamespace(
                type=lambda: topcec_gui.QDBusMessage.MessageType.ReplyMessage,
                arguments=lambda: [json.dumps({
                    'outputs': [], 'adapters': [], 'inputs': [], 'errors': errors,
                })]))
            app.processEvents()

        inventory([])
        self.assertTrue(backend.equipmentAvailabilityKnown)
        self.assertIn('not detected',
                      window.findChild(QObject, 'retainedOutput').property('text'))
        self.assertFalse(copy.property('visible'))
        self.assertEqual(backend.equipmentRecoveryCommands, '')
        inventory(['Display discovery: compositor not responding'])
        self.assertFalse(backend.equipmentAvailabilityKnown)
        self.assertIn('availability unknown',
                      window.findChild(QObject, 'retainedOutput').property('text'))
        self.assertIn('availability unknown',
                      window.findChild(QObject, 'retainedAdapter').property('text'))
        self.assertEqual(repeater.property('count'), 0)
        self.assertIn('compositor not responding', backend.equipmentMessage)
        self.assertNotIn('An empty list means no equipment', backend.equipmentMessage)
        with patch.object(topcec_gui.sys, 'stderr') as diagnostic_log:
            backend._equipment_reply(0, topcec_gui.QDBusMessage.createError(
                'org.freedesktop.DBus.Error.NoReply', 'Traceback: unexpected internal error'))
        self.assertIn('unexpected internal error', ''.join(
            call.args[0] for call in diagnostic_log.write.call_args_list))
        self.assertNotIn('Traceback', backend.equipmentMessage)
        self.assertIn('NoReply', backend.equipmentMessage)
        self.assertFalse(backend.equipmentAvailabilityKnown)
        self.assertEqual(output.property('editText'), 'DRAFT-OUTPUT')
        self.assertEqual(adapter.property('editText'), '/dev/manual-CEC')
        self.assertEqual(devices.property('text'), original_devices)
        self.assertEqual(backend.config, configured)
        self.assertTrue(window.property('settingsDirty'))
        self.assertTrue(backend.settingsEnabled)
        self.assertEqual(backend.connectionState, 'connected')
        engine.deleteLater()

    def test_detected_equipment_choices_preserve_manual_config_and_drafts(self):
        app = QGuiApplication.instance() or QGuiApplication([])
        backend = GuiBackend(dbus_only=True)
        backend._connection_state = 'connected'
        backend._service_status = 'configuration-only'
        backend._config_source = 'saved'
        backend.config = {**backend.config, 'target_output': 'OLD-DISPLAY',
                          'cec_port': '/dev/old-CEC',
                          'devices': ['/dev/input/old']}
        original_config = dict(backend.config)
        backend._service_data = {'configuration_saved': True}
        backend._config_reply(0, self.reply({'schema_version': 1, **original_config}))
        original_config = dict(backend.config)
        engine = QQmlApplicationEngine()
        engine.rootContext().setContextProperty('topcec', backend)
        engine.load(QUrl.fromLocalFile(str(ROOT / 'cec-tv/topcec.qml')))
        window = engine.rootObjects()[0]
        configured_output = window.findChild(QObject, 'outputField')
        configured_adapter = window.findChild(QObject, 'adapterField')
        configured_inputs = window.findChild(QObject, 'devicesField')
        self.assertIsNone(window.findChild(QObject, 'detectedOutputField'))
        inventory = {
            'outputs': [{'path': 'DP-NEW', 'label': 'DP-NEW'}],
            'adapters': [{'path': '/dev/serial/by-id/real-CEC', 'label': 'Real CEC'}],
            'inputs': [{'path': '/dev/input/by-id/real-kbd', 'label': 'Real keyboard'}],
            'errors': [],
        }

        def update_inventory(data):
            backend._equipment_reply(0, SimpleNamespace(
                type=lambda: topcec_gui.QDBusMessage.MessageType.ReplyMessage,
                arguments=lambda: [json.dumps(data)]))
            app.processEvents()

        update_inventory(inventory)
        for field in (configured_output, configured_adapter):
            self.assertEqual(field.property('count'), 1)
            self.assertEqual(field.property('currentIndex'), -1)
        self.assertEqual(configured_output.property('editText'), original_config['target_output'])
        self.assertEqual(configured_inputs.property('text'), '\n'.join(original_config['devices']))
        self.assertEqual(backend.config, original_config)
        engine.rootContext().setContextProperty('detectedChoice', configured_output)
        action = QQmlExpression(engine.rootContext(), window, 'detectedChoice.activated(0)')
        action.evaluate()
        self.assertFalse(action.hasError(), action.error().toString())
        self.assertEqual(configured_output.property('editText'), 'DP-NEW')
        self.assertTrue(window.property('settingsDirty'))
        engine.rootContext().setContextProperty('detectedChoice', configured_adapter)
        QQmlExpression(engine.rootContext(), window, 'detectedChoice.activated(0)').evaluate()
        QQmlExpression(engine.rootContext(), window,
                       'setInputDeviceSelected({path: "/dev/input/by-id/real-kbd"}, true)').evaluate()
        self.assertEqual(configured_adapter.property('editText'), '/dev/serial/by-id/real-CEC')
        self.assertIn('/dev/input/by-id/real-kbd', configured_inputs.property('text'))
        self.assertIn(original_config['devices'][0], configured_inputs.property('text'))
        update_inventory({'outputs': [], 'adapters': [], 'inputs': [], 'errors': []})
        self.assertEqual(configured_output.property('editText'), 'DP-NEW')
        self.assertEqual(configured_adapter.property('editText'), '/dev/serial/by-id/real-CEC')
        self.assertEqual(configured_output.property('count'), 0)
        self.assertEqual(configured_output.property('currentIndex'), -1)
        self.assertEqual(configured_output.property('displayText'), 'No display has been detected')
        self.assertFalse(window.findChild(QObject, 'retainedOutput').property('visible'))
        self.assertIn('/dev/input/by-id/real-kbd', configured_inputs.property('text'))
        # Replug updates the same configuration controls without losing drafts.
        update_inventory(inventory)
        self.assertEqual(configured_output.property('editText'), 'DP-NEW')
        self.assertEqual(configured_output.property('currentText'), 'DP-NEW')
        self.assertEqual(configured_adapter.property('currentText'), 'Real CEC')
        self.assertTrue(window.property('settingsDirty'))
        self.assertEqual(configured_output.property('count'), 1)
        self.assertEqual(backend.config, original_config)
        backend._equipment_reply(0, SimpleNamespace(
            type=lambda: topcec_gui.QDBusMessage.MessageType.ErrorMessage,
            errorName=lambda: 'org.freedesktop.DBus.Error.UnknownMethod',
            errorMessage=lambda: 'Unknown method GetEquipment'))
        self.assertIn('Update the host backend', backend.equipmentMessage)
        self.assertTrue(backend.settingsEnabled)
        self.assertEqual(backend.detectedOutputs, [])
        self.assertEqual(configured_output.property('editText'), 'DP-NEW')
        engine.deleteLater()

    def test_hotplug_refresh_updates_configuration_controls_through_dbus(self):
        app = QGuiApplication.instance() or QGuiApplication([])
        bus = Mock()
        bus.isConnected.return_value = True
        interface = Mock()
        interface.isValid.return_value = True
        watchers = []

        def watcher(pending, parent):
            result = self.FakeWatcher(pending, parent)
            watchers.append(result)
            return result

        def complete(data):
            watchers[-1].complete(SimpleNamespace(
                type=lambda: topcec_gui.QDBusMessage.MessageType.ReplyMessage,
                arguments=lambda: [json.dumps(data)]))

        inventory = {
            'outputs': [{'path': 'DP-NEW', 'label': 'DP-NEW'}],
            'adapters': [{'path': '/dev/serial/by-id/real-CEC', 'label': 'Real CEC'}],
            'inputs': [{'path': '/dev/input/by-id/real-kbd', 'label': 'Keyboard',
                        'aliases': ['/dev/input/event10']}],
            'errors': [],
        }
        with patch.object(topcec_gui.QDBusConnection, 'sessionBus', return_value=bus), \
                patch.object(topcec_gui, 'QDBusPendingCallWatcher', side_effect=watcher), \
                patch.object(GuiBackend, '_service_interface', return_value=interface):
            backend = GuiBackend(dbus_only=True)
            engine = QQmlApplicationEngine()
            engine.rootContext().setContextProperty('topcec', backend)
            engine.load(QUrl.fromLocalFile(str(ROOT / 'cec-tv/topcec.qml')))
            window = engine.rootObjects()[0]
            output = window.findChild(QObject, 'outputField')
            adapter = window.findChild(QObject, 'adapterField')
            devices = window.findChild(QObject, 'devicesField')
            repeater = window.findChild(QObject, 'inputChoices')
            engine.rootContext().setContextProperty('choices', repeater)
            for detected in (inventory, {'outputs': [], 'adapters': [], 'inputs': [], 'errors': []},
                             inventory):
                backend.refresh()
                complete({'service': 'running', 'cec_enabled': True})
                complete({
                    'schema_version': 1, **DEFAULT_CONFIG,
                    'target_output': 'DP-NEW', 'cec_port': '/dev/serial/by-id/real-CEC',
                    'devices': ['/dev/input/event10'],
                })
                self.assertTrue(backend._refresh_in_flight)
                complete(detected)
                app.processEvents()
                self.assertFalse(backend._refresh_in_flight)
                if detected['outputs']:
                    self.assertEqual(output.property('count'), 1)
                    self.assertEqual(adapter.property('count'), 1)
                    # The detected stable alias represents configured event10,
                    # not a duplicate or a false unavailable device.
                    self.assertEqual(repeater.property('count'), 1)
                    existing = QQmlExpression(
                        engine.rootContext(), window, 'choices.itemAt(0)').evaluate()[0]
                    self.assertIsNotNone(existing)
                    self.assertTrue(existing.property('checked'))
                    self.assertNotIn('unavailable', existing.property('text'))
                else:
                    self.assertEqual(output.property('count'), 0)
                    self.assertEqual(adapter.property('count'), 0)
                    self.assertEqual(repeater.property('count'), 0)
                    self.assertIn('unavailable', window.findChild(QObject, 'retainedInputs').property('text'))
                self.assertEqual(devices.property('text'), '/dev/input/event10')
                self.assertFalse(window.property('settingsDirty'))
            self.assertGreaterEqual(interface.asyncCallWithArgumentList.call_count, 9)
            existing.setProperty('checked', False)
            QMetaObject.invokeMethod(existing, 'toggled')
            self.assertNotIn('/dev/input/event10', devices.property('text'))
            self.assertTrue(backend.hasInputDraft())
            app.processEvents()
            available = QQmlExpression(
                engine.rootContext(), window, 'choices.itemAt(0)').evaluate()[0]
            self.assertFalse(available.property('checked'))
            available.setProperty('checked', True)
            QMetaObject.invokeMethod(available, 'toggled')
            self.assertIn('/dev/input/by-id/real-kbd', devices.property('text'))
            self.assertEqual(bus.connect.call_count, 1)
            engine.deleteLater()

    def test_inventory_errors_and_stale_replies_preserve_connection(self):
        backend = GuiBackend(dbus_only=True)
        backend._connection_state = 'connected'
        backend._service_status = 'running'
        config = dict(backend.config)
        for data in ({}, {'outputs': [42], 'adapters': [], 'inputs': [], 'errors': []},
                     {'outputs': [], 'adapters': [], 'inputs': [], 'errors': 'invalid'}):
            with self.subTest(data=data):
                backend._equipment_reply(0, SimpleNamespace(
                    type=lambda: topcec_gui.QDBusMessage.MessageType.ReplyMessage,
                    arguments=lambda: [json.dumps(data)]))
                self.assertIn('Invalid host equipment response', backend.equipmentMessage)
                self.assertFalse(backend.equipmentAvailabilityKnown)
                self.assertEqual(backend.config, config)
                self.assertTrue(backend.settingsEnabled)
        inventory = {
            'outputs': [{'path': 'DP-2', 'label': 'DP-2'}],
            'adapters': [], 'inputs': [], 'errors': [],
        }
        reply = SimpleNamespace(
            type=lambda: topcec_gui.QDBusMessage.MessageType.ReplyMessage,
            arguments=lambda: [json.dumps(inventory)])
        spy = QSignalSpy(backend.equipmentChanged)
        backend._equipment_reply(0, reply)
        backend._equipment_reply(0, reply)
        self.assertEqual(spy.count(), 1)
        self.assertEqual(backend.detectedOutputs, inventory['outputs'])
        backend._refresh_generation += 1
        backend._set_unavailable()
        backend._equipment_reply(0, reply)
        self.assertEqual(backend.detectedOutputs, [])
        self.assertIn('disconnected', backend.equipmentMessage)

    def test_legacy_backend_input_error_shows_guidance_without_unverified_command(self):
        app = QGuiApplication.instance() or QGuiApplication([])
        backend = GuiBackend(dbus_only=True)
        backend._connection_state = 'connected'
        backend._service_status = 'configuration-only'
        backend._service_data = {
            'service': 'configuration-only',
            'fail_safe_reason': "Cannot read input: [Errno 13] Permission denied: '/dev/input/event10'",
        }
        engine = QQmlApplicationEngine()
        engine.rootContext().setContextProperty('topcec', backend)
        engine.load(QUrl.fromLocalFile(str(ROOT / 'cec-tv/topcec.qml')))
        window = engine.rootObjects()[0]
        window.setProperty('currentSection', 4)
        self.assertTrue(window.findChild(QObject, 'inputPermissionHelp').property('visible'))
        self.assertIn('Updating only the Flatpak', backend.inputPermissionMessage)
        self.assertIn('bash packaging/install-user.sh', backend.inputPermissionMessage)
        self.assertEqual(backend.inputPermissionCommand, '')
        self.assertFalse(window.findChild(QObject, 'copyInputPermissionCommand').property('visible'))
        self.assertIsNone(window.findChild(QObject, 'saveSettingsButton'))
        for missing_help in (None, {}):
            backend._service_data['input_permission_help'] = missing_help
            backend.changed.emit()
            self.assertTrue(backend.inputPermissionMessage)
            self.assertEqual(backend.inputPermissionCommand, '')
        backend._service_data['fail_safe_reason'] = 'Waiting for Firefox snapshot'
        backend.changed.emit()
        self.assertFalse(window.findChild(QObject, 'inputPermissionHelp').property('visible'))
        self.assertIsNotNone(app)
        engine.deleteLater()

    def test_host_verified_input_permission_command_is_displayed_and_copied(self):
        app = QGuiApplication.instance() or QGuiApplication([])
        self.addCleanup(app.clipboard().setText, app.clipboard().text())
        backend = GuiBackend(dbus_only=True)
        backend._connection_state = 'connected'
        backend._service_status = 'configuration-only'
        backend._service_data = {
            'input_permission_help': {
                'message': 'Host verified input group access. Log out and back in.',
                'command': 'sudo usermod -aG input -- test-user',
            },
        }
        engine = QQmlApplicationEngine()
        engine.rootContext().setContextProperty('topcec', backend)
        engine.load(QUrl.fromLocalFile(str(ROOT / 'cec-tv/topcec.qml')))
        window = engine.rootObjects()[0]
        help_item = window.findChild(QObject, 'inputPermissionHelp')
        command = window.findChild(QObject, 'inputPermissionCommand')
        copy = window.findChild(QObject, 'copyInputPermissionCommand')
        window.setProperty('currentSection', 4)
        self.assertTrue(help_item.property('visible'))
        self.assertEqual(command.property('text'), backend.inputPermissionCommand)
        self.assertTrue(command.property('selectByMouse'))
        self.assertTrue(command.property('readOnly'))
        with patch.object(topcec_gui.subprocess, 'run',
                          side_effect=AssertionError('must not execute command')):
            QMetaObject.invokeMethod(copy, 'clicked')
        self.assertEqual(app.clipboard().text(), 'sudo usermod -aG input -- test-user')
        self.assertTrue(backend.settingsEnabled)
        backend._service_data['input_permission_help']['command'] = ''
        backend.changed.emit()
        self.assertFalse(copy.property('visible'))
        self.assertFalse(command.property('visible'))
        self.assertTrue(help_item.property('visible'))
        backend._service_data = {}
        backend.changed.emit()
        self.assertFalse(help_item.property('visible'))
        engine.deleteLater()

    def test_retry_monitoring_reuses_saved_settings_and_preserves_drafts(self):
        app = QGuiApplication.instance() or QGuiApplication([])
        backend = GuiBackend(dbus_only=True)
        backend._config_reply(0, self.reply({'schema_version': 1, **DEFAULT_CONFIG}))
        backend._service_status = 'configuration-only'
        backend._config_source = 'saved'
        draft = '/dev/input/by-id/draft-keyboard'
        backend.rememberInputDraft(draft)
        backend._failed_input_draft = draft
        engine = QQmlApplicationEngine()
        engine.rootContext().setContextProperty('topcec', backend)
        engine.load(QUrl.fromLocalFile(str(ROOT / 'cec-tv/topcec.qml')))
        window = engine.rootObjects()[0]
        window.setProperty('currentSection', 4)
        window.findChild(QObject, 'timeoutMinutes').setProperty('value', 23)
        window.setProperty('settingsDirty', True)
        app.processEvents()

        retry = window.findChild(QObject, 'retryMonitoringButton')
        self.assertTrue(retry.property('visible'))
        self.assertTrue(retry.property('enabled'))
        requests = []
        saved = QSignalSpy(backend.settingsSaved)
        with patch.object(backend, '_service_interface', return_value=Mock()), \
                patch.object(backend, '_async_call', side_effect=lambda _, method, callback, *args:
                             requests.append((method, callback, args))), \
                patch.object(backend, 'refresh'):
            QMetaObject.invokeMethod(retry, 'click')
            backend.retryMonitoring()
            self.assertFalse(retry.property('enabled'))
            self.assertEqual(len(requests), 1)
            method, callback, args = requests.pop()
            self.assertEqual(method, 'ApplySettings')
            config = json.loads(args[0])
            self.assertNotIn('device_axis_deadzones', config)
            self.assertEqual(validate_config(config), DEFAULT_CONFIG)
            callback(topcec_gui.QDBusMessage.createError('org.example.Error', 'Access denied'))
            self.assertIn('Access denied', backend.actionMessage)
            self.assertTrue(retry.property('enabled'))
            QMetaObject.invokeMethod(retry, 'click')
            method, callback, args = requests.pop()
            callback(self.reply({'accepted': True, 'applied_live': True, 'config': config}))

        self.assertEqual(saved.count(), 0)
        self.assertEqual(backend.deviceList(), draft)
        self.assertEqual(backend._failed_input_draft, draft)
        self.assertTrue(window.property('settingsDirty'))
        self.assertEqual(window.findChild(QObject, 'timeoutMinutes').property('value'), 23)
        backend._service_status = 'running'
        backend.changed.emit()
        self.assertFalse(retry.property('visible'))
        engine.deleteLater()

    def test_gui_readonly_text_can_be_selected_and_copied(self):
        app = QGuiApplication.instance() or QGuiApplication([])
        self.addCleanup(app.clipboard().setText, app.clipboard().text())
        backend = GuiBackend(dbus_only=True)
        engine = QQmlApplicationEngine()
        engine.rootContext().setContextProperty('topcec', backend)
        engine.load(QUrl.fromLocalFile(str(ROOT / 'cec-tv/topcec.qml')))
        window = engine.rootObjects()[0]
        for name in ('setupHeading', 'setupExplanation', 'setupCommands',
                     'setupDiagnostics', 'backendDiagnostics'):
            with self.subTest(name=name):
                field = window.findChild(QObject, name)
                self.assertTrue(field.property('selectByMouse'))
                self.assertTrue(field.property('readOnly'))
                QMetaObject.invokeMethod(field, 'selectAll')
                self.assertEqual(field.property('selectedText'), field.property('text'))
                QMetaObject.invokeMethod(field, 'copy')
                self.assertEqual(app.clipboard().text(), field.property('text'))
        window.setProperty('currentSection', 3)
        for name in ('devicesField',):
            field = window.findChild(QObject, name)
            self.assertTrue(field.property('selectByMouse'))
            self.assertFalse(field.property('readOnly'))
        engine.deleteLater()

    def test_caption_copy_preserves_button_clicks_and_page_copy_covers_disabled_text(self):
        app = QGuiApplication.instance() or QGuiApplication([])
        self.addCleanup(app.clipboard().setText, app.clipboard().text())
        backend = GuiBackend(dbus_only=True)
        engine = QQmlApplicationEngine()
        engine.rootContext().setContextProperty('topcec', backend)
        engine.load(QUrl.fromLocalFile(str(ROOT / 'cec-tv/topcec.qml')))
        window = engine.rootObjects()[0]
        window.resize(900, 1400)
        window.show()
        app.processEvents()
        button = window.findChild(QQuickItem, 'repositoryButton')
        point = button.mapToScene(QPointF(button.width() / 2, button.height() / 2)).toPoint()
        with patch.object(backend, 'retryConnection'):
            QTest.mouseClick(window, Qt.RightButton, Qt.NoModifier, point)
            app.processEvents()
        menu = window.findChild(QObject, 'captionCopyMenu')
        self.assertEqual(menu.property('caption'), 'Open topCEC repository')
        self.assertTrue(menu.property('visible'))
        action = window.findChild(QObject, 'copyCaptionAction')
        QMetaObject.invokeMethod(action, 'clicked')
        self.assertEqual(app.clipboard().text(), 'Open topCEC repository')
        QMetaObject.invokeMethod(menu, 'close')
        QTest.qWait(250)
        backend._connection_state = 'unavailable'
        backend.changed.emit()
        app.processEvents()
        retry = window.findChild(QQuickItem, 'retryConnectionButton')
        clicked = QSignalSpy(retry, SIGNAL('clicked()'))
        self.assertTrue(clicked.isValid())
        interface = Mock()
        interface.isValid.return_value = False
        point = retry.mapToScene(QPointF(retry.width() / 2, retry.height() / 2)).toPoint()
        with patch.object(backend, '_service_interface', return_value=interface):
            QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point)
        self.assertEqual(clicked.count(), 1)

        page = window.findChild(QObject, 'pageContent')
        engine.rootContext().setContextProperty('testPageContent', page)
        expression = QQmlExpression(
            engine.rootContext(), window, 'displayedText(testPageContent)')
        text, undefined = expression.evaluate()
        self.assertFalse(expression.hasError(), expression.error().toString())
        self.assertFalse(undefined)
        self.assertIn('topCEC Backend Not Available', text)
        self.assertIn('Open topCEC repository', text)
        self.assertIn('Retry Connection', text)
        self.assertNotIn('TV power control', text)
        page_action = window.findChild(QObject, 'copyPageAction')
        QMetaObject.invokeMethod(page_action, 'trigger')
        self.assertIn(text, app.clipboard().text())
        backend._connection_state = 'connected'
        backend._service_status = 'starting'
        backend.changed.emit()
        app.processEvents()
        text, undefined = expression.evaluate()
        page_copy = QQmlExpression(engine.rootContext(), window, 'copyPageText()')
        copied, undefined = page_copy.evaluate()
        self.assertFalse(page_copy.hasError(), page_copy.error().toString())
        self.assertNotIn('Save and apply', copied)
        window.setProperty('settingsDirty', True)
        self.assertNotIn('Save and apply', page_copy.evaluate()[0])
        self.assertNotIn('topCEC Backend Not Available', text)
        self.assertIsNone(window.findChild(QObject, 'saveSettingsButton'))
        self.assertIn('unlisted', window.findChild(QObject, 'retainedInputs').property('text').lower())
        window.setProperty('currentSection', 3)
        app.processEvents()
        text, _ = expression.evaluate()
        for path in backend.config['devices']:
            self.assertIn(path + ' (availability unknown)', text)
        engine.deleteLater()

    class FakeWatcher:
        def __init__(self, pending, parent):
            self.pending = pending
            self.callback = None
            self.result = None
            self.finished = SimpleNamespace(connect=self._connect)

        def _connect(self, callback):
            self.callback = callback

        def reply(self):
            return self.result

        def complete(self, reply):
            self.result = reply
            self.callback(self)

    class FakeProcess:
        def __init__(self):
            self.finished_callback = None
            self.output = b''
            self.error_output = b''
            self.code = 0
            self.finished = SimpleNamespace(connect=self._connect_finished)
            self.errorOccurred = SimpleNamespace(connect=Mock())

        def _connect_finished(self, callback):
            self.finished_callback = callback

        def start(self, program, arguments):
            self.program = program
            self.arguments = arguments

        def readAllStandardOutput(self):
            return self.output

        def readAllStandardError(self):
            return self.error_output

        def exitCode(self):
            return self.code

        def complete(self, output='', error='', code=0):
            self.output = output.encode()
            self.error_output = error.encode()
            self.code = code
            self.finished_callback(code, 0)

    def test_original_application_icon_renders_at_small_and_large_sizes(self):
        app = QGuiApplication.instance() or QGuiApplication([])
        icon = topcec_gui.application_icon()
        self.assertFalse(icon.isNull())
        for size in (16, 32, 128):
            image = icon.pixmap(size, size).toImage()
            self.assertFalse(image.isNull())
            self.assertGreater(image.pixelColor(size // 2, size // 2).alpha(), 0)
            white_rows = [
                y for y in range(size)
                if all(channel > 180 for channel in (
                    image.pixelColor(size // 2, y).red(),
                    image.pixelColor(size // 2, y).green(),
                    image.pixelColor(size // 2, y).blue()))
            ]
            self.assertTrue(white_rows)
            lower_frame = round(82 * size / 128)
            self.assertGreaterEqual(lower_frame - max(white_rows) - 1, 1)
        self.assertIsNotNone(app)

    def test_installed_icon_is_used_without_a_theme(self):
        from PySide6.QtGui import QIcon

        app = QGuiApplication.instance() or QGuiApplication([])
        path = str(ROOT / 'cec-tv/net.local.topcec.svg')
        with patch.object(QStandardPaths, 'locate', return_value=path) as locate, \
                patch.object(QIcon, 'fromTheme', side_effect=lambda name, fallback: fallback):
            self.assertFalse(topcec_gui.application_icon().pixmap(32, 32).isNull())
        self.assertIn('icons/hicolor/scalable/apps/net.local.topcec.svg',
                      locate.call_args.args)
        self.assertIsNotNone(app)

    def test_installed_header_logo_renders_without_an_adjacent_svg(self):
        from PySide6.QtGui import QIcon

        app = QGuiApplication.instance() or QGuiApplication([])
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            qml_path = directory / 'lib/topcec/topcec.qml'
            qml_path.parent.mkdir(parents=True)
            qml_path.write_bytes((ROOT / 'cec-tv/topcec.qml').read_bytes())
            icon_path = directory / 'share/icons/hicolor/scalable/apps/net.local.topcec.svg'
            icon_path.parent.mkdir(parents=True)
            icon_path.write_bytes((ROOT / 'cec-tv/net.local.topcec.svg').read_bytes())
            with patch.object(topcec_gui, '__file__', str(qml_path.with_suffix('.py'))), \
                    patch.object(QStandardPaths, 'locate', return_value=str(icon_path)), \
                    patch.object(QIcon, 'fromTheme', side_effect=lambda name, fallback: fallback):
                backend = GuiBackend(dbus_only=True)
                engine = QQmlApplicationEngine()
                engine.rootContext().setContextProperty('topcec', backend)
                engine.load(QUrl.fromLocalFile(str(qml_path)))
                self.assertTrue(engine.rootObjects())
                window = engine.rootObjects()[0]
                window.show()
                QTest.qWait(50)
                header = window.findChild(QQuickItem, 'appIdentityHeader')
                engine.rootContext().setContextProperty('testAppHeader', header)
                expression = QQmlExpression(
                    engine.rootContext(), window,
                    'testAppHeader.contentItem.children.find('
                    'item => item.objectName === "appIdentityLogo").valid')
                valid, _ = expression.evaluate()
                self.assertFalse(expression.hasError(), expression.error().toString())
                self.assertTrue(valid, 'The installed header must load an actual logo image')
                window.close()
                engine.deleteLater()
                app.processEvents()

    def setUp(self):
        preferences = tempfile.TemporaryDirectory()
        self.addCleanup(preferences.cleanup)
        config_path = patch.object(topcec_gui, 'default_config_path',
                                   return_value=Path(preferences.name) / 'config.json')
        config_path.start()
        self.addCleanup(config_path.stop)
        # Form tests control save acknowledgements explicitly.
        autosave = patch.object(GuiBackend, '_save_pending_inputs')
        autosave.start()
        self.autosave_patch = autosave
        self.addCleanup(autosave.stop)

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

    def test_older_unversioned_save_reply_receives_new_defaults(self):
        backend = GuiBackend(dbus_only=True)
        old_config = {key: value for key, value in DEFAULT_CONFIG.items()
                      if key not in ('consider_input_devices', 'mouse_output', 'mouse_outputs',
                                     'firefox_audio_blocks_standby', 'idle_inhibition_apps')}
        with patch.object(backend, 'refresh'):
            backend._settings_reply(0, self.reply({'accepted': True, 'config': old_config}))
        self.assertTrue(backend.config['consider_input_devices'])
        self.assertIsNone(backend.config['mouse_output'])
        self.assertIsNone(backend.config['mouse_outputs'])
        self.assertIn('saved', backend.actionMessage.lower())

    def test_standby_input_toggle_and_mouse_display_selection(self):
        app = QGuiApplication.instance() or QGuiApplication([])
        backend = GuiBackend(dbus_only=True)
        backend._connection_state = 'connected'
        backend._service_status = 'running'
        backend._config_source = 'saved'
        backend.config = {
            **DEFAULT_CONFIG, 'target_output': 'HDMI-A-2', 'cec_port': '/dev/mock-cec',
            'devices': []}
        backend._service_data = {
            'installed_apps': [{'id': 'firefox.desktop', 'name': 'Mozilla Firefox'}],
            'observed_apps': [], 'active_inhibitor_apps': [],
        }
        backend._set_equipment({
            'outputs': [{'path': 'DP-1', 'label': 'Monitor'},
                        {'path': 'HDMI-A-2', 'label': 'TV'}],
            'adapters': [{'path': '/dev/mock-cec', 'label': 'Adapter'}],
            'inputs': [], 'errors': [],
        }, '')
        engine = QQmlApplicationEngine()
        engine.rootContext().setContextProperty('topcec', backend)
        engine.load(QUrl.fromLocalFile(str(ROOT / 'cec-tv/topcec.qml')))
        window = engine.rootObjects()[0]
        window.show()
        window.setProperty('currentSection', 2)
        app.processEvents()
        checkbox = window.findChild(QObject, 'considerInputDevices')
        firefox_row = self.app_row(engine, window, 0)
        firefox_audio = firefox_row.findChild(QObject, 'firefoxAudio')
        selector = window.findChild(QObject, 'mouseDisplayChoices')
        self.assertTrue(checkbox.property('checked'))
        self.assertFalse(firefox_audio.property('checked'))
        QMetaObject.invokeMethod(firefox_audio, 'click')
        self.assertEqual(selector.property('count'), 2)
        legacy_values = json.loads(QQmlExpression(
            engine.rootContext(), window, 'JSON.stringify(settingsValues())').evaluate()[0])
        self.assertIsNone(legacy_values['mouseOutputs'])
        legacy_config = config_from_settings(
            backend.config, {**legacy_values, 'targetOutput': 'DP-1'})
        self.assertIsNone(legacy_config['mouse_outputs'])
        self.assertEqual(legacy_config['target_output'], 'DP-1')
        self.assertTrue(window.property('equipmentReady'))
        QMetaObject.invokeMethod(checkbox, 'click')
        self.assertTrue(window.property('settingsDirty'))
        self.assertTrue(window.property('equipmentReady'))
        engine.rootContext().setContextProperty('mouseSelector', selector)
        def display(index):
            return QQmlExpression(engine.rootContext(), window,
                                  f'mouseSelector.itemAt({index})').evaluate()[0]
        self.assertFalse(display(0).property('checked'))
        self.assertTrue(display(1).property('checked'))
        QMetaObject.invokeMethod(display(0), 'click')
        values = json.loads(QQmlExpression(
            engine.rootContext(), window, 'JSON.stringify(settingsValues())').evaluate()[0])
        config = config_from_settings(backend.config, values)
        self.assertFalse(config['consider_input_devices'])
        self.assertTrue(config['firefox_audio_blocks_standby'])
        self.assertEqual(config['mouse_outputs'], ['HDMI-A-2', 'DP-1'])
        backend._set_equipment({'outputs': [], 'adapters': [], 'inputs': [], 'errors': []}, '')
        app.processEvents()
        self.assertEqual(selector.property('count'), 2)
        self.assertIn('not detected', display(0).property('text'))
        QMetaObject.invokeMethod(display(0), 'click')
        QMetaObject.invokeMethod(display(0), 'click')
        values = json.loads(QQmlExpression(
            engine.rootContext(), window, 'JSON.stringify(settingsValues())').evaluate()[0])
        self.assertEqual(config_from_settings(backend.config, values)['mouse_outputs'], [])
        engine.deleteLater()

    def test_kde_and_disabled_timeout_modes(self):
        kde = config_from_settings(
            self.config, {**self.values, 'timeoutMode': 'kde'})
        self.assertTrue(kde['kde_timeout'])
        disabled = config_from_settings(
            self.config, {**self.values, 'timeoutMode': 'never'})
        self.assertIsNone(disabled['timeout_seconds'])
        self.assertFalse(disabled['kde_timeout'])

    def test_installed_apps_can_be_searched_selected_and_retained(self):
        app = QGuiApplication.instance() or QGuiApplication([])
        backend = GuiBackend(dbus_only=True)
        backend._connection_state = 'connected'
        backend._service_status = 'running'
        backend._config_source = 'saved'
        backend.config = {**DEFAULT_CONFIG, 'devices': [],
                          'idle_inhibition_apps': ['removed.desktop']}
        backend._service_data = {
            'installed_apps': [{'id': 'player.desktop', 'name': 'Video Player'},
                               {'id': 'editor.desktop', 'name': 'Editor',
                                'launcher_group': 'editor.desktop'},
                               {'id': 'editor-menu.desktop', 'name': 'Editor',
                                'launcher_group': 'editor.desktop'},
                               {'id': 'editor-handler.desktop', 'name': 'Editor',
                                'menu_hidden': True},
                               {'id': 'archived.desktop', 'name': 'Archived',
                                'menu_hidden': True}],
            'observed_apps': [{'id': 'player.desktop', 'name': 'Video Player'},
                              {'id': 'archived.desktop', 'name': 'Archived'}],
            'active_inhibitor_apps': [{'id': 'player.desktop', 'name': 'Video Player'}],
            'installed_apps_error': None,
            'inhibitions_error': None,
            'blocking_apps': [{'app': 'Player', 'reason': 'Playing',
                               'locationUnknown': True}],
        }
        engine = QQmlApplicationEngine()
        engine.rootContext().setContextProperty('topcec', backend)
        engine.load(QUrl.fromLocalFile(str(ROOT / 'cec-tv/topcec.qml')))
        window = engine.rootObjects()[0]
        window.show()
        window.setProperty('currentSection', 2)
        app.processEvents()
        self.assertEqual(window.findChild(QObject, 'canBlockStandbyHeading').property('text'),
                         'Can block screen standby')
        repeater = window.findChild(QObject, 'installedAppsScroll')
        self.assertEqual(repeater.property('count'), 3)
        engine.rootContext().setContextProperty('appChoicesRepeater', repeater)
        def item(index):
            return QQmlExpression(engine.rootContext(), window,
                                  f'appChoicesRepeater.itemAtIndex({index})').evaluate()[0]
        player = item(0)
        self.assertEqual(player.objectName(), 'appRow:player.desktop')
        removed = item(2)
        self.assertEqual(removed.objectName(), 'appRow:removed.desktop')
        allow = player.findChild(QObject, 'idleApp:player.desktop')
        self.assertEqual(allow.property('text'), 'Allow standby')
        self.assertTrue(allow.property('checked'))
        removed_allow = removed.findChild(QObject, 'idleApp:removed.desktop')
        self.assertFalse(removed_allow.property('checked'))
        QMetaObject.invokeMethod(removed_allow, 'click')
        self.assertTrue(removed_allow.property('checked'))
        self.assertEqual(json.loads(QQmlExpression(
            engine.rootContext(), window, 'JSON.stringify(settingsValues())').evaluate()[0])
            ['idleInhibitionApps'], [])
        QMetaObject.invokeMethod(removed_allow, 'click')
        self.assertEqual(player.findChild(QObject, 'forceApp:player.desktop').property('text'),
                         'Force block standby')
        QMetaObject.invokeMethod(allow, 'click')
        self.assertFalse(allow.property('checked'))
        QMetaObject.invokeMethod(player.findChild(QObject, 'forceApp:player.desktop'), 'click')
        values = json.loads(QQmlExpression(
            engine.rootContext(), window, 'JSON.stringify(settingsValues())').evaluate()[0])
        self.assertEqual(values['idleInhibitionApps'], ['removed.desktop', 'player.desktop'])
        self.assertEqual(config_from_settings(backend.config, values)['idle_inhibition_apps'],
                         values['idleInhibitionApps'])
        self.assertEqual(config_from_settings(backend.config, values)['force_inhibition_apps'],
                         ['player.desktop'])
        search = window.findChild(QObject, 'appSearch')
        self.assertIn('currently', search.property('placeholderText'))
        search.setProperty('text', 'archived')
        app.processEvents()
        self.assertEqual(repeater.property('count'), 0)
        search.setProperty('text', 'player')
        app.processEvents()
        self.assertEqual(repeater.property('count'), 1)
        self.assertEqual(item(0).objectName(), 'appRow:player.desktop')
        backend._service_data['active_inhibitor_apps'] = []
        backend.changed.emit()
        app.processEvents()
        self.assertEqual(repeater.property('count'), 0)
        backend._service_data['active_inhibitor_apps'] = [{'id': 'player.desktop'}]
        backend.changed.emit()
        QMetaObject.invokeMethod(window.findChild(QObject, 'showAllApps'), 'click')
        self.assertIn('all installed', search.property('placeholderText'))
        search.setProperty('text', 'editor')
        app.processEvents()
        self.assertEqual(repeater.property('count'), 1)
        search.setProperty('text', 'editor-menu.desktop')
        app.processEvents()
        self.assertEqual(repeater.property('count'), 1)
        editor = item(0)
        self.assertEqual(editor.objectName(), 'appRow:editor.desktop')
        QMetaObject.invokeMethod(editor.findChild(QObject, 'forceApp:editor.desktop'), 'click')
        window.findChild(QObject, 'appSearch').setProperty('text', '')
        QMetaObject.invokeMethod(window.findChild(QObject, 'showAllApps'), 'click')
        app.processEvents()
        self.assertEqual(repeater.property('count'), 4)
        values = json.loads(QQmlExpression(
            engine.rootContext(), window, 'JSON.stringify(settingsValues())').evaluate()[0])
        self.assertEqual(set(values['forceInhibitionApps']),
                         {'player.desktop', 'editor.desktop', 'editor-menu.desktop'})
        search.setProperty('text', '')
        editor = next(item(index) for index in range(repeater.property('count'))
                      if item(index).objectName().startswith('appRow:editor'))
        QMetaObject.invokeMethod(editor.findChild(QObject, 'forceApp:editor.desktop'), 'click')
        values = json.loads(QQmlExpression(
            engine.rootContext(), window, 'JSON.stringify(settingsValues())').evaluate()[0])
        self.assertEqual(values['forceInhibitionApps'], ['player.desktop'])
        window.findChild(QObject, 'autoSaveTimer').stop()
        engine.deleteLater()

    def test_firefox_detection_failure_is_not_reported_as_no_blockers(self):
        app = QGuiApplication.instance() or QGuiApplication([])
        backend = GuiBackend(dbus_only=True)
        backend._connection_state = 'connected'
        backend._service_status = 'running'
        backend.config['firefox_audio_blocks_standby'] = True
        backend._service_data = {
            'firefox_audio_error': 'AT-SPI did not respond within 5 seconds',
            'blocking_apps': [], 'inhibitions_error': None,
        }
        engine = QQmlApplicationEngine()
        engine.rootContext().setContextProperty('topcec', backend)
        engine.load(QUrl.fromLocalFile(str(ROOT / 'cec-tv/topcec.qml')))
        window = engine.rootObjects()[0]
        window.show()
        window.setProperty('currentSection', 2)
        app.processEvents()
        message = window.findChild(QObject, 'firefoxAudioStatus')
        empty = window.findChild(QObject, 'noBlockingApps')
        self.assertTrue(message.property('visible'))
        self.assertNotIn('AT-SPI', message.property('text'))
        self.assertIn('standby is blocked', message.property('text'))
        self.assertFalse(empty.property('visible'))
        backend._service_data['firefox_audio_error'] = None
        backend.changed.emit()
        self.assertFalse(message.property('visible'))
        self.assertTrue(empty.property('visible'))
        engine.deleteLater()

    def test_chromium_browser_audio_options_are_independent(self):
        app = QGuiApplication.instance() or QGuiApplication([])
        backend = GuiBackend(dbus_only=True)
        backend._connection_state = 'connected'
        backend._service_status = 'running'
        browsers = [{'id': 'chromium.desktop', 'name': 'Chromium'},
                    {'id': 'google-chrome.desktop', 'name': 'Google Chrome'}]
        backend._service_data = {'observed_apps': browsers, 'installed_apps': browsers,
                                 'active_inhibitor_apps': browsers}
        engine = QQmlApplicationEngine()
        engine.rootContext().setContextProperty('topcec', backend)
        engine.load(QUrl.fromLocalFile(str(ROOT / 'cec-tv/topcec.qml')))
        window = engine.rootObjects()[0]
        window.show()
        window.setProperty('currentSection', 2)
        app.processEvents()
        initial = json.loads(QQmlExpression(
            engine.rootContext(), window, 'JSON.stringify(settingsValues())').evaluate()[0])
        self.assertEqual(initial['chromiumAudioBlocksStandby'], [])
        QQmlExpression(engine.rootContext(), window, 'setChromiumAudio("chromium", true)').evaluate()
        values = json.loads(QQmlExpression(
            engine.rootContext(), window, 'JSON.stringify(settingsValues())').evaluate()[0])
        self.assertEqual(values['chromiumAudioBlocksStandby'], ['chromium'])
        self.assertNotIn('chrome', values['chromiumAudioBlocksStandby'])
        self.assertEqual(config_from_settings(backend.config, values)
                         ['chromium_audio_blocks_standby'], ['chromium'])
        window.findChild(QObject, 'autoSaveTimer').stop()
        engine.deleteLater()

    def test_detected_chromium_audio_option_shares_its_app_row(self):
        app = QGuiApplication.instance() or QGuiApplication([])
        backend = GuiBackend(dbus_only=True)
        backend._connection_state = 'connected'
        backend._service_status = 'running'
        path = '/app/chromium/chrome'
        chrome_path = '/app/extra/chrome'
        backend.config = {**DEFAULT_CONFIG,
                          'idle_inhibition_apps': ['org.chromium.Chromium.desktop']}
        backend._service_data = {
            'installed_apps': [{'id': 'org.chromium.Chromium.desktop', 'name': 'Chromium'},
                               {'id': 'com.google.Chrome.desktop', 'name': 'Google Chrome'},
                               {'id': 'org.mozilla.firefox.desktop', 'name': 'Mozilla Firefox'}],
            'observed_apps': [{'id': path, 'name': path},
                              {'id': chrome_path, 'name': chrome_path},
                              {'id': 'firefox.desktop', 'name': 'Mozilla Firefox'}],
            'active_inhibitor_apps': [{'id': path, 'name': path}],
        }
        engine = QQmlApplicationEngine()
        engine.rootContext().setContextProperty('topcec', backend)
        engine.load(QUrl.fromLocalFile(str(ROOT / 'cec-tv/topcec.qml')))
        window = engine.rootObjects()[0]
        window.show()
        window.setProperty('currentSection', 2)
        app.processEvents()
        row = self.app_row(engine, window, 0)
        self.assertEqual(row.objectName(), 'appRow:' + path)
        self.assertEqual(row.findChild(QObject, 'appName:' + path).property('text'), 'Chromium')
        checkbox = row.findChild(QObject, 'browserAudio:chromium')
        self.assertTrue(checkbox.property('visible'))
        QMetaObject.invokeMethod(checkbox, 'click')
        values = json.loads(QQmlExpression(
            engine.rootContext(), window, 'JSON.stringify(settingsValues())').evaluate()[0])
        self.assertEqual(values['chromiumAudioBlocksStandby'], ['chromium'])
        video = row.findChild(QObject, 'browserVideo:chromium')
        self.assertTrue(video.property('visible'))
        allow = row.findChild(QQuickItem, 'idleApp:' + path)
        force = row.findChild(QQuickItem, 'forceApp:' + path)
        audio_item = row.findChild(QQuickItem, 'browserAudio:chromium')
        video_item = row.findChild(QQuickItem, 'browserVideo:chromium')
        audio_position = audio_item.mapToItem(row, QPointF(0, 0))
        video_position = video_item.mapToItem(row, QPointF(0, 0))
        self.assertGreater(audio_position.y(), allow.mapToItem(row, QPointF(0, 0)).y())
        self.assertGreater(audio_position.y(), force.mapToItem(row, QPointF(0, 0)).y())
        self.assertAlmostEqual(video_position.y(), audio_position.y(), delta=1)
        QMetaObject.invokeMethod(video, 'click')
        QMetaObject.invokeMethod(checkbox, 'click')
        values = json.loads(QQmlExpression(
            engine.rootContext(), window, 'JSON.stringify(settingsValues())').evaluate()[0])
        config = config_from_settings(backend.config, values)
        self.assertEqual(config['chromium_video_blocks_standby'], ['chromium'])
        self.assertEqual(config['chromium_audio_blocks_standby'], [])
        QMetaObject.invokeMethod(window.findChild(QObject, 'showAllApps'), 'click')
        app.processEvents()
        choices = json.loads(QQmlExpression(
            engine.rootContext(), window, 'JSON.stringify(appChoices())').evaluate()[0])
        chromium_rows = [item for item in choices if item['browserId'] == 'chromium']
        self.assertEqual(len(chromium_rows), 1)
        self.assertEqual(set(chromium_rows[0]['groupIds']),
                         {path, 'org.chromium.Chromium.desktop'})
        chrome_rows = [item for item in choices if item['name'] == 'Google Chrome']
        self.assertEqual(len(chrome_rows), 1)
        self.assertEqual(set(chrome_rows[0]['groupIds']),
                         {chrome_path, 'com.google.Chrome.desktop'})
        firefox_rows = [item for item in choices if item['isFirefox']]
        self.assertEqual(len(firefox_rows), 1)
        self.assertEqual(set(firefox_rows[0]['groupIds']),
                         {'firefox.desktop', 'org.mozilla.firefox.desktop'})
        row = self.app_row(engine, window, 0)
        allow = row.findChild(QObject, 'idleApp:' + path)
        self.assertFalse(allow.property('checked'))
        QMetaObject.invokeMethod(allow, 'click')
        app.processEvents()
        self.assertEqual(json.loads(QQmlExpression(
            engine.rootContext(), window, 'JSON.stringify(settingsValues())').evaluate()[0])
                         ['idleInhibitionApps'], [])
        row = self.app_row(engine, window, 0)
        QMetaObject.invokeMethod(row.findChild(QObject, 'idleApp:' + path), 'click')
        app.processEvents()
        self.assertEqual(set(json.loads(QQmlExpression(
            engine.rootContext(), window, 'JSON.stringify(settingsValues())').evaluate()[0])
                             ['idleInhibitionApps']),
                         {path, 'org.chromium.Chromium.desktop'})
        for path, expected in (('/app/extra/google/chrome/chrome', 'chrome'),
                               ('/app/brave/brave', 'brave'),
                               ('/app/edge/msedge', 'edge'),
                               ('/app/vivaldi/vivaldi-bin', 'vivaldi')):
            result = QQmlExpression(
                engine.rootContext(), window,
                'browserForApp({id: ' + json.dumps(path) + '}).id').evaluate()[0]
            self.assertEqual(result, expected)
        window.findChild(QObject, 'autoSaveTimer').stop()
        engine.deleteLater()

    def test_browser_setup_guides_registration_with_explicit_flatpak_permission(self):
        app = QGuiApplication.instance() or QGuiApplication([])
        backend = GuiBackend(dbus_only=True)
        backend._connection_state = 'connected'
        backend._service_status = 'running'
        engine = QQmlApplicationEngine()
        engine.rootContext().setContextProperty('topcec', backend)
        engine.load(QUrl.fromLocalFile(str(ROOT / 'cec-tv/topcec.qml')))
        window = engine.rootObjects()[0]
        window.show()
        window.setProperty('width', 780)
        window.setProperty('currentSection', 2)
        app.processEvents()
        QMetaObject.invokeMethod(window.findChild(QObject, 'browserSetupToggle'), 'click')
        browser = window.findChild(QObject, 'setupBrowser')
        installation = window.findChild(QObject, 'setupInstallation')
        browser.setProperty('currentIndex', 0)
        installation.setProperty('currentIndex', 0)
        app.processEvents()
        for control in (browser, installation):
            self.assertGreaterEqual(control.property('width') + 1,
                                    control.property('implicitWidth'))
        requests = []
        with patch.object(backend, '_service_interface', return_value=Mock(isValid=lambda: True)), \
                patch.object(backend, '_async_call', side_effect=lambda _, method, callback, *args:
                             requests.append((method, callback, json.loads(args[0])))):
            QMetaObject.invokeMethod(window.findChild(QObject, 'prepareBrowserExtension'), 'click')
            method, callback, request = requests.pop()
            self.assertEqual(method, 'SetupBrowser')
            self.assertEqual(request, {'browser': 'chromium', 'flatpak': True,
                                       'extension_id': '', 'grant_access': False})
            callback(self.reply({'extension': '/tmp/extension', 'registered': False,
                                 'flatpak': True, 'access_granted': False}))
            self.assertEqual(backend.browserSetupPath, '/tmp/extension')
            grant = window.findChild(QObject, 'browserGrantAccess')
            self.assertFalse(grant.property('checked'))
            extension_id = window.findChild(QObject, 'browserExtensionId')
            extension_id.setProperty('text', 'a' * 32)
            QMetaObject.invokeMethod(window.findChild(QObject, 'registerBrowserExtension'), 'click')
            _, callback, request = requests.pop()
            self.assertFalse(request['grant_access'])
            callback(self.reply({'extension': '/tmp/extension', 'registered': True,
                                 'flatpak': True, 'access_granted': False}))
            self.assertIn('still needs to be granted', backend.browserSetupMessage)
            QMetaObject.invokeMethod(grant, 'click')
            QMetaObject.invokeMethod(window.findChild(QObject, 'registerBrowserExtension'), 'click')
            _, callback, request = requests.pop()
            self.assertEqual(request['extension_id'], 'a' * 32)
            self.assertTrue(request['grant_access'])
            callback(self.reply({'extension': '/tmp/extension', 'registered': True,
                                 'flatpak': True, 'access_granted': True}))
            self.assertIn('restart', backend.browserSetupMessage)

            browser.setProperty('currentIndex', 5)
            installation.setProperty('currentIndex', 1)
            QMetaObject.invokeMethod(window.findChild(QObject, 'prepareBrowserExtension'), 'click')
            method, callback, request = requests.pop()
            self.assertEqual(method, 'SetupBrowser')
            self.assertEqual(request, {'browser': 'firefox', 'flatpak': False,
                                       'extension_id': '', 'grant_access': False})
            callback(self.reply({'browser': 'firefox', 'extension': '/tmp/firefox-extension',
                                 'registered': True, 'flatpak': False,
                                 'access_granted': False}))
            self.assertIn('Mozilla-signed XPI', backend.browserSetupMessage)
            self.assertIn('about:debugging', window.findChild(
                QObject, 'browserSetupInstructions').property('text'))
            self.assertFalse(window.findChild(QObject, 'browserExtensionId').property('visible'))
            self.assertFalse(window.findChild(QObject, 'registerBrowserExtension').property('visible'))
        engine.deleteLater()

    def test_browser_setup_reports_unsupported_host_and_ignores_stale_replies(self):
        app = QGuiApplication.instance() or QGuiApplication([])
        backend = GuiBackend(dbus_only=True)
        backend._connection_state = 'connected'
        requests = []
        with patch.object(backend, '_service_interface', return_value=Mock(isValid=lambda: True)), \
                patch.object(backend, '_async_call', side_effect=lambda _, method, callback, *args:
                             requests.append(callback)):
            backend.setupBrowser('chromium', True, '', False)
            callback = requests.pop()
            backend.resetBrowserSetup()
            callback(self.reply({'extension': '/old', 'registered': False,
                                 'flatpak': True, 'access_granted': False}))
            self.assertEqual(backend.browserSetupPath, '')
            backend.setupBrowser('chromium', True, '', False)
            requests.pop()(topcec_gui.QDBusMessage.createError(
                'org.freedesktop.DBus.Error.UnknownMethod', 'No such method'))
            self.assertIn('Update the host backend', backend.browserSetupMessage)
            self.assertFalse(backend.browserSetupPending)

    def test_firefox_mismatch_warning_is_only_shown_in_diagnostics(self):
        app = QGuiApplication.instance() or QGuiApplication([])
        backend = GuiBackend(dbus_only=True)
        backend._connection_state = 'connected'
        backend._service_status = 'running'
        backend.config['firefox_audio_blocks_standby'] = True
        backend._standby_reason = (
            'Automatic standby blocked: KWin windows are missing from AT-SPI; waiting for a match')
        backend._service_data = {
            'firefox_audio_error': 'KWin windows are missing from AT-SPI; waiting for a match',
            'blocking_apps': [], 'inhibitions_error': None,
        }
        backend._update_diagnostics()
        engine = QQmlApplicationEngine()
        engine.rootContext().setContextProperty('topcec', backend)
        engine.load(QUrl.fromLocalFile(str(ROOT / 'cec-tv/topcec.qml')))
        window = engine.rootObjects()[0]
        window.show()
        window.setProperty('currentSection', 2)
        app.processEvents()
        banner = window.findChild(QObject, 'diagnosticsWarningBanner')
        self.assertFalse(banner.property('visible'))
        self.assertFalse(window.findChild(QObject, 'tvStandbyButton').property('enabled'))
        self.assertIn('standby is blocked',
                      window.findChild(QObject, 'firefoxAudioStatus').property('text'))
        window.setProperty('currentSection', 0)
        app.processEvents()
        self.assertFalse(banner.property('visible'))
        window.setProperty('currentSection', 4)
        app.processEvents()
        self.assertTrue(banner.property('visible'))
        self.assertIn('Automatic standby is blocked', banner.property('text'))
        self.assertIn('missing from AT-SPI', banner.property('text'))
        self.assertIn('missing from AT-SPI', backend.diagnostics)
        self.assertIn('accessibility.force_disabled to -1', backend.diagnostics)
        self.assertTrue(window.findChild(QObject, 'firefoxAccessibilityHelp').property('visible'))
        backend._service_data['firefox_audio_error'] = None
        backend._update_diagnostics()
        backend.changed.emit()
        self.assertFalse(window.findChild(QObject, 'firefoxAccessibilityHelp').property('visible'))
        backend._service_data['firefox_audio_error'] = 'Firefox WebExtension reports audio, but mapping is unknown'
        backend._update_diagnostics()
        self.assertNotIn('Firefox accessibility:', backend.diagnostics)
        backend._service_data['firefox_audio_error'] = 'AT-SPI did not respond'
        backend.config['firefox_audio_blocks_standby'] = False
        backend._update_diagnostics()
        self.assertIn('Firefox audio: disabled', backend.diagnostics)
        self.assertNotIn('Firefox accessibility:', backend.diagnostics)
        engine.deleteLater()

    def test_firefox_audio_row_uses_installed_identity(self):
        app = QGuiApplication.instance() or QGuiApplication([])
        for app_id in ('org.mozilla.firefox.desktop', 'firefox.desktop'):
            with self.subTest(app_id=app_id):
                backend = GuiBackend(dbus_only=True)
                backend._connection_state = 'connected'
                backend._service_status = 'running'
                backend._config_source = 'saved'
                backend.config = {**DEFAULT_CONFIG, 'devices': [],
                                  'idle_inhibition_apps': []}
                firefox = {'id': app_id, 'name': 'Mozilla Firefox'}
                backend._service_data = {
                    'installed_apps': [firefox],
                    'observed_apps': [firefox],
                    'active_inhibitor_apps': [],
                }
                engine = QQmlApplicationEngine()
                engine.rootContext().setContextProperty('topcec', backend)
                engine.load(QUrl.fromLocalFile(str(ROOT / 'cec-tv/topcec.qml')))
                window = engine.rootObjects()[0]
                window.show()
                window.setProperty('currentSection', 2)
                app.processEvents()
                app_list = window.findChild(QObject, 'installedAppsScroll')
                self.assertEqual(app_list.property('count'), 1)
                row = self.app_row(engine, window, 0)
                row_id = app_id or '__firefox_audio__'
                self.assertEqual(row.objectName(), 'appRow:' + row_id)
                audio = row.findChild(QObject, 'firefoxAudio')
                name = row.findChild(QObject, 'appName:' + row_id)
                self.assertEqual(audio.property('text'), 'Block standby while playing audio')
                self.assertEqual(
                    audio.parent(), row.findChild(QObject, 'browserMediaOptions:' + row_id))
                self.assertFalse(audio.property('checked'))
                self.assertEqual(row.findChild(QObject, 'idleApp:' + row_id).property('visible'),
                                 bool(app_id))
                engine.deleteLater()
                app.processEvents()

    def test_uninstalled_browsers_are_not_shown(self):
        app = QGuiApplication.instance() or QGuiApplication([])
        backend = GuiBackend(dbus_only=True)
        backend._connection_state = 'connected'
        backend._service_status = 'running'
        browser_apps = [
            {'id': 'org.chromium.Chromium.desktop', 'name': 'Chromium'},
            {'id': 'google-chrome.desktop', 'name': 'Google Chrome'},
            {'id': 'brave-browser.desktop', 'name': 'Brave'},
            {'id': 'microsoft-edge.desktop', 'name': 'Microsoft Edge'},
            {'id': 'vivaldi.desktop', 'name': 'Vivaldi'},
            {'id': 'org.mozilla.firefox.desktop', 'name': 'Mozilla Firefox'},
        ]
        backend.config = {
            **DEFAULT_CONFIG,
            'idle_inhibition_apps': ['org.chromium.Chromium.desktop'],
            'chromium_audio_blocks_standby': ['chromium'],
            'chromium_video_blocks_standby': ['chrome'],
            'firefox_audio_blocks_standby': True,
            'firefox_video_blocks_standby': True,
        }
        backend._service_data = {
            'installed_apps': [],
            'observed_apps': browser_apps,
            'active_inhibitor_apps': browser_apps,
        }
        engine = QQmlApplicationEngine()
        engine.rootContext().setContextProperty('topcec', backend)
        engine.load(QUrl.fromLocalFile(str(ROOT / 'cec-tv/topcec.qml')))
        window = engine.rootObjects()[0]
        window.show()
        window.setProperty('currentSection', 2)
        app.processEvents()

        app_list = window.findChild(QObject, 'installedAppsScroll')
        self.assertEqual(app_list.property('count'), 0)
        QMetaObject.invokeMethod(window.findChild(QObject, 'showAllApps'), 'click')
        app.processEvents()
        self.assertEqual(app_list.property('count'), 0)
        engine.deleteLater()

    def test_app_cards_expand_and_firefox_label_stays_readable(self):
        app = QGuiApplication.instance() or QGuiApplication([])
        backend = GuiBackend(dbus_only=True)
        backend._connection_state = 'connected'
        backend._service_status = 'running'
        backend._status_poll_timer.stop()
        firefox = {'id': 'firefox.desktop', 'name': 'Mozilla Firefox'}
        backend._service_data = {
            'installed_apps': [firefox], 'observed_apps': [],
            'active_inhibitor_apps': [],
        }
        engine = QQmlApplicationEngine()
        engine.rootContext().setContextProperty('topcec', backend)
        engine.load(QUrl.fromLocalFile(str(ROOT / 'cec-tv/topcec.qml')))
        window = engine.rootObjects()[0]
        window.resize(1200, 900)
        window.show()
        window.setProperty('currentSection', 2)
        app.processEvents()
        page = window.findChild(QQuickItem, 'pageContent')
        app_list = window.findChild(QQuickItem, 'installedAppsScroll')
        self.assertGreater(page.width(), 850)
        self.assertGreater(app_list.width(), page.width() - 40)
        for section, card_name in ((0, 'powerCard'), (1, 'equipmentFormCard'),
                                   (2, 'standbyFormCard'), (3, 'inputFormCard')):
            window.setProperty('currentSection', section)
            QTest.qWait(30)
            card = window.findChild(QObject, card_name)
            self.assertTrue(card.property('visible'))
            self.assertFalse(card.property('cardWidthRestricted'))
            self.assertGreater(card.property('width'), 850)
        window.setProperty('currentSection', 2)
        app.processEvents()

        row = self.app_row(engine, window, 0)
        name = row.findChild(QQuickItem, 'appName:firefox.desktop')
        audio = row.findChild(QQuickItem, 'firefoxAudio')
        font = name.property('font')
        font.setPointSizeF(18)
        name.setProperty('font', font)
        app.processEvents()
        self.assertGreaterEqual(name.width(), QFontMetricsF(font).horizontalAdvance(name.property('text')))
        self.assertEqual(name.property('lineCount'), 1)
        video = row.findChild(QQuickItem, 'firefoxVideo')
        name_position = name.mapToItem(row, QPointF(0, 0))
        audio_position = audio.mapToItem(row, QPointF(0, 0))
        video_position = video.mapToItem(row, QPointF(0, 0))
        self.assertGreater(audio_position.y(), name_position.y())
        self.assertAlmostEqual(video_position.y(), audio_position.y(), delta=1)

        window.resize(380, 760)
        app.processEvents()
        audio_position = audio.mapToItem(row, QPointF(0, 0))
        video_position = video.mapToItem(row, QPointF(0, 0))
        self.assertGreater(video_position.y(), audio_position.y())
        self.assertLessEqual(name.width(), name.parentItem().width())
        self.assertEqual(name.property('lineCount'), 1)
        self.assertLess(page.width(), 380)

        firefox['name'] = 'A very long Firefox application name ' * 8
        backend.appsChanged.emit()
        app.processEvents()
        row = self.app_row(engine, window, 0)
        name = row.findChild(QQuickItem, 'appName:firefox.desktop')
        self.assertLessEqual(name.width(), name.parentItem().width())
        self.assertGreater(name.property('lineCount'), 1)
        engine.deleteLater()

    def test_firefox_audio_draft_survives_search_and_recreated_row(self):
        app = QGuiApplication.instance() or QGuiApplication([])
        backend = GuiBackend(dbus_only=True)
        backend._connection_state = 'connected'
        backend._service_status = 'running'
        firefox = {'id': 'org.mozilla.firefox.desktop', 'name': 'Mozilla Firefox'}
        backend._service_data = {
            'installed_apps': [firefox], 'observed_apps': [],
            'active_inhibitor_apps': [],
        }
        engine = QQmlApplicationEngine()
        engine.rootContext().setContextProperty('topcec', backend)
        engine.load(QUrl.fromLocalFile(str(ROOT / 'cec-tv/topcec.qml')))
        window = engine.rootObjects()[0]
        window.show()
        window.setProperty('currentSection', 2)
        app.processEvents()
        row = self.app_row(engine, window, 0)
        QMetaObject.invokeMethod(row.findChild(QObject, 'firefoxAudio'), 'click')
        search = window.findChild(QObject, 'appSearch')
        search.setProperty('text', 'firefox')
        app.processEvents()
        self.assertEqual(window.findChild(QObject, 'installedAppsScroll').property('count'), 0)
        values = json.loads(QQmlExpression(
            engine.rootContext(), window, 'JSON.stringify(settingsValues())').evaluate()[0])
        self.assertTrue(values['firefoxAudioBlocksStandby'])
        QMetaObject.invokeMethod(window.findChild(QObject, 'showAllApps'), 'click')
        app.processEvents()
        row = self.app_row(engine, window, 0)
        self.assertTrue(row.findChild(QObject, 'firefoxAudio').property('checked'))
        QMetaObject.invokeMethod(row.findChild(QObject, 'firefoxAudio'), 'click')
        search.setProperty('text', '')
        QMetaObject.invokeMethod(window.findChild(QObject, 'showAllApps'), 'click')
        app.processEvents()
        row = self.app_row(engine, window, 0)
        self.assertFalse(row.findChild(QObject, 'firefoxAudio').property('checked'))
        QMetaObject.invokeMethod(window.findChild(QObject, 'autoSaveTimer'), 'stop')
        engine.deleteLater()

    def test_browser_media_options_share_a_row_when_space_allows(self):
        app = QGuiApplication.instance() or QGuiApplication([])
        backend = GuiBackend(dbus_only=True)
        backend._connection_state = 'connected'
        backend._service_status = 'running'
        backend._status_poll_timer.stop()
        firefox = {'id': 'firefox.desktop', 'name': 'Mozilla Firefox'}
        player = {'id': 'player.desktop', 'name': 'Video Player'}
        backend._service_data = {
            'installed_apps': [firefox, player], 'observed_apps': [player],
            'active_inhibitor_apps': [],
        }
        engine = QQmlApplicationEngine()
        engine.rootContext().setContextProperty('topcec', backend)
        engine.load(QUrl.fromLocalFile(str(ROOT / 'cec-tv/topcec.qml')))
        window = engine.rootObjects()[0]
        window.resize(1300, 900)
        window.show()
        window.setProperty('currentSection', 2)
        QTest.qWait(50)

        firefox_row = self.app_row(engine, window, 0)
        player_row = self.app_row(engine, window, 1)
        firefox_controls = [firefox_row.findChild(QQuickItem, name) for name in (
            'appName:firefox.desktop', 'idleApp:firefox.desktop',
            'forceApp:firefox.desktop', 'firefoxAudio', 'firefoxVideo')]
        player_controls = [player_row.findChild(QQuickItem, name) for name in (
            'appName:player.desktop', 'idleApp:player.desktop', 'forceApp:player.desktop')]
        for width in (1300, 775):
            window.resize(width, 900)
            QTest.qWait(50)
            self.assertEqual(window.findChild(QObject, 'idleTimeoutLabel').property('lineCount'), 1)
            firefox_positions = [
                control.mapToItem(firefox_row, QPointF(0, 0)) for control in firefox_controls]
            player_positions = [
                control.mapToItem(player_row, QPointF(0, 0)) for control in player_controls]
            for controls in (firefox_controls[:3], player_controls):
                self.assertEqual(controls[0].property('lineCount'), 1)
                self.assertTrue(all(control.y() == controls[0].y() for control in controls))
                for left, right in zip(controls, controls[1:]):
                    self.assertLessEqual(left.x() + left.width(), right.x())
            for firefox_position, player_position in zip(firefox_positions, player_positions):
                self.assertEqual(firefox_position.x(), player_position.x())
            self.assertEqual(firefox_positions[3].x(), firefox_positions[1].x())
            self.assertGreater(firefox_positions[3].y(), firefox_positions[2].y())
            if width == 1300:
                self.assertAlmostEqual(
                    firefox_positions[4].y(), firefox_positions[3].y(), delta=1)
            else:
                self.assertGreaterEqual(
                    firefox_positions[4].y(), firefox_positions[3].y())
            if width == 1300:
                self.assertEqual(firefox_positions[0].y(), firefox_positions[2].y())

        window.resize(380, 760)
        QTest.qWait(50)
        firefox_positions = [
            control.mapToItem(firefox_row, QPointF(0, 0)) for control in firefox_controls]
        self.assertEqual(firefox_positions[3].x(), firefox_positions[1].x())
        self.assertGreater(firefox_positions[3].y(), firefox_positions[2].y())
        for control in firefox_controls + player_controls:
            self.assertLessEqual(control.x() + control.width(), control.parentItem().width() + 1)
            self.assertLessEqual(control.y() + control.height(), control.parentItem().height() + 1)
        engine.deleteLater()

    def test_invalid_settings_are_rejected(self):
        with self.assertRaises(ValueError):
            config_from_settings(self.config, {**self.values, 'timeoutMode': 'other'})
        self.assertEqual(config_from_settings(
            self.config, {**self.values, 'devices': ''})['devices'], [])

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

    def test_simulation_buttons_preview_without_calling_service(self):
        backend = GuiBackend(dbus_only=True)
        backend._service_data = {'cec_enabled': True, 'power_state': 'on',
                                 'pending_action': 'on'}
        backend._config_reply(0, self.reply({'schema_version': 1, **DEFAULT_CONFIG}))
        with patch.object(backend, '_service_interface') as service:
            backend.simulatePower('off')
        service.assert_not_called()
        self.assertEqual(backend.actionMessage, '')
        self.assertEqual(backend.powerState, 'Off (simulated)')
        self.assertIn('Pending action: standby (simulated)', backend.diagnostics)
        backend._config_reply(0, self.reply({'schema_version': 1, **DEFAULT_CONFIG}))
        self.assertEqual(backend.powerState, 'Off (simulated)')
        self.assertIn('Pending action: standby (simulated)', backend.diagnostics)
        backend.simulatePower('on')
        self.assertEqual(backend.powerState, 'On (simulated)')
        self.assertIn('Pending action: on (simulated)', backend.diagnostics)
        self.assertEqual(backend._service_data['pending_action'], 'on')

        interface = Mock(isValid=Mock(return_value=True))
        with patch.object(backend, '_service_interface', return_value=interface), \
                patch.object(backend, '_async_call'):
            backend.requestPower('on')
        self.assertEqual(backend.actionMessage, '')
        self.assertEqual(backend.powerState, 'on')
        self.assertIn('Pending action: on\n', backend.diagnostics)

    def test_queued_power_request_uses_pending_action_instead_of_action_message(self):
        backend = GuiBackend(dbus_only=True)
        backend._service_data = {'pending_action': 'on'}
        backend._update_diagnostics()

        backend._power_reply(0, 'on', self.reply({}))

        self.assertEqual(backend.actionMessage, '')
        self.assertIn('Pending action: on', backend.diagnostics)

    def test_cec_fault_uses_successful_adapter_discovery(self):
        backend = GuiBackend(dbus_only=True)
        backend._service_data = {'cec_fault': None}
        backend._config_reply(0, self.reply({'schema_version': 1, **DEFAULT_CONFIG}))
        inventory = {'outputs': [], 'adapters': [], 'inputs': [], 'errors': []}
        self.assertIn('CEC fault: none', backend.diagnostics)
        backend._equipment_reply(0, self.reply(inventory))
        self.assertIn('CEC fault: adapter not found', backend.diagnostics)
        backend._service_data['cec_fault'] = 'adapter failed'
        backend._config_reply(0, self.reply({'schema_version': 1, **DEFAULT_CONFIG}))
        self.assertIn('CEC fault: adapter failed', backend.diagnostics)
        backend._service_data['cec_fault'] = None
        backend._equipment_reply(0, self.reply({
            **inventory, 'errors': ['CEC adapter discovery: permission denied']}))
        self.assertIn('CEC fault: none', backend.diagnostics)
        backend._equipment_reply(0, self.reply({
            **inventory, 'errors': ['Display discovery: unavailable']}))
        self.assertIn('CEC fault: adapter not found', backend.diagnostics)
        backend._equipment_reply(0, self.reply({
            **inventory, 'adapters': [{'path': '/dev/cec', 'label': 'CEC'}]}))
        self.assertIn('CEC fault: none', backend.diagnostics)

    def test_gui_displays_english_service_diagnostics(self):
        from monitor import Mapping

        backend = GuiBackend(dbus_only=True)
        reason = Mapping(15).health(0, required=True)
        status = {
            'service': 'running', 'power_state': 'unknown',
            'fail_safe_reason': reason, 'scan_status': reason,
        }
        interface = Mock()
        interface.isValid.return_value = True
        bus = Mock()
        bus.isConnected.return_value = True
        watchers = []

        def make_watcher(pending, parent):
            watcher = self.FakeWatcher(pending, parent)
            watchers.append(watcher)
            return watcher

        with patch.object(backend, '_service_interface', return_value=interface), \
                patch.object(topcec_gui.QDBusConnection, 'sessionBus',
                             return_value=bus), \
                patch.object(topcec_gui, 'QDBusPendingCallWatcher',
                             side_effect=make_watcher):
            backend.refresh()
            watchers[0].complete(SimpleNamespace(
                type=lambda: topcec_gui.QDBusMessage.MessageType.ReplyMessage,
                arguments=lambda: [json.dumps(status)]))
            watchers[1].complete(SimpleNamespace(
                type=lambda: topcec_gui.QDBusMessage.MessageType.ReplyMessage,
                arguments=lambda: [json.dumps({
                    'schema_version': 1, **DEFAULT_CONFIG,
                })]))
        self.assertEqual(
            backend.standbyReason,
            'Automatic standby blocked: Waiting for Firefox snapshot from the live bridge')
        self.assertIn('Scan: Waiting for Firefox snapshot from the live bridge',
                      backend.diagnostics)
        self.assertNotIn('Service: running', backend.diagnostics)

    def test_flatpak_missing_service_is_generic_and_actionable(self):
        bus = Mock()
        bus.isConnected.return_value = True
        interface = Mock()
        interface.isValid.return_value = False
        with patch.object(topcec_gui.QDBusConnection, 'sessionBus',
                          return_value=bus), \
                patch.object(GuiBackend, '_service_interface',
                             return_value=interface):
            backend = GuiBackend(dbus_only=True)
            backend.refresh()
        self.assertEqual(backend.connectionState, 'unavailable')
        self.assertIn('cannot determine whether it is installed or stopped',
                      backend.connectionMessage)
        self.assertNotIn('not installed', backend.connectionMessage)
        self.assertFalse(backend.settingsEnabled)

    def test_native_gui_detects_installed_but_stopped_service(self):
        bus = Mock()
        bus.isConnected.return_value = True
        interface = Mock()
        interface.isValid.return_value = False
        probes = []

        def make_process(parent):
            probe = self.FakeProcess()
            probes.append(probe)
            return probe

        with patch.object(topcec_gui.QDBusConnection, 'sessionBus',
                          return_value=bus), \
                patch.object(topcec_gui, 'available_outputs', return_value=[]), \
                patch.object(topcec_gui, 'available_adapters', return_value=[]), \
                patch.object(topcec_gui, 'QProcess', side_effect=make_process), \
                patch.object(GuiBackend, '_service_interface',
                             return_value=interface):
            backend = GuiBackend(dbus_only=False)
            backend.refresh()
            probes[0].complete('loaded\ninactive\n')
        self.assertEqual(backend.serviceStatus, 'stopped')
        self.assertIn('installed but stopped', backend.connectionMessage)
        self.assertTrue(backend.settingsEnabled)

    def test_native_gui_detects_a_missing_user_service(self):
        bus = Mock()
        bus.isConnected.return_value = True
        interface = Mock()
        interface.isValid.return_value = False
        probes = []

        def make_process(parent):
            probe = self.FakeProcess()
            probes.append(probe)
            return probe

        with patch.object(topcec_gui.QDBusConnection, 'sessionBus',
                          return_value=bus), \
                patch.object(topcec_gui, 'available_outputs', return_value=[]), \
                patch.object(topcec_gui, 'available_adapters', return_value=[]), \
                patch.object(topcec_gui, 'QProcess', side_effect=make_process), \
                patch.object(GuiBackend, '_service_interface',
                             return_value=interface):
            backend = GuiBackend(dbus_only=False)
            backend.refresh()
            probes[0].complete('not-found\ninactive\n')
        self.assertEqual(backend.serviceStatus, 'not-installed')
        self.assertIn('service is not installed', backend.connectionMessage)

    def test_dbus_connection_error_is_distinct_from_missing_service(self):
        bus = Mock()
        bus.isConnected.return_value = False
        with patch.object(topcec_gui.QDBusConnection, 'sessionBus',
                          return_value=bus):
            backend = GuiBackend(dbus_only=True)
            backend.refresh()
        self.assertEqual(backend.connectionState, 'error')
        self.assertIn('session D-Bus is disconnected', backend.connectionMessage)

    def test_backend_appearance_and_disappearance_recover_without_restart(self):
        bus = Mock()
        bus.isConnected.return_value = True
        interface = Mock()
        interface.isValid.return_value = False
        watchers = []

        def make_watcher(pending, parent):
            watcher = self.FakeWatcher(pending, parent)
            watchers.append(watcher)
            return watcher

        with patch.object(topcec_gui.QDBusConnection, 'sessionBus',
                          return_value=bus), \
                patch.object(topcec_gui, 'QDBusPendingCallWatcher',
                             side_effect=make_watcher), \
                patch.object(GuiBackend, '_service_interface',
                             return_value=interface):
            backend = GuiBackend(dbus_only=True)
            backend.refresh()
            self.assertEqual(backend.connectionState, 'unavailable')

            interface.isValid.return_value = True
            backend._name_owner_changed(topcec_gui.SERVICE, '', ':1.42')
            self.assertEqual(len(watchers), 1)
            status = {
                'service': 'running', 'power_state': 'on',
                'cec_enabled': True,
            }
            watchers[0].complete(SimpleNamespace(
                type=lambda: topcec_gui.QDBusMessage.MessageType.ReplyMessage,
                arguments=lambda: [json.dumps(status)]))
            self.assertEqual(len(watchers), 2)
            watchers[1].complete(SimpleNamespace(
                type=lambda: topcec_gui.QDBusMessage.MessageType.ReplyMessage,
                arguments=lambda: [json.dumps({
                    'schema_version': 1, **DEFAULT_CONFIG,
                })]))
            self.assertEqual(backend.connectionState, 'connected')
            self.assertEqual(backend.powerState, 'on')
            self.assertTrue(backend.settingsEnabled)

            backend._name_owner_changed(topcec_gui.SERVICE, ':1.42', '')
            self.assertEqual(backend.connectionState, 'unavailable')
            self.assertEqual(backend.powerState, 'unavailable')
            self.assertFalse(backend.settingsEnabled)

            backend._name_owner_changed(topcec_gui.SERVICE, '', ':1.43')
            watchers[3].complete(SimpleNamespace(
                type=lambda: topcec_gui.QDBusMessage.MessageType.ReplyMessage,
                arguments=lambda: [json.dumps(status)]))
            watchers[4].complete(SimpleNamespace(
                type=lambda: topcec_gui.QDBusMessage.MessageType.ReplyMessage,
                arguments=lambda: [json.dumps({
                    'schema_version': 1, **DEFAULT_CONFIG,
                })]))
            self.assertEqual(backend.connectionState, 'connected')
            self.assertTrue(backend.settingsEnabled)

    def test_name_owner_signal_is_registered_only_once(self):
        bus = Mock()
        bus.isConnected.return_value = True
        bus.connect.return_value = True
        with patch.object(topcec_gui.QDBusConnection, 'sessionBus',
                          return_value=bus):
            backend = GuiBackend(dbus_only=True)
            backend._ensure_owner_watch()
            backend._ensure_owner_watch()
        self.assertEqual(bus.connect.call_count, 1)
        self.assertEqual(bus.connect.call_args.args[3], 'NameOwnerChanged')

    def test_setup_view_and_flatpak_permissions_are_documented(self):
        qml = (ROOT / 'cec-tv/topcec.qml').read_text(encoding='utf-8')
        self.assertIn('topCEC Backend Not Available', qml)
        self.assertIn('Retry Connection', qml)
        self.assertIn('bash packaging/install-user.sh', qml)
        self.assertIn('systemctl --user enable --now topcec.service', qml)
        self.assertIn('interval: topcec.backendAvailable ? 5000 : 30000', qml)
        self.assertIn('readonly property bool setupRequired: topcec.dbusOnly && !topcec.backendAvailable', qml)
        self.assertIn('visible: root.setupRequired', qml)
        self.assertIn('visible: !root.setupRequired', qml)
        manifest = (ROOT / 'net.local.topcec.yml').read_text(encoding='utf-8')
        self.assertIn('--talk-name=net.local.CecActivity', manifest)
        for forbidden_permission in (
                '--filesystem=host', '--device=all',
                '--talk-name=org.freedesktop.systemd1'):
            self.assertNotIn(forbidden_permission, manifest)

    def test_settings_are_applied_through_host_service(self):
        backend = GuiBackend(dbus_only=True)
        backend._connection_state = 'connected'
        backend._service_status = 'running'
        interface = Mock()
        interface.isValid.return_value = True
        bus = Mock()
        bus.isConnected.return_value = True
        watchers = []

        def make_watcher(pending, parent):
            watcher = self.FakeWatcher(pending, parent)
            watchers.append(watcher)
            return watcher

        with patch.object(backend, '_service_interface', return_value=interface), \
                patch.object(backend, 'refresh') as refresh, \
                patch.object(topcec_gui.QDBusConnection, 'sessionBus',
                             return_value=bus), \
                patch.object(topcec_gui, 'QDBusPendingCallWatcher',
                             side_effect=make_watcher):
            backend.applySettings(self.values)
            name, arguments = interface.asyncCallWithArgumentList.call_args.args
            serialized, = arguments
            watchers[0].complete(SimpleNamespace(
                type=lambda: topcec_gui.QDBusMessage.MessageType.ReplyMessage,
                arguments=lambda: [json.dumps({
                    'accepted': True, 'config': json.loads(serialized)})]))
        self.assertEqual(name, 'ApplySettings')
        config = validate_config(json.loads(serialized))
        self.assertEqual(config['target_output'], 'HDMI-A-2')
        self.assertTrue(config['require_snapshot'])
        self.assertIn('older backend', backend.actionMessage)
        refresh.assert_called_once()

    def test_configuration_only_backend_enables_flatpak_settings_not_power(self):
        backend = GuiBackend(dbus_only=True)
        backend._service_data = {
            'service': 'configuration-only', 'cec_enabled': False,
            'fail_safe_reason': 'Cannot read input: Permission denied',
        }
        config = {
            'schema_version': 1, **DEFAULT_CONFIG,
            'target_output': 'DP-1',
            'devices': ['/dev/input/by-id/host-keyboard'],
        }
        backend._config_reply(0, SimpleNamespace(
            type=lambda: topcec_gui.QDBusMessage.MessageType.ReplyMessage,
            arguments=lambda: [json.dumps(config)]))
        self.assertTrue(backend.backendAvailable)
        self.assertTrue(backend.settingsEnabled)
        self.assertEqual(backend.serviceStatus, 'configuration-only')
        self.assertIn('configuration only', backend.connectionMessage)
        self.assertIn('Permission denied', backend.standbyReason)
        with patch.object(backend, '_service_interface') as interface:
            backend.requestPower('on')
            interface.assert_not_called()
        self.assertEqual(backend.actionMessage, 'Live CEC control is unavailable.')

    def test_qml_loads_host_config_and_preserves_draft_across_recovery(self):
        app = QGuiApplication.instance() or QGuiApplication([])
        backend = GuiBackend(dbus_only=True)
        engine = QQmlApplicationEngine()
        engine.rootContext().setContextProperty('topcec', backend)
        engine.load(QUrl.fromLocalFile(str(ROOT / 'cec-tv/topcec.qml')))
        window = engine.rootObjects()[0]
        devices = window.findChild(QObject, 'devicesField')
        output = window.findChild(QObject, 'outputField')
        self.assertIsNotNone(devices)
        self.assertIsNotNone(output)
        self.assertIsNone(window.findChild(QObject, 'saveSettingsButton'))

        def connect(config):
            backend._service_data = {
                'service': 'configuration-only', 'cec_enabled': False,
                'configuration_saved': True,
                'fail_safe_reason': 'Cannot read input: Permission denied',
            }
            backend._config_reply(backend._refresh_generation, SimpleNamespace(
                type=lambda: topcec_gui.QDBusMessage.MessageType.ReplyMessage,
                arguments=lambda: [json.dumps(config)]))
            app.processEvents()

        config = {
            'schema_version': 1, **DEFAULT_CONFIG,
            'target_output': 'DP-1',
            'devices': ['/dev/input/by-id/host-keyboard'],
        }
        connect(config)
        self.assertEqual(devices.property('text'), config['devices'][0])
        self.assertEqual(output.property('editText'), 'DP-1')
        window.setProperty('currentSection', 3)
        QMetaObject.invokeMethod(window.findChild(QObject, 'manualPathsToggle'), 'click')
        QMetaObject.invokeMethod(devices, 'forceActiveFocus')
        devices.setProperty('text', '/dev/input/by-id/draft-keyboard')
        self.assertTrue(window.property('settingsDirty'))
        window.findChild(QObject, 'manualOutput').setProperty('checked', True)
        output.setProperty('editText', 'DRAFT-1')
        backend._name_owner_changed(topcec_gui.SERVICE, ':1.42', '')
        connect({**config, 'target_output': 'CHANGED-1'})
        self.assertEqual(devices.property('text'), '/dev/input/by-id/draft-keyboard')
        self.assertEqual(output.property('editText'), 'DRAFT-1')
        self.assertTrue(window.property('settingsDirty'))
        engine.deleteLater()

    def test_native_qml_configuration_is_visible_and_editable_offline(self):
        app = QGuiApplication.instance() or QGuiApplication([])
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(topcec_gui, 'available_outputs', return_value=[]), \
                patch.object(topcec_gui, 'available_adapters', return_value=[]):
            backend = GuiBackend(Path(directory) / 'config.json', dbus_only=False)
            backend._connection_state = 'unavailable'
            engine = QQmlApplicationEngine()
            engine.rootContext().setContextProperty('topcec', backend)
            engine.load(QUrl.fromLocalFile(str(ROOT / 'cec-tv/topcec.qml')))
            window = engine.rootObjects()[0]
            self.assertIsNone(window.findChild(QObject, 'saveSettingsButton'))
            for name in ('manualOutput', 'manualAdapter'):
                window.findChild(QObject, name).setProperty('checked', True)
            window.findChild(QObject, 'outputField').setProperty('editText', 'MANUAL-DISPLAY')
            window.findChild(QObject, 'adapterField').setProperty('editText', '/dev/manual-adapter')
            window.findChild(QObject, 'devicesField').setProperty('text', '/dev/manual-input')
            window.setProperty('currentSection', 3)
            app.processEvents()
            window.findChild(QObject, 'manualPathsToggle').setProperty('checked', True)
            devices = window.findChild(QObject, 'devicesField')
            self.assertTrue(devices.property('visible'))
            self.assertFalse(devices.property('readOnly'))
            self.assertIsNotNone(app)
            engine.deleteLater()

    def test_native_gui_can_configure_before_service_starts(self):
        probes = []

        def make_process(parent):
            probe = self.FakeProcess()
            probes.append(probe)
            return probe

        with tempfile.TemporaryDirectory() as directory, \
                patch.object(topcec_gui, 'available_outputs', return_value=[]), \
                patch.object(topcec_gui, 'available_adapters', return_value=[]), \
                patch.object(topcec_gui, 'QProcess', side_effect=make_process), \
                patch.object(topcec_gui.subprocess, 'run', return_value=SimpleNamespace(
                    returncode=0, stdout='', stderr='')) as run:
            path = Path(directory) / 'config.json'
            backend = GuiBackend(path, dbus_only=False)
            self.assertTrue(backend.settingsEnabled)
            backend.applySettings(self.values)
            self.assertEqual(validate_config(json.loads(
                path.read_text(encoding='utf-8')))['target_output'], 'HDMI-A-2')
            run.assert_not_called()
            self.assertIn('next service start', backend.actionMessage)

    def test_native_gui_offline_save_does_not_execute_systemctl(self):
        probes = []

        def make_process(parent):
            probe = self.FakeProcess()
            probes.append(probe)
            return probe

        with tempfile.TemporaryDirectory() as directory, \
                patch.object(topcec_gui, 'available_outputs', return_value=[]), \
                patch.object(topcec_gui, 'available_adapters', return_value=[]), \
                patch.object(topcec_gui, 'QProcess', side_effect=make_process), \
                patch.object(topcec_gui.subprocess, 'run',
                             side_effect=AssertionError('Must not restart a service')):
            path = Path(directory) / 'config.json'
            backend = GuiBackend(path, dbus_only=False)
            backend.applySettings(self.values)
            self.assertTrue(path.is_file())
            self.assertIn('next service start',
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
        manifest = (ROOT / 'net.local.topcec.yml').read_text(
            encoding='utf-8')
        launcher = (ROOT / 'packaging/flatpak/topcec-gui').read_text(
            encoding='utf-8')
        self.assertIn('app-id: net.local.topcec', manifest)
        self.assertIn('--talk-name=net.local.CecActivity', manifest)
        self.assertNotIn('base: io.qt.PySide.BaseApp', manifest)
        self.assertIn('runtime-version: "6.11"', manifest)
        self.assertIn('packaging/flatpak/pyside.yml', manifest)
        self.assertIn('path: .', manifest)
        self.assertIn('/app/share/icons/hicolor/scalable/apps/net.local.topcec.svg',
                      manifest)
        self.assertIn("os.environ['TOPCEC_DBUS_ONLY'] = '1'", launcher)
        self.assertIn('org.kde.Platform', manifest)
        self.assertIn('cec-tv/activity_policy.py', manifest)
        self.assertIn('cec-tv/configuration.py', manifest)
        self.assertIn('cec-tv/topcec_gui.py', manifest)
        self.assertIn('cec-tv/topcec.qml', manifest)
        for forbidden_permission in (
                '--filesystem=host', '--device=all', '--socket=session-bus',
                '--talk-name=org.freedesktop.systemd1',
                '--talk-name=org.kde.KWin'):
            self.assertNotIn(forbidden_permission, manifest)

    def test_flatpak_builds_bindings_against_sdk_and_checks_imports(self):
        module = (ROOT / 'packaging/flatpak/pyside.yml').read_text(
            encoding='utf-8')
        self.assertIn('--qtpaths=/usr/bin/qtpaths', module)
        self.assertIn('--module-subset=Core,Gui,Network,DBus,OpenGL,Qml,Quick', module)
        self.assertIn('from PySide6 import QtCore, QtDBus, QtGui, QtQml, QtQuick',
                      module)
        self.assertNotIn('LD_LIBRARY_PATH', module)
        self.assertIn('sha256:', module)
        self.assertIn('LICENSES/*.txt /app/share/licenses/pyside/', module)

    def test_qml_list_accessors_take_no_arguments(self):
        backend = GuiBackend(dbus_only=True)
        meta = backend.metaObject()
        self.assertGreaterEqual(meta.indexOfMethod('deviceList()'), 0)
        self.assertGreaterEqual(meta.indexOfMethod('muteLabelList()'), 0)

    def test_kirigami_window_loads_offscreen(self):
        app = QGuiApplication.instance() or QGuiApplication([])
        app.setDesktopFileName(topcec_gui.APP_ID)
        app.setWindowIcon(topcec_gui.application_icon())
        backend = GuiBackend(dbus_only=True)
        engine = QQmlApplicationEngine()
        engine.rootContext().setContextProperty('topcec', backend)
        engine.load(QUrl.fromLocalFile(
            str(ROOT / 'cec-tv' / 'topcec.qml')))
        self.assertEqual(len(engine.rootObjects()), 1)
        self.assertFalse(app.windowIcon().isNull())
        self.assertEqual(app.desktopFileName(), 'net.local.topcec')
        self.assertIsNotNone(app)


if __name__ == '__main__':
    unittest.main(verbosity=2)
