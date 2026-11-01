"""Hardware-independent inactivity and standby policy."""

DEFAULT_TIMEOUT = 60.0


class ActivityPolicy:
    def __init__(self, now, timeout=DEFAULT_TIMEOUT):
        self.timeout = timeout
        self.last = now
        self.expired = False

    def activity(self, now):
        self.last = now
        if self.expired:
            self.expired = False
            return 'VILLE SLÅTT PÅ TV'
        return None

    def tick(self, now, uncertain=False):
        if uncertain:
            # Require a full 60 seconds of known inactivity after recovery.
            self.last = now
        elif self.timeout is not None and not self.expired and now - self.last >= self.timeout:
            self.expired = True
            return f'VILLE SLÅTT AV TV ({self.timeout:g} sekunder uten aktivitet)'
        return None

    def set_timeout(self, timeout, now):
        self.timeout = timeout
        self.last = now

    def cancel_standby(self, now):
        self.expired = False
        self.last = now
