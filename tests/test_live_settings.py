# SPDX-License-Identifier: GPL-3.0-or-later
"""In-process live configuration transactions with mocked hardware and D-Bus."""
import json
import os
from contextlib import nullcontext
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'cec-tv'))
import monitor
from chromium_media import ChromiumMedia
from configuration import DEFAULT_CONFIG, load_config, save_config


class Device:
    def __init__(self, path, fd):
        self.path, self.fd, self.closed = path, fd, False
        self.events = []
        self.failure = None

    def capabilities(self, absinfo=True):
        return {3: [(0, SimpleNamespace(min=0, max=1000, value=500, fuzz=0)),
                    (2, SimpleNamespace(min=0, max=1000, value=500, fuzz=0))]}

    def read(self):
        if self.failure:
            raise self.failure
        events, self.events = self.events, []
        return iter(events)

    def close(self):
        self.closed = True


class Selector:
    def __init__(self):
        self.devices = {}
        self.closed = False
        self.fail_register = None

    def register(self, device, events):
        if device.path == self.fail_register:
            raise OSError('Input selector registration failed')
        self.devices[device.fd] = device

    def select(self, timeout=0):
        if self.closed:
            raise AssertionError('Polling a retired selector')
        return [(SimpleNamespace(fileobj=device), 1) for device in self.devices.values()]

    def close(self):
        self.closed = True


class TestPower(monitor.CecPower):
    __test__ = False

    def __init__(self, port):
        super().__init__(port)
        self.validation_error = None
        self.validated = False
        self.closed = False
        self.poll = Mock()
        self.request = Mock()
        self.activity = Mock()

    def validate_port(self):
        if self.validation_error:
            raise self.validation_error
        self.validated = True

    def close(self):
        self.closed = True


