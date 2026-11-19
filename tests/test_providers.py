"""Hardware-free tests for monitor provider interfaces."""
# SPDX-License-Identifier: GPL-3.0-or-later
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'cec-tv'))
from monitor import (CecPower, EvdevActivityProvider, FirefoxMediaProvider,
                     SunshinePointer, SunshinePointerDevice)
from providers import ActivityProvider, CecBackend, MediaProvider


class ProviderInterfaceChecks(unittest.TestCase):
    def test_existing_providers_satisfy_structural_interfaces(self):
        provider = EvdevActivityProvider(
            SimpleNamespace(ABS_RZ=2, ABS_MT_SLOT=47, EV_ABS=3, ABS={}),
            2.0, 5.0)
        media = FirefoxMediaProvider()
        power = CecPower('MOCK')
        self.assertIsInstance(provider, ActivityProvider)
        self.assertIsInstance(media, MediaProvider)
        self.assertIsInstance(power, CecBackend)

    def test_evdev_provider_preserves_focus_and_deadzone_rules(self):
        ecodes = SimpleNamespace(ABS_RZ=2, ABS_MT_SLOT=47, EV_ABS=3, EV_KEY=1,
                                 ABS={2: 'ABS_RZ', 0: 'ABS_X'})
        provider = EvdevActivityProvider(ecodes, 2.0, 5.0)
        info = lambda value, fuzz=0: SimpleNamespace(
            min=0, max=1000, value=value, fuzz=fuzz)
        device = SimpleNamespace(capabilities=lambda absinfo: {
            ecodes.EV_ABS: [(0, info(100)), (2, info(500)), (47, info(0))]})
        state = {'axes': provider.seed(device)}
        self.assertEqual(set(state['axes']), {0, 2})
        self.assertEqual(state['axes'][2].threshold, 50)
        event = SimpleNamespace(type=ecodes.EV_ABS, code=0, value=200)
        self.assertIsNone(provider.event_activity(state, event, False))
        event.value = 220
        self.assertIn('wheel/pedal', provider.event_activity(state, event, True))
        key = SimpleNamespace(type=ecodes.EV_KEY, value=1)
        self.assertIsNone(provider.event_activity(state, key, False))
        self.assertEqual(provider.event_activity(state, key, True), 'keyboard/wheel')

    def test_axis_overrides_are_per_device_and_preserve_legacy_defaults(self):
        ecodes = SimpleNamespace(ABS_RZ=5, ABS_MT_SLOT=47, EV_ABS=3)
        provider = EvdevActivityProvider(ecodes, 2, 5, {
            '/mock/wheel': {'0': 10, '5': 15},
        })
        info = SimpleNamespace(min=0, max=1000, value=500, fuzz=0)
        device = SimpleNamespace(path='/mock/wheel',
                                 capabilities=lambda absinfo: {3: [(0, info), (5, info)]})
        self.assertEqual(provider.seed(device)[0].threshold, 100)
        self.assertEqual(provider.seed(device)[5].threshold, 150)
        device.path = '/mock/other'
        self.assertEqual(provider.seed(device)[0].threshold, 20)
        self.assertEqual(provider.seed(device)[5].threshold, 50)

    def test_device_aliases_and_current_selection_resolve_to_same_override(self):
        ecodes = SimpleNamespace(ABS_RZ=5, ABS_MT_SLOT=47, EV_ABS=3)
        info = SimpleNamespace(min=0, max=1000, value=500, fuzz=0)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'event0'
            target.touch()
            alias = Path(directory) / 'wheel'
            alias.symlink_to(target)
            provider = EvdevActivityProvider(ecodes, 2, 5, {str(alias): {'0': 12}})
            device = SimpleNamespace(path='/old/missing/path',
                                     capabilities=lambda absinfo: {3: [(0, info)]})
            self.assertEqual(provider.seed(device, str(target))[0].threshold, 120)


class SunshinePointerChecks(unittest.TestCase):
    def setUp(self):
        codes = SimpleNamespace(EV_SYN=0, EV_REL=2, EV_ABS=3, SYN_REPORT=0,
                                SYN_DROPPED=3, REL_X=0, REL_Y=1, ABS_X=0, ABS_Y=1)
        self.pointer = SunshinePointer(Mock(), codes)
        self.pointer.next_scan = float('inf')
        self.device = Mock()
        self.device.name = 'libvirtualhid Mouse (Absolute)'
        self.path = Path('/mock/absolute')
        self.pointer.devices[self.path] = SunshinePointerDevice(self.device)

    def source(self, *events):
        self.device.read.side_effect = [iter(events), BlockingIOError()]
        with patch('monitor.time.time', return_value=100):
            return self.pointer.source()

    def test_source_attributes_recent_absolute_zero_and_excludes_stale_or_future_input(self):
        for stamp, expected in (
                (99.98, 'likely Sunshine input (libvirtualhid Mouse (Absolute), 20 ms before report)'),
                (99.5, 'unknown'), (100.01, 'unknown')):
            with self.subTest(stamp=stamp):
                event = SimpleNamespace(type=3, code=0, value=0, timestamp=lambda: stamp)
                self.assertEqual(self.source(event), expected)

    def test_relative_motion_is_detected_but_overrun_clears_attribution(self):
        motion = SimpleNamespace(type=2, code=1, value=-2, timestamp=lambda: 99.99)
        dropped = SimpleNamespace(type=0, code=3)
        resynced = SimpleNamespace(type=0, code=0)
        self.assertIn('likely Sunshine input', self.source(motion))
        self.assertEqual(self.source(dropped, motion, resynced), 'unknown')
        self.assertIn('likely Sunshine input', self.source(motion))

    def test_disconnected_device_is_optional(self):
        self.device.read.side_effect = OSError('device disconnected')
        self.assertEqual(self.pointer.source(), 'unknown (Sunshine pointer devices unavailable)')
        self.device.close.assert_called_once_with()


if __name__ == '__main__':
    unittest.main(verbosity=2)
