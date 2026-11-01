#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Read Plasma's AC display timeout for this desktop; never changes settings.
AC defaults: KDE/powerdevil daemon/powerdevilsettingsdefaults.cpp.
"""
import json
import subprocess
import sys


def parse(enabled, seconds):
    value = enabled.strip().lower()
    if value not in ('true', 'false'):
        raise ValueError('Ugyldig TurnOffDisplayWhenIdle')
    if value == 'false':
        return None
    timeout = int(seconds.strip())
    if timeout <= 0:
        return None
    return timeout


def read(key, default):
    return subprocess.run(['/usr/bin/kreadconfig6', '--file', 'powerdevilrc',
                           '--group', 'AC', '--group', 'Display', '--key', key,
                           '--default', str(default)], capture_output=True,
                          text=True, check=True, timeout=2).stdout


if __name__ == '__main__':
    try:
        timeout = parse(read('TurnOffDisplayWhenIdle', 'true'),
                        read('TurnOffDisplayIdleTimeoutSec', '600'))
        print(json.dumps({'ok': True, 'timeout': timeout}))
    except Exception as error:
        print(json.dumps({'ok': False, 'error': str(error)}))
        sys.exit(1)
