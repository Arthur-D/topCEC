"""Hardware-free regression tests for the live CEC coordinator."""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'cec-tv'))
import monitor


class Child:
    def __init__(self):
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
        self.power.activity()
        self.power.poll()
        self.assertEqual(self.actions, ['off'])
        self.assertEqual(self.power.pending, 'on')

        self.children[0].finish()
        self.power.poll()
        self.assertEqual(self.actions, ['off', 'on'])

    def test_failed_off_dispatches_recovery_on_and_blocks_future_off(self):
        self.power.request('off')
        self.power.poll()
        self.children[0].finish(ok=False)
        self.power.poll()

        self.assertEqual(self.actions, ['off', 'on'])
        self.assertIsNotNone(self.power.fault)
        self.power.request('off')
        self.power.poll()
        self.assertEqual(self.actions, ['off', 'on'])

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
