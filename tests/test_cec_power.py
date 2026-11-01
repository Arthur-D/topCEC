"""Hardware-free regression tests for the live CEC coordinator."""
# SPDX-License-Identifier: GPL-3.0-or-later
import json
import os
import signal
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'cec-tv'))
import monitor


class Child:
    def __init__(self):
        self.pid = 123
        self.returncode = None
        self.output = ''

    def poll(self):
        return self.returncode

    def communicate(self):
        return self.output, ''

    def finish(self, state='standby', ok=True):
        self.returncode = 0 if ok else 1
        self.output = json.dumps({
            'ok': ok,
            'state': state,
            'error': 'mock adapter failure',
        })


class CecPowerChecks(unittest.TestCase):
    def setUp(self):
        self.now = [100.0]
        self.children = []
        self.actions = []

        def spawn(args, **kwargs):
            self.actions.append(args[2])
            child = Child()
            self.children.append(child)
            return child

        self.popen = patch.object(monitor.subprocess, 'Popen', side_effect=spawn)
        self.clock = patch.object(monitor.time, 'monotonic',
                                  side_effect=lambda: self.now[0])
        self.popen.start()
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.addCleanup(self.popen.stop)
        self.power = monitor.CecPower('MOCK')

    def test_activity_during_inflight_off_queues_wake(self):
        self.power.request('off')
        self.power.poll()
        with patch.object(os, 'killpg'):
            self.power.activity()
        self.power.poll()
        self.assertEqual(self.actions, ['off'])
        self.assertEqual(self.power.pending, 'on')

        self.children[0].finish()
        self.power.poll()
        self.assertEqual(self.actions, ['off', 'on'])

    def test_activity_cancels_inflight_standby_before_dispatching_wake(self):
        self.power.request('off')
        self.power.poll()
        child = self.children[0]

        def terminate_group(pid, signum):
            self.assertEqual(pid, child.pid)
            self.assertEqual(signum, signal.SIGTERM)
            child.returncode = -signal.SIGTERM

        with patch.object(os, 'killpg', side_effect=terminate_group) as killpg:
            self.power.activity()
        killpg.assert_called_once_with(child.pid, signal.SIGTERM)
        self.assertEqual(self.power.pending, 'on')
        self.power.poll()

        self.assertEqual(self.actions, ['off', 'on'])
        self.assertIsNotNone(self.power.fault)
        self.assertTrue(self.power.may_be_off)
        self.children[1].finish(state='on')
        self.power.poll()
        self.assertIsNone(self.power.fault)
        self.assertFalse(self.power.may_be_off)

    def test_failed_standby_cancellation_keeps_wake_queued_and_reports_fault(self):
        self.power.request('off')
        self.power.poll()
        child = self.children[0]

        with patch.object(os, 'killpg', side_effect=PermissionError('denied')):
            self.power.activity()

        self.assertEqual(self.power.pending, 'on')
        self.assertIn('Could not cancel standby command', self.power.fault)
        self.assertEqual(self.actions, ['off'])
        child.finish()
        self.power.poll()
        self.assertEqual(self.actions, ['off', 'on'])

    def test_failed_off_dispatches_recovery_on_and_blocks_future_off(self):
        self.power.request('off')
        self.power.poll()
        with patch.object(os, 'killpg'):
            self.power.activity()
        self.children[0].finish(ok=False)
        self.power.poll()

        self.assertEqual(self.actions, ['off', 'on'])
        self.assertIsNotNone(self.power.fault)
        self.power.request('off')
        self.power.poll()
        self.assertEqual(self.actions, ['off', 'on'])

    def test_failed_off_without_wake_does_not_send_on(self):
        self.power.request('off')
        self.power.poll()
        self.children[0].finish(ok=False)
        self.power.poll()

        self.assertEqual(self.actions, ['off'])
        self.assertIsNotNone(self.power.fault)
        self.assertTrue(self.power.may_be_off)

        self.power.activity()
        self.power.poll()
        self.assertEqual(self.actions, ['off', 'on'])

    def test_timed_out_off_only_recovers_when_wake_was_requested(self):
        self.power.request('off')
        self.power.poll()
        child = self.children[0]
        with patch.object(os, 'killpg'):
            self.power.activity()
        self.now[0] += monitor.CecPower.OPERATION_TIMEOUT - 0.1
        self.power.poll()
        self.assertEqual(self.actions, ['off'])

        def terminate_group(pid, signum):
            self.assertEqual(pid, child.pid)
            self.assertEqual(signum, signal.SIGKILL)
            child.returncode = -signal.SIGKILL

        with patch.object(os, 'killpg', side_effect=terminate_group) as killpg:
            self.now[0] += 0.1
            self.power.poll()

        killpg.assert_called_once_with(child.pid, signal.SIGKILL)
        self.assertEqual(self.actions, ['off', 'on'])
        self.assertIn('deadline', self.power.fault)

    def test_timed_out_off_without_wake_does_not_send_on(self):
        self.power.request('off')
        self.power.poll()
        child = self.children[0]
        self.now[0] += monitor.CecPower.OPERATION_TIMEOUT

        def terminate_group(pid, signum):
            self.assertEqual(pid, child.pid)
            self.assertEqual(signum, signal.SIGKILL)
            child.returncode = -signal.SIGKILL

        with patch.object(os, 'killpg', side_effect=terminate_group) as killpg:
            self.power.poll()

        killpg.assert_called_once_with(child.pid, signal.SIGKILL)
        self.assertEqual(self.actions, ['off'])
        self.assertIsNotNone(self.power.fault)
        self.assertIn('deadline', self.power.fault)

    def test_timeout_kill_race_uses_child_final_result(self):
        self.power.request('on')
        self.power.poll()
        child = self.children[0]
        child.finish(state='on')
        self.now[0] += monitor.CecPower.OPERATION_TIMEOUT

        with patch.object(os, 'killpg', side_effect=ProcessLookupError):
            self.power.poll()

        self.assertEqual(self.actions, ['on'])
        self.assertIsNone(self.power.fault)
        self.assertFalse(self.power.may_be_off)

    def test_failed_on_retries_only_after_activity_and_cooldown(self):
        self.power.request('on')
        self.power.poll()
        self.children[0].finish(ok=False)
        self.power.poll()
        self.assertEqual(self.actions, ['on'])

        self.power.activity()
        self.power.poll()
        self.assertEqual(self.actions, ['on'])

        self.now[0] += 10
        self.power.poll()
        self.assertEqual(self.actions, ['on', 'on'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
