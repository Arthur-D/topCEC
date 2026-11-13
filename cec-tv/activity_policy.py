# SPDX-License-Identifier: GPL-3.0-or-later
"""Hardware-independent inactivity and standby policy."""

DEFAULT_TIMEOUT = 300.0


class ActivityPolicy:
    def __init__(self, now, timeout=DEFAULT_TIMEOUT):
        self.timeout = timeout
        self.last = now
        self.expired = False

    def activity(self, now):
        self.last = now
        if self.expired:
            self.expired = False
            return 'Simulation: would turn TV on'
        return None

    def tick(self, now, uncertain=False):
        if uncertain:
            # Require a full inactivity interval of known state after recovery.
            self.last = now
        elif self.timeout is not None and not self.expired and now - self.last >= self.timeout:
            self.expired = True
            return f'Simulation: would put TV in standby ({self.timeout:g} seconds without activity)'
        return None

    def set_timeout(self, timeout, now):
        self.timeout = timeout
        self.last = now

    def cancel_standby(self, now):
        self.expired = False
        self.last = now
