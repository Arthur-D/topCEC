# SPDX-License-Identifier: GPL-3.0-or-later
"""Hardware-independent CEC power-state transitions."""
from enum import Enum


class PowerState(Enum):
    UNKNOWN = 'unknown'
    ON = 'on'
    STANDBY = 'standby'
    TURNING_ON = 'turning_on'
    TURNING_OFF = 'turning_off'
    FAULT = 'fault'


class CecPowerStateMachine:
    def __init__(self):
        self.state = PowerState.UNKNOWN
        self.fault = None
        self.may_be_off = False

    @property
    def can_standby(self):
        return self.fault is None

    def begin(self, action):
        self._validate_action(action)
        if action == 'off' and not self.can_standby:
            return False
        self.state = PowerState.TURNING_OFF if action == 'off' else PowerState.TURNING_ON
        if action == 'off':
            self.may_be_off = True
        return True

    def confirm(self, state):
        if state not in ('on', 'standby'):
            raise ValueError(f'Invalid confirmed CEC power state: {state!r}')
        self.state = PowerState.ON if state == 'on' else PowerState.STANDBY
        self.may_be_off = state != 'on'
        self.fault = None

    def fail(self, error, action):
        self._validate_action(action)
        self.state = PowerState.FAULT
        self.fault = str(error)
        if action == 'on':
            self.may_be_off = True

    def set_fault(self, error):
        self.fault = error
        if error is not None:
            self.state = PowerState.FAULT
        elif self.state is PowerState.FAULT:
            self.state = PowerState.UNKNOWN

    @staticmethod
    def _validate_action(action):
        if action not in ('on', 'off'):
            raise ValueError(f'Invalid CEC power action: {action!r}')
