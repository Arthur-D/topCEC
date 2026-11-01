"""Hardware-free tests for monitor provider interfaces."""
# SPDX-License-Identifier: GPL-3.0-or-later
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'cec-tv'))
from monitor import CecPower, EvdevActivityProvider, FirefoxMediaProvider
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
        self.assertIn('ratt/pedal', provider.event_activity(state, event, True))
        key = SimpleNamespace(type=ecodes.EV_KEY, value=1)
        self.assertIsNone(provider.event_activity(state, key, False))
        self.assertEqual(provider.event_activity(state, key, True), 'tastatur/ratt')


if __name__ == '__main__':
    unittest.main(verbosity=2)