class LiveSettingsChecks(unittest.TestCase):
    def test_kde_timeout_uses_fallback_on_read_error_and_recovers(self):
        timer = Mock()
        settings = monitor.KdeTimeout()
        failed_read = Mock()
        failed_read.poll.return_value = 1
        failed_read.returncode = 1
        failed_read.communicate.return_value = (
            json.dumps({'ok': False, 'error': 'Plasma unavailable'}), '')
        settings.process = failed_read

        with patch.object(monitor, 'log'):
            error = settings.poll(timer, 10)
            self.assertIn('Plasma unavailable', error)
            self.assertTrue(settings.fallback_active)
            timer.set_timeout.assert_called_once_with(300.0, 10)

            recovered_read = Mock()
            recovered_read.poll.return_value = 0
            recovered_read.returncode = 0
            recovered_read.communicate.return_value = (
                json.dumps({'ok': True, 'timeout': 600}), '')
            settings.process = recovered_read
            self.assertIsNone(settings.poll(timer, 16))
            self.assertFalse(settings.fallback_active)
            self.assertEqual(timer.set_timeout.call_args_list, [
                unittest.mock.call(300.0, 10),
                unittest.mock.call(600, 16),
            ])

            disabled_read = Mock()
            disabled_read.poll.return_value = 0
            disabled_read.returncode = 0
            disabled_read.communicate.return_value = (
                json.dumps({'ok': True, 'timeout': None}), '')
            settings.process = disabled_read
            self.assertIsNone(settings.poll(timer, 22))
            self.assertFalse(settings.fallback_active)
            self.assertEqual(timer.set_timeout.call_args,
                             unittest.mock.call(None, 22))

    def run_service(self, path, scenario, *, initial=None, fail_inputs=(), fail_adapter=None,
                    plasma_timeout_seconds='unread', inventory=None):
        config = {**DEFAULT_CONFIG, 'target_output': '/mock/output',
                  'devices': ['/mock/keyboard'], 'cec_port': '/mock/cec',
                  **(initial or {})}
        context = SimpleNamespace(receiver=None, browser_receiver=None, callbacks={}, inputs=[], selectors=[],
                                  powers=[], workers=[], providers=[], now=0,
                                  fail_register=None, denied=set(fail_inputs))
        fd = 10
        timer_class = monitor.Timer

        def open_input(device_path):
            nonlocal fd
            if device_path in context.denied:
                raise PermissionError(13, 'Permission denied', device_path)
            fd += 1
            device = Device(device_path, fd)
            context.inputs.append(device)
            return device

        def make_selector():
            selector = Selector()
            selector.fail_register = context.fail_register
            context.selectors.append(selector)
            return selector

        def make_power(port):
            power = TestPower(port)
            if port == fail_adapter:
                power.validation_error = PermissionError(13, 'Permission denied', port)
            context.powers.append(power)
            return power

        def make_provider(ecodes, axis, rz, overrides):
            provider = monitor.EvdevActivityProvider(ecodes, axis, rz, overrides)
            provider.seed = Mock(wraps=provider.seed)
            context.providers.append(provider)
            return provider

        def make_timer(now, timeout):
            context.timer = timer_class(now, timeout)
            return context.timer

        class ReceiverObject:
            def __init__(self, *args):
                if args[1] == '/net/local/CecActivity':
                    context.receiver = self
                else:
                    context.browser_receiver = self

        def timeout_add(interval, callback):
            self.assertNotIn(interval, context.callbacks, 'Duplicate monitoring loop')
            context.callbacks[interval] = callback
            return interval

        def make_worker(*args, **kwargs):
            if inventory is not None and args[0][-1].endswith('equipment.py'):
                kwargs['stdout'].write(json.dumps(inventory))
                kwargs['stdout'].flush()
            worker = Mock(returncode=0)
            worker.poll.return_value = None
            worker.communicate.return_value = ('', '')
            worker.command = args[0]
            context.workers.append(worker)
            return worker

        service = SimpleNamespace(Object=ReceiverObject, BusName=Mock(),
                                  method=lambda *args, **kwargs: lambda method: method)
        dbus = SimpleNamespace(service=service, SessionBus=Mock(), DBusException=RuntimeError)
        loop = Mock()
        loop.run.side_effect = lambda: scenario(context)
        glib = SimpleNamespace(MainLoop=lambda: loop, timeout_add=timeout_add)
        modules = {
            'dbus': dbus, 'dbus.service': service, 'dbus.mainloop': SimpleNamespace(),
            'dbus.mainloop.glib': SimpleNamespace(DBusGMainLoop=Mock()),
            'gi': SimpleNamespace(), 'gi.repository': SimpleNamespace(GLib=glib),
            'evdev': SimpleNamespace(InputDevice=open_input, ecodes=SimpleNamespace(
                EV_ABS=3, EV_KEY=1, EV_SYN=0, SYN_DROPPED=3, SYN_REPORT=0,
                ABS_RZ=2, ABS_MT_SLOT=47, ABS={})),
        }
        args = SimpleNamespace(
            target=config['target_output'], timeout_seconds=config['timeout_seconds'],
            mapping_ttl=config['mapping_ttl_seconds'], device=config['devices'],
            mute_label=config['mute_labels'], cec=config['cec_enabled'],
            cec_port=config['cec_port'], kde_timeout=config['kde_timeout'],
            require_snapshot=config['require_snapshot'],
            consider_input_devices=config['consider_input_devices'],
            mouse_output=config['mouse_output'],
            mouse_outputs=config['mouse_outputs'],
            firefox_audio_blocks_standby=config['firefox_audio_blocks_standby'],
            idle_inhibition_apps=config['idle_inhibition_apps'],
            force_inhibition_apps=config['force_inhibition_apps'],
            axis_deadzone_percent=config['axis_deadzone_percent'],
            rz_deadzone_percent=config['rz_deadzone_percent'],
            device_axis_deadzones=config['device_axis_deadzones'], config=str(path))
        with patch.dict(sys.modules, modules), \
                patch.object(monitor.selectors, 'DefaultSelector', side_effect=make_selector), \
                patch.object(monitor.subprocess, 'Popen', side_effect=make_worker), \
                patch.object(monitor.subprocess, 'run', side_effect=AssertionError('No restart or CEC command')), \
                patch.object(monitor, 'input_permission_help',
                             side_effect=lambda error: {'message': str(error), 'command': ''}), \
                patch.object(monitor, 'log'), \
                patch.object(monitor.time, 'monotonic', side_effect=lambda: context.now), \
                patch.object(monitor, 'KdeTimeout', side_effect=lambda: Mock(
                    poll=Mock(return_value=None), value=plasma_timeout_seconds, next_read=0)), \
                patch.object(monitor, 'Timer', side_effect=make_timer):
            context.args = args
            self.assertEqual(monitor.run(args, cec_backend_factory=make_power,
                                         activity_provider_factory=make_provider), 0)
        self.assertEqual(set(context.callbacks), {100, 500})
        self.assertTrue(all(selector.closed for selector in context.selectors))
        self.assertTrue(all(device.closed for device in context.inputs))
        return context

    @staticmethod
    def config(receiver):
        return json.loads(receiver.GetConfig())

    def apply(self, receiver, **changes):
        return json.loads(receiver.ApplySettings(json.dumps({
            **self.config(receiver), **changes})))

    def test_add_remove_retain_inputs_and_persist_in_same_process(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'

            def scenario(context):
                receiver = context.receiver
                initial_pid = json.loads(receiver.GetStatus())['process_id']
                keyboard = context.inputs[0]
                response = self.apply(receiver, devices=['/mock/keyboard', '/mock/mouse'])
                self.assertTrue(response['applied_live'])
                self.assertEqual(len(context.inputs), 2)
                self.assertFalse(keyboard.closed)
                self.assertIs(context.selectors[-1].devices[keyboard.fd], keyboard)
                self.assertTrue(context.selectors[0].closed)
                mouse = context.inputs[-1]
                self.apply(receiver, devices=['/mock/mouse'])
                self.assertTrue(keyboard.closed)
                self.assertFalse(mouse.closed)
                self.assertEqual(len(context.inputs), 2)
                self.assertIs(context.selectors[-1].devices[mouse.fd], mouse)
                self.assertEqual(load_config(path)['devices'], ['/mock/mouse'])
                self.assertEqual(json.loads(receiver.GetStatus())['process_id'], initial_pid)
                self.assertIs(context.receiver, receiver)
                self.assertTrue(context.callbacks[100]())

            self.run_service(path, scenario)
            self.run_service(path, lambda context: self.assertEqual(
                self.config(context.receiver)['devices'], ['/mock/mouse']),
                initial=load_config(path))

    def test_input_toggle_and_mouse_output_apply_live_and_survive_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'

            def scenario(context):
                receiver = context.receiver
                keyboard = context.inputs[0]
                self.apply(receiver, consider_input_devices=False, mouse_output='DP-9')
                self.assertTrue(keyboard.closed)
                self.assertEqual(self.config(receiver)['devices'], ['/mock/keyboard'])
                context.now = 10
                receiver.Report('Mouse-activity: HDMI-A-2')
                self.assertNotEqual(context.timer.last, 10)
                receiver.Report('Mouse-activity: DP-9')
                self.assertEqual(context.timer.last, 10)
                context.denied.add('/mock/keyboard')
                with self.assertRaisesRegex(RuntimeError, 'previous configuration retained'):
                    self.apply(receiver, consider_input_devices=True)
                self.assertFalse(self.config(receiver)['consider_input_devices'])
                context.denied.clear()
                self.apply(receiver, consider_input_devices=True)
                self.assertEqual(len(context.inputs), 2)

            self.run_service(path, scenario)
            saved = load_config(path)
            self.assertTrue(saved['consider_input_devices'])
            self.assertEqual(saved['mouse_output'], 'DP-9')
            self.run_service(path, lambda context: self.assertEqual(
                self.config(context.receiver)['mouse_output'], 'DP-9'), initial=saved)

            saved['consider_input_devices'] = False
            save_config(path, {'schema_version': 1, **saved})
            self.run_service(path, lambda context: self.assertEqual(context.inputs, []),
                             initial=load_config(path), fail_inputs=['/mock/keyboard'])

    def test_firefox_audio_toggle_applies_live_and_uses_mouse_display(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'

            def scenario(context):
                receiver = context.receiver
                self.apply(receiver, firefox_audio_blocks_standby=True)
                self.apply(receiver, mouse_outputs=['DP-2', 'DP-9'])
                receiver.Report('Firefox-snapshot: ' + json.dumps([
                    {'title': 'Video — Mozilla Firefox', 'output': 'DP-9'}]))
                receiver.Report('Firefox-media-snapshot: ' + json.dumps({
                    'version': 1, 'windows': [{
                        'window_id': 1, 'active_title': 'Video',
                        'tabs': [{'audible': True, 'muted': False}],
                    }]}))
                receiver.Report('Fokus: DP-9')
                self.assertTrue(context.callbacks[100]())
                self.assertTrue(json.loads(receiver.GetStatus())['playback_active'])
                self.apply(receiver, mouse_outputs=['DP-2'])
                self.assertTrue(context.callbacks[100]())
                self.assertFalse(json.loads(receiver.GetStatus())['playback_active'])
                self.apply(receiver, mouse_outputs=[])
                self.assertTrue(context.callbacks[100]())
                self.assertFalse(json.loads(receiver.GetStatus())['playback_active'])
                self.apply(receiver, mouse_outputs=['DP-2', 'DP-9'])
                self.apply(receiver, firefox_audio_blocks_standby=False)
                self.assertTrue(context.callbacks[100]())
                self.assertFalse(json.loads(receiver.GetStatus())['playback_active'])
                self.assertIsNone(json.loads(receiver.GetStatus())['fail_safe_reason'])
                self.assertFalse(load_config(path)['firefox_audio_blocks_standby'])
                self.apply(receiver, firefox_audio_blocks_standby=True)
                self.assertTrue(context.callbacks[100]())
                self.assertTrue(json.loads(receiver.GetStatus())['playback_active'])

            self.run_service(path, scenario)

    def test_firefox_scan_only_runs_when_enabled_and_discards_old_worker(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'

            def scenario(context):
                receiver = context.receiver
                self.assertTrue(context.callbacks[100]())
                self.assertEqual(context.workers, [])
                self.assertEqual(json.loads(receiver.GetStatus())['scan_status'],
                                 'Firefox audio detection disabled')
                self.apply(receiver, firefox_audio_blocks_standby=True)
                self.assertTrue(context.callbacks[100]())
                old_worker = context.workers[-1]
                self.apply(receiver, firefox_audio_blocks_standby=False)
                self.apply(receiver, firefox_audio_blocks_standby=True)
                self.assertTrue(context.callbacks[100]())
                old_worker.kill.assert_called_once()
                old_worker.communicate.assert_called_once()
                self.assertIsNot(context.workers[-1], old_worker)
                self.apply(receiver, firefox_audio_blocks_standby=False)
                self.assertTrue(context.callbacks[100]())
                context.workers[-1].kill.assert_called_once()
                self.assertEqual(json.loads(receiver.GetStatus())['scan_status'],
                                 'Firefox audio detection disabled')

            self.run_service(path, scenario)

    def test_chromium_audio_blocks_only_selected_browser_and_display(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'

            def scenario(context):
                receiver = context.receiver
                self.apply(receiver, chromium_audio_blocks_standby=['chromium'],
                           mouse_outputs=['TV'])
                receiver.Report('Desktop-snapshot: ' + json.dumps([
                    {'pid': 42, 'desktop': 'org.chromium.Chromium',
                     'class': 'chromium', 'title': 'Video - Chromium', 'output': 'TV'}]))
                receiver.Report('Fokus: TV')
                self.assertTrue(context.callbacks[100]())
                status = json.loads(receiver.GetStatus())
                self.assertIn('unavailable', status['chromium_audio_errors']['chromium'])
                context.browser_receiver.Report(json.dumps({
                    'browser': 'chromium', 'instance': 'a' * 32, 'version': 1,
                    'windows': [{'window_id': 1, 'active_title': 'Video',
                                 'tabs': [{'audible': True, 'muted': False}]}]}))
                self.assertTrue(context.callbacks[100]())
                status = json.loads(receiver.GetStatus())
                self.assertEqual(status['chromium_audio_errors'], {})
                self.assertIn('Chromium', status['fail_safe_reason'])
                self.assertTrue(any(item['app'] == 'Chromium' and item['reason'] == 'Audio'
                                    for item in status['blocking_apps']))
                self.apply(receiver, chromium_audio_blocks_standby=[])
                self.assertTrue(context.callbacks[100]())
                self.assertFalse(any(item['app'] == 'Chromium'
                                     for item in json.loads(receiver.GetStatus())['blocking_apps']))

            with patch.object(monitor, 'firefox_window_snapshot', return_value='[]'), \
                    patch.object(monitor, 'ChromiumMedia',
                                 return_value=ChromiumMedia(read_exe=lambda _: '/usr/bin/unrelated')):
                self.run_service(path, scenario)

    def test_video_only_settings_apply_live_and_reject_unknown_video(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'

            def scenario(context):
                receiver = context.receiver
                self.apply(receiver, firefox_video_blocks_standby=True,
                           mouse_outputs=['TV'])
                receiver.Report('Firefox-snapshot: ' + json.dumps([
                    {'title': 'Video — Mozilla Firefox', 'output': 'TV'}]))
                receiver.Report('Fokus: TV')
                snapshot = {'version': 1, 'windows': [{
                    'window_id': 1, 'active_title': 'Video',
                    'tabs': [{'audible': True, 'muted': False, 'video': False}],
                }]}
                receiver.Report('Firefox-media-snapshot: ' + json.dumps(snapshot))
                self.assertTrue(context.callbacks[100]())
                status = json.loads(receiver.GetStatus())
                self.assertIsNone(status['fail_safe_reason'])
                snapshot['windows'][0]['tabs'][0].update(
                    audible=False, muted=True, video=True)
                receiver.Report('Firefox-media-snapshot: ' + json.dumps(snapshot))
                self.assertTrue(context.callbacks[100]())
                status = json.loads(receiver.GetStatus())
                self.assertTrue(any(item['reason'] == 'Video'
                                    for item in status['blocking_apps']))
                snapshot['windows'][0]['tabs'].append(
                    {'audible': False, 'muted': False, 'video': None})
                receiver.Report('Firefox-snapshot: ' + json.dumps([
                    {'title': 'Video — Mozilla Firefox', 'output': 'TV'},
                    {'title': 'Unreported window — Mozilla Firefox', 'output': 'TV'},
                ]))
                receiver.Report('Firefox-media-snapshot: ' + json.dumps(snapshot))
                self.assertTrue(context.callbacks[100]())
                status = json.loads(receiver.GetStatus())
                self.assertIn('Mozilla Firefox — Video', status['fail_safe_reason'])
                self.assertTrue(any(item['reason'] == 'Video'
                                    for item in status['blocking_apps']))
                snapshot['windows'][0]['tabs'].pop()
                snapshot['windows'][0]['tabs'][0]['video'] = None
                receiver.Report('Firefox-media-snapshot: ' + json.dumps(snapshot))
                self.assertTrue(context.callbacks[100]())
                self.assertIn('unknown', json.loads(receiver.GetStatus())['fail_safe_reason'])
                self.apply(receiver, firefox_video_blocks_standby=False)
                self.assertTrue(context.callbacks[100]())
                self.assertIsNone(json.loads(receiver.GetStatus())['fail_safe_reason'])

            self.run_service(path, scenario)

    def test_chromium_video_only_blocks_playback_and_unknown_without_audio(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'

            def scenario(context):
                receiver = context.receiver
                self.apply(receiver, chromium_video_blocks_standby=['chromium'],
                           mouse_outputs=['TV'])
                receiver.Report('Desktop-snapshot: ' + json.dumps([
                    {'pid': 42, 'desktop': 'chromium', 'class': 'chromium',
                     'title': 'Video - Chromium', 'output': 'TV'}]))
                receiver.Report('Fokus: TV')
                snapshot = {'browser': 'chromium', 'instance': 'a' * 32, 'version': 1,
                            'windows': [{'window_id': 1, 'active_title': 'Video',
                                         'tabs': [{'audible': True, 'muted': False,
                                                   'video': False}]}]}
                context.browser_receiver.Report(json.dumps(snapshot))
                self.assertTrue(context.callbacks[100]())
                self.assertIsNone(json.loads(receiver.GetStatus())['fail_safe_reason'])
                snapshot['windows'][0]['tabs'][0].update(
                    audible=False, muted=True, video=True)
                context.browser_receiver.Report(json.dumps(snapshot))
                self.assertTrue(context.callbacks[100]())
                status = json.loads(receiver.GetStatus())
                self.assertTrue(any(item['reason'] == 'Video'
                                    for item in status['blocking_apps']))
                snapshot['windows'][0]['tabs'][0]['video'] = None
                context.browser_receiver.Report(json.dumps(snapshot))
                self.assertTrue(context.callbacks[100]())
                status = json.loads(receiver.GetStatus())
                self.assertIn('unknown', status['chromium_video_errors']['chromium'])

            with patch.object(monitor, 'firefox_window_snapshot', return_value='[]'), \
                    patch.object(monitor, 'ChromiumMedia',
                                 return_value=ChromiumMedia(read_exe=lambda _: '/usr/bin/unrelated')):
                self.run_service(path, scenario)

    def test_multiple_mouse_displays_and_empty_selection_apply_live(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'

            def scenario(context):
                receiver = context.receiver
                self.apply(receiver, mouse_outputs=['DP-1', 'DP-2'])
                for now, output in ((10, 'DP-1'), (20, 'DP-2')):
                    context.now = now
                    receiver.Report('Mouse-activity: ' + output)
                    self.assertEqual(context.timer.last, now)
                context.now = 30
                receiver.Report('Mouse-activity: HDMI-A-2')
                self.assertEqual(context.timer.last, 20)
                self.apply(receiver, mouse_outputs=[])
                context.now = 40
                receiver.Report('Mouse-activity: DP-1')
                receiver.Report('TV-aktivitet: mus')
                self.assertEqual(context.timer.last, 30)
                self.assertEqual(load_config(path)['mouse_outputs'], [])

            self.run_service(path, scenario)
            self.run_service(path, lambda context: self.assertEqual(
                self.config(context.receiver)['mouse_outputs'], []),
                initial=load_config(path))

    def test_atspi_audio_uses_all_selected_displays(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'

            def scenario(context):
                receiver = context.receiver
                self.apply(receiver, mouse_outputs=['DP-1', 'DP-2'])
                receiver.Report('Firefox-snapshot: ' + json.dumps([
                    {'title': 'Video — Mozilla Firefox', 'output': 'DP-2'}]))
                receiver.Report('Fokus: DP-1')
                self.assertTrue(context.callbacks[100]())
                worker = context.workers[-1]
                worker.poll.return_value = 0
                worker.communicate.return_value = (json.dumps({
                    'ok': True, 'frames': [{
                        'title': 'Video — Mozilla Firefox', 'audio': True,
                    }]}), '')
                self.assertTrue(context.callbacks[100]())
                self.assertTrue(json.loads(receiver.GetStatus())['playback_active'])
                self.apply(receiver, mouse_outputs=['DP-1'])
                self.assertTrue(context.callbacks[100]())
                self.assertFalse(json.loads(receiver.GetStatus())['playback_active'])

            self.run_service(path, scenario, initial={'firefox_audio_blocks_standby': True})

    def test_idle_inhibition_selection_changes_standby_and_reports_reason(self):
        inventory = {'outputs': [], 'adapters': [], 'inputs': [], 'errors': [],
                     'apps': [{'id': 'player.desktop', 'name': 'Player'}],
                     'apps_error': None}
        plasma = Mock(requests=[{'kind': 'idle', 'app': 'player',
                                 'reason': 'Playing', 'mode': 'block'}])
        plasma.health.return_value = None
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(monitor, 'PlasmaInhibitions', return_value=plasma), \
                patch.object(monitor, 'firefox_window_snapshot', return_value='[]'):
            path = Path(directory) / 'config.json'

            def scenario(context):
                receiver = context.receiver
                context.callbacks[500]()
                context.workers[-1].poll.return_value = 0
                context.callbacks[500]()
                receiver.Report('Desktop-snapshot: ' + json.dumps([
                    {'pid': 123, 'title': 'Player', 'desktop': 'player',
                     'class': 'player', 'output': 'DP-9'}]))
                receiver.Report('Fokus: DP-9')
                self.apply(receiver, mouse_outputs=['DP-2', 'DP-9'],
                           firefox_audio_blocks_standby=False,
                           idle_inhibition_apps=['player.desktop'])
                self.assertTrue(context.callbacks[100]())
                status = json.loads(receiver.GetStatus())
                self.assertIn('Playing', status['fail_safe_reason'])
                self.assertEqual(status['blocking_apps'][0]['reason'], 'Playing')
                with self.assertRaisesRegex(RuntimeError, 'Standby blocked'):
                    receiver.RequestPower('off')
                self.apply(receiver, mouse_outputs=['DP-2'])
                self.assertTrue(context.callbacks[100]())
                self.assertEqual(json.loads(receiver.GetStatus())['blocking_apps'], [])
                self.apply(receiver, mouse_outputs=[])
                plasma.health.return_value = 'Plasma unavailable'
                self.assertTrue(context.callbacks[100]())
                self.assertIsNone(json.loads(receiver.GetStatus())['fail_safe_reason'])
                plasma.health.return_value = None
                self.apply(receiver, mouse_outputs=['DP-2', 'DP-9'])
                self.apply(receiver, idle_inhibition_apps=[])
                self.assertTrue(context.callbacks[100]())
                status = json.loads(receiver.GetStatus())
                self.assertIsNone(status['fail_safe_reason'])
                self.assertEqual(status['blocking_apps'], [])
                self.apply(receiver, idle_inhibition_apps=['player.desktop'])
                plasma.health.return_value = 'Plasma unavailable'
                self.assertTrue(context.callbacks[100]())
                self.assertEqual(json.loads(receiver.GetStatus())['fail_safe_reason'],
                                 'Plasma unavailable')

            self.run_service(path, scenario, inventory=inventory,
                             initial={'cec_enabled': True})

    def test_force_inhibit_tracks_windows_and_persists_observed_apps(self):
        inventory = {'outputs': [], 'adapters': [], 'inputs': [], 'errors': [],
                    'apps': [{'id': 'player.desktop', 'name': 'Player'}],
                    'apps_error': None}
        plasma = Mock(requests=[{'kind': 'idle', 'app': 'Player',
                                'reason': 'Playing', 'mode': 'block'}])
        plasma.health.return_value = None
        with tempfile.TemporaryDirectory() as directory, \
               patch.object(monitor, 'PlasmaInhibitions', return_value=plasma), \
               patch.object(monitor, 'firefox_window_snapshot', return_value='[]'):
            path = Path(directory) / 'config.json'

            def scenario(context):
               receiver = context.receiver
               context.callbacks[500]()
               context.workers[-1].poll.return_value = 0
               context.callbacks[500]()
               receiver.Report('Desktop-snapshot: ' + json.dumps([
                   {'pid': 123, 'title': 'Player', 'desktop': 'player',
                    'class': 'player', 'output': 'DP-9'}]))
               self.apply(receiver, mouse_outputs=['DP-9'], firefox_audio_blocks_standby=False,
                          force_inhibition_apps=['player.desktop'])
               context.callbacks[100]()
               status = json.loads(receiver.GetStatus())
               self.assertEqual(status['observed_apps'][0]['id'], 'player.desktop')
               self.assertIn('Force inhibit', status['blocking_apps'][0]['reason'])
               with self.assertRaisesRegex(RuntimeError, 'Standby blocked'):
                   receiver.RequestPower('off')
               self.apply(receiver, mouse_outputs=['DP-2'])
               context.callbacks[100]()
               self.assertEqual(json.loads(receiver.GetStatus())['blocking_apps'], [])
               receiver.Report('Desktop-snapshot: []')
               context.callbacks[100]()
               self.assertEqual(json.loads(receiver.GetStatus())['blocking_apps'], [])
               context.now += 16
               context.callbacks[100]()
               self.assertIn('Window status unavailable',
                             json.loads(receiver.GetStatus())['blocking_apps'][0]['reason'])

            self.run_service(path, scenario, inventory=inventory, initial={'cec_enabled': True})
            self.assertEqual(json.loads((path.parent / 'observed-inhibitors.json').read_text()),
                            ['Player'])
            saved = load_config(path)
            self.assertEqual(saved['force_inhibition_apps'], ['player.desktop'])
            plasma.requests = []

            def after_restart(context):
                context.callbacks[500]()
                context.workers[-1].poll.return_value = 0
                context.callbacks[500]()
                context.receiver.Report('Desktop-snapshot: ' + json.dumps([
                    {'pid': 123, 'title': 'Player', 'desktop': 'player',
                     'class': 'player', 'output': 'DP-2'}]))
                context.callbacks[100]()
                status = json.loads(context.receiver.GetStatus())
                self.assertEqual(status['observed_apps'][0]['id'], 'player.desktop')
                self.assertIn('Force inhibit', status['blocking_apps'][0]['reason'])

            self.run_service(path, after_restart, inventory=inventory, initial=saved)

    def test_input_and_disk_failure_roll_back_without_losing_monitoring(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'

            def scenario(context):
                receiver = context.receiver
                before = self.config(receiver)
                save_config(path, before)
                original_bytes = path.read_bytes()
                keyboard = context.inputs[0]
                old_selector = context.selectors[0]
                for disk_failure in (False, True):
                    manager = patch.object(monitor, 'save_config', side_effect=OSError('Disk full')) if disk_failure else patch.dict({})
                    with manager, self.assertRaisesRegex(RuntimeError, 'previous configuration retained'):
                        self.apply(receiver, devices=['/mock/keyboard', '/mock/new',
                                                      '/mock/bad'] if not disk_failure else
                                   ['/mock/keyboard', '/mock/other'])
                    self.assertFalse(keyboard.closed)
                    self.assertFalse(old_selector.closed)
                    self.assertEqual(path.read_bytes(), original_bytes)
                    self.assertEqual(self.config(receiver), before)
                    self.assertTrue(context.inputs[-1].closed)
                    self.assertTrue(context.selectors[-1].closed)
                    self.assertTrue(context.callbacks[100]())
                self.assertIn('Disk full', json.loads(receiver.GetStatus())['settings_error'])

            self.run_service(path, scenario, fail_inputs=['/mock/bad'])

    def test_runtime_numeric_display_labels_and_adapter_changes_are_live(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'

            def scenario(context):
                receiver = context.receiver
                receiver.Report('Fokus: DP-9')
                response = self.apply(
                    receiver, target_output='DP-9', timeout_seconds=120, kde_timeout=False,
                    axis_deadzone_percent=10, rz_deadzone_percent=15,
                    mapping_ttl_seconds=42, mute_labels=['Mute audio'],
                    cec_enabled=True, cec_port='/mock/new-cec')
                self.assertTrue(context.powers[-1].validated)
                self.assertEqual(context.powers[-1].port, '/mock/new-cec')
                status = json.loads(receiver.GetStatus())
                self.assertEqual(status['target_output'], 'DP-9')
                self.assertEqual(status['adapter'], '/mock/new-cec')
                self.assertTrue(response['config']['require_snapshot'])
                self.assertEqual(load_config(path)['timeout_seconds'], 120)
                self.assertEqual(context.timer.timeout, 120)
                self.assertEqual(context.providers[-1].axis_deadzone_percent, 10)
                self.assertEqual(context.providers[-1].rz_deadzone_percent, 15)
                axes = context.providers[-1].seed(context.inputs[0])
                self.assertEqual(axes[0].threshold, 100)
                self.assertEqual(axes[2].threshold, 150)
                self.apply(receiver, device_axis_deadzones={'/mock/keyboard': {'0': 18}})
                self.assertEqual(load_config(path)['device_axis_deadzones'],
                                 {'/mock/keyboard': {'0': 18}})
                self.assertEqual(context.providers[-1].seed(context.inputs[0])[0].threshold, 180)
                context.inputs[0].events = [SimpleNamespace(type=3, code=0, value=700)]
                context.now = 2
                self.assertTrue(context.callbacks[100]())
                self.assertEqual(context.timer.last, 2)
                self.assertTrue(context.callbacks[100]())
                self.assertEqual(context.args.mute_label, ['Mute audio'])
                self.assertFalse(context.inputs[0].closed)
                for power in context.powers:
                    power.request.assert_not_called()
                self.apply(receiver, timeout_seconds=None, kde_timeout=True)
                self.assertIsNone(context.timer.timeout)
                self.assertTrue(context.callbacks[100]())
                self.apply(receiver, kde_timeout=False, devices=[])
                self.assertTrue(context.inputs[0].closed)
                self.assertEqual(load_config(path)['devices'], [])

            self.run_service(path, scenario)
            fresh = self.run_service(path, lambda context: self.assertEqual(context.inputs, []),
                                     initial=load_config(path))
            self.assertEqual(fresh.inputs, [])

    def test_status_reports_fetched_plasma_timeout(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'

            def scenario(context):
                self.assertTrue(context.callbacks[100]())
                status = json.loads(context.receiver.GetStatus())
                self.assertTrue(status['plasma_timeout_read'])
                self.assertEqual(status['plasma_timeout_seconds'], 420)

            self.run_service(
                path, scenario, initial={'kde_timeout': True},
                plasma_timeout_seconds=420)

    def test_seed_or_registration_failure_retains_previous_resources(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'

            def scenario(context):
                receiver = context.receiver
                before = self.config(receiver)
                save_config(path, before)
                for fail_seed in (False, True):
                    context.fail_register = None if fail_seed else '/mock/new'
                    manager = (
                        patch.object(monitor.EvdevActivityProvider, 'seed',
                                     side_effect=OSError('Input metadata failed'))
                        if fail_seed else nullcontext())
                    with manager, self.assertRaisesRegex(RuntimeError, 'previous configuration retained'):
                        self.apply(receiver, devices=['/mock/keyboard', '/mock/new'])
                    self.assertFalse(context.inputs[0].closed)
                    self.assertTrue(context.inputs[-1].closed)
                    self.assertFalse(context.selectors[0].closed)
                    self.assertTrue(context.selectors[-1].closed)
                    self.assertEqual(self.config(receiver), before)
                    self.assertEqual(load_config(path)['devices'], before['devices'])

            self.run_service(path, scenario)

    def test_adapter_validation_and_recovery_state_reject_without_commit(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'

            def scenario(context):
                receiver = context.receiver
                before = self.config(receiver)
                save_config(path, before)
                original = path.read_bytes()
                with self.assertRaisesRegex(RuntimeError, 'Permission denied'):
                    self.apply(receiver, cec_port='/mock/bad-cec', devices=['/mock/new'])
                self.assertFalse(context.inputs[0].closed)
                self.assertTrue(context.inputs[-1].closed)
                old_power = context.powers[0]
                for attribute, value in (('process', Mock()), ('pending', 'off'), ('may_be_off', True)):
                    owner = old_power.state_machine if attribute == 'may_be_off' else old_power
                    setattr(owner, attribute, value)
                    with self.assertRaisesRegex(RuntimeError, 'wake recovery'):
                        self.apply(receiver, cec_port='/mock/other-cec')
                    setattr(owner, attribute, None if attribute != 'may_be_off' else False)
                self.assertEqual(path.read_bytes(), original)
                self.assertEqual(self.config(receiver), before)
                for power in context.powers:
                    power.request.assert_not_called()

            self.run_service(path, scenario, initial={'cec_enabled': True},
                             fail_adapter='/mock/bad-cec')

    def test_configuration_only_recovers_and_runtime_disconnect_can_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'

            def scenario(context):
                receiver = context.receiver
                self.assertEqual(json.loads(receiver.GetStatus())['service'], 'configuration-only')
                callback = context.callbacks[100]
                self.assertTrue(callback())
                power = context.powers[0]
                power.pending = 'on'
                power.poll.side_effect = OSError('Recovery transport unavailable')
                self.assertTrue(callback())
                self.assertIn('Recovery transport unavailable',
                              json.loads(receiver.GetStatus())['settings_error'])
                power.poll.side_effect = None
                power.pending = None
                context.denied.clear()
                self.apply(receiver, devices=['/mock/working'])
                self.assertEqual(json.loads(receiver.GetStatus())['service'], 'running')
                self.assertIs(context.callbacks[100], callback)
                self.assertTrue(callback())
                context.inputs[-1].failure = OSError('Input unplugged')
                self.assertTrue(callback())
                self.assertEqual(json.loads(receiver.GetStatus())['service'], 'configuration-only')
                self.apply(receiver, devices=['/mock/replacement'])
                self.assertEqual(json.loads(receiver.GetStatus())['service'], 'running')
                self.assertTrue(callback())
                self.assertEqual(load_config(path)['devices'], ['/mock/replacement'])

            self.run_service(path, scenario, fail_inputs=['/mock/keyboard'],
                             initial={'cec_enabled': True})

    def test_alias_change_retains_open_device_and_deduplicates_same_input(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / 'config.json'
            event = root / 'event'
            event.touch()
            alias = root / 'keyboard-alias'
            alias.symlink_to(event)

            def scenario(context):
                original = context.inputs[0]
                response = self.apply(context.receiver, devices=[str(alias), str(event)])
                self.assertEqual(response['config']['devices'], [str(alias)])
                self.assertEqual(len(context.inputs), 1)
                self.assertFalse(original.closed)
                self.assertIs(context.selectors[-1].devices[original.fd], original)
                self.assertEqual(load_config(path)['devices'], [str(alias)])

            self.run_service(path, scenario, initial={'devices': [str(event)]})

    def test_old_scan_is_discarded_after_live_label_change(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'

            def scenario(context):
                self.assertTrue(context.callbacks[100]())
                original_worker = context.workers[0]
                self.apply(context.receiver, mute_labels=['Mute audio'])
                original_worker.poll.return_value = 0
                original_worker.communicate.return_value = ('Not a valid scan', '')
                self.assertTrue(context.callbacks[100]())
                status = json.loads(context.receiver.GetStatus())
                self.assertIn('updated mute-tab labels', status['scan_status'])
                self.assertEqual(context.workers[-1].command[-2:], ['--mute-label', 'Mute audio'])
                original_worker.communicate.assert_called_once()

            self.run_service(path, scenario, initial={'firefox_audio_blocks_standby': True})

    def test_browser_extension_reports_are_visible_without_cec_hardware(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'

            def scenario(context):
                initial = json.loads(context.receiver.GetStatus())
                self.assertFalse(initial['cec_enabled'])
                self.assertFalse(initial['browser_extension_reports']['firefox'])
                self.assertFalse(initial['browser_extension_reports']['chromium'])

                firefox_snapshot = {
                    'version': 1,
                    'windows': [{
                        'window_id': 1, 'active_title': 'Test page',
                        'tabs': [{'audible': False, 'muted': False, 'video': False}],
                    }],
                }
                context.receiver.Report(
                    'Firefox-media-snapshot: ' + json.dumps(firefox_snapshot))
                context.browser_receiver.Report(json.dumps({
                    'version': 1, 'browser': 'chromium', 'instance': 'a' * 32,
                    'windows': firefox_snapshot['windows'],
                }))
                connected = json.loads(context.receiver.GetStatus())
                self.assertTrue(connected['browser_extension_reports']['firefox'])
                self.assertTrue(connected['browser_extension_reports']['chromium'])
                self.assertFalse(connected['browser_extension_reports']['chrome'])

                context.now = 16
                stale = json.loads(context.receiver.GetStatus())
                self.assertFalse(stale['browser_extension_reports']['firefox'])
                self.assertFalse(stale['browser_extension_reports']['chromium'])

            self.run_service(path, scenario, initial={
                'cec_enabled': False, 'cec_port': '', 'devices': [],
            })

    def test_cec_adapter_probe_opens_nonblocking_and_never_sends_commands(self):
        with patch.object(monitor.os, 'open', return_value=42) as opened, \
                patch.object(monitor.os, 'fstat', return_value=SimpleNamespace(st_mode=0o20660)), \
                patch.object(monitor.os, 'close') as closed, \
                patch.object(monitor.subprocess, 'run', side_effect=AssertionError('No CEC command')):
            monitor.CecPower('/mock/adapter').validate_port()
        opened.assert_called_once_with(
            '/mock/adapter', os.O_RDWR | os.O_NONBLOCK | os.O_NOCTTY)
        closed.assert_called_once_with(42)
        with patch.object(monitor.os, 'open', return_value=43), \
                patch.object(monitor.os, 'fstat', return_value=SimpleNamespace(st_mode=0o100600)), \
                patch.object(monitor.os, 'close') as closed:
            with self.assertRaisesRegex(OSError, 'character device'):
                monitor.CecPower('/mock/regular-file').validate_port()
        closed.assert_called_once_with(43)


if __name__ == '__main__':
    unittest.main(verbosity=2)
