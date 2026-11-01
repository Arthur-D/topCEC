#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Explicit CEC command to TV address 0, followed by verified power status.
Only invoked by the live monitor. No broadcast, input switching or autostart.
"""
import argparse
import fcntl
import json
import os
import re
import subprocess
import sys
import time


def cec(port, command):
    result = subprocess.run(['/usr/bin/cec-client', '-s', '-d', '1', port],
                            input=command + '\n', text=True, capture_output=True,
                            timeout=15)
    output = result.stdout + result.stderr
    if result.returncode or re.search(r'\bERROR\b|failed|unable', output, re.I):
        raise RuntimeError(output[-1500:])
    return output


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['on', 'off', 'status'])
    parser.add_argument('--port', default='/dev/serial/by-id/usb-Pulse-Eight_CEC_Adapter_v12-if00')
    args = parser.parse_args()
    # Shared lock with the controller prevents overlapping adapter clients.
    lock_path = os.path.join(os.environ['XDG_RUNTIME_DIR'], 'cec-activity-command.lock')
    with open(lock_path, 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.action != 'status':
            cec(args.port, 'on 0' if args.action == 'on' else 'standby 0')
        target = 'on' if args.action == 'on' else 'standby'
        if args.action == 'on':
            time.sleep(5)  # Allow TV electronics to wake before asking status.
        for attempt in range(6 if args.action == 'on' else 3):
            output = cec(args.port, 'pow 0')
            matches = re.findall(r'power status:\s*([^\r\n]+)', output, re.I)
            state = matches[-1].strip().lower() if matches else 'unknown'
            if args.action == 'status' or state == target:
                print(json.dumps({'ok': state in ('on', 'standby'), 'state': state,
                                  'action': args.action}))
                return 0 if state in ('on', 'standby') else 1
            time.sleep(1)
        raise RuntimeError('TV rapporterer ' + state + ', forventet ' + target)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as error:
        print(json.dumps({'ok': False, 'error': str(error)}))
        sys.exit(1)
