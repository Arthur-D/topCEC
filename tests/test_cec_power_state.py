"""Hardware-independent tests for CEC power-state transitions."""
# SPDX-License-Identifier: GPL-3.0-or-later
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'cec-tv'))
from cec_power_state import CecPowerStateMachine, PowerState


class CecPowerStateChecks(unittest.TestCase):
    def setUp(self):
        self.machine = CecPowerStateMachine()

    def test_confirmed_power_transitions(self):
        self.assertEqual(self.machine.state, PowerState.UNKNOWN)
        self.assertFalse(self.machine.may_be_off)

        self.assertTrue(self.machine.begin('off'))
        self.assertEqual(self.machine.state, PowerState.TURNING_OFF)
        self.assertTrue(self.machine.may_be_off)
        self.machine.confirm('standby')
        self.assertEqual(self.machine.state, PowerState.STANDBY)
        self.assertTrue(self.machine.may_be_off)
        self.assertIsNone(self.machine.fault)

        self.assertTrue(self.machine.begin('on'))
        self.assertEqual(self.machine.state, PowerState.TURNING_ON)
        self.machine.confirm('on')
        self.assertEqual(self.machine.state, PowerState.ON)
        self.assertFalse(self.machine.may_be_off)

    def test_failure_blocks_standby_but_allows_wake_recovery(self):
        self.machine.begin('off')
        self.machine.fail('adapter failure', 'off')
        self.assertEqual(self.machine.state, PowerState.FAULT)
        self.assertTrue(self.machine.may_be_off)
        self.assertFalse(self.machine.can_standby)
        self.assertFalse(self.machine.begin('off'))

        self.assertTrue(self.machine.begin('on'))
        self.machine.confirm('on')
        self.assertEqual(self.machine.state, PowerState.ON)
        self.assertTrue(self.machine.can_standby)
        self.assertFalse(self.machine.may_be_off)

    def test_failed_wake_preserves_uncertain_power_state(self):
        self.machine.fail('adapter failure', 'on')
        self.assertEqual(self.machine.state, PowerState.FAULT)
        self.assertTrue(self.machine.may_be_off)
        self.assertFalse(self.machine.can_standby)

    def test_invalid_actions_and_confirmations_are_rejected(self):
        with self.assertRaises(ValueError):
            self.machine.begin('standby')
        with self.assertRaises(ValueError):
            self.machine.confirm('unknown')


if __name__ == '__main__':
    unittest.main(verbosity=2)
