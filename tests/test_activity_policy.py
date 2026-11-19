"""Hardware-free regression tests for inactivity policy."""
# SPDX-License-Identifier: GPL-3.0-or-later
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'cec-tv'))
from activity_policy import ActivityPolicy, DEFAULT_TIMEOUT


class ActivityPolicyChecks(unittest.TestCase):
    def test_default_timeout_and_single_standby_transition(self):
        policy = ActivityPolicy(0)
        self.assertEqual(policy.timeout, DEFAULT_TIMEOUT)
        self.assertIsNone(policy.tick(DEFAULT_TIMEOUT - 0.1))
        self.assertIn('TV in standby', policy.tick(DEFAULT_TIMEOUT))
        self.assertIsNone(policy.tick(DEFAULT_TIMEOUT + 1))
        self.assertTrue(policy.expired)

    def test_activity_after_standby_requests_wake_once(self):
        policy = ActivityPolicy(0, timeout=10)
        policy.tick(10)
        self.assertIn('TV on', policy.activity(11))
        self.assertIsNone(policy.activity(12))
        self.assertFalse(policy.expired)

    def test_activity_without_wake_permission_only_resets_idle_time(self):
        policy = ActivityPolicy(0, timeout=10)
        self.assertIsNone(policy.activity(8, allow_wake=False))
        self.assertIsNone(policy.tick(10))
        self.assertIn('TV in standby', policy.tick(18))
        self.assertIsNone(policy.activity(19, allow_wake=False))
        self.assertTrue(policy.expired)
        self.assertIn('TV on', policy.activity(20))

    def test_uncertainty_requires_full_known_idle_interval(self):
        policy = ActivityPolicy(0, timeout=60)
        self.assertIsNone(policy.tick(100, uncertain=True))
        self.assertIsNone(policy.tick(159.9))
        self.assertIn('TV in standby', policy.tick(160))

    def test_disabled_timeout_never_expires(self):
        policy = ActivityPolicy(0, timeout=None)
        self.assertIsNone(policy.tick(100_000))
        self.assertFalse(policy.expired)

    def test_timeout_change_restarts_idle_interval(self):
        policy = ActivityPolicy(0, timeout=10)
        policy.set_timeout(30, 9)
        self.assertIsNone(policy.tick(38))
        self.assertIn('30', policy.tick(39))

    def test_cancel_standby_clears_expiration_without_activity(self):
        policy = ActivityPolicy(0, timeout=10)
        policy.tick(10)
        policy.cancel_standby(10)
        self.assertFalse(policy.expired)
        self.assertIsNone(policy.tick(11))


if __name__ == '__main__':
    unittest.main(verbosity=2)
