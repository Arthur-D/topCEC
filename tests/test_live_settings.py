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
    def run_service(self, path, scenario, *, initial=None, fail_inputs=(), fail_adapter=None,
                    plasma_timeout_seconds='unread'):
        config = {**DEFAULT_CONFIG, 'devices': ['/mock/keyboard'], 'cec_port': '/mock/cec',
                  **(initial or {})}
        context = SimpleNamespace(receiver=None, callbacks={}, inputs=[], selectors=[],
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
                context.receiver = self

        def timeout_add(interval, callback):
            self.assertNotIn(interval, context.callbacks, 'Duplicate monitoring loop')
            context.callbacks[interval] = callback
            return interval

        def make_worker(*args, **kwargs):
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

            self.run_service(path, scenario)

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
