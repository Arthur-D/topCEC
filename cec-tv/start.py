#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Load the two KWin bridges, then run the monitor in the desktop session."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

from configuration import default_config_path, load_config

BASE = Path(__file__).resolve().parent


def qdbus(*args, required=True):
    result = subprocess.run(['/usr/bin/qdbus', *args], capture_output=True,
                            text=True, timeout=10)
    if required and result.returncode:
        raise RuntimeError(result.stderr or result.stdout)
    return result.stdout.strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', help='JSON monitor configuration file')
    args = parser.parse_args()
    config_path = Path(args.config).expanduser() if args.config else default_config_path()
    if args.config or config_path.exists():
        load_config(config_path)
    else:
        config_path = None
    owner = qdbus('org.freedesktop.DBus', '/org/freedesktop/DBus',
                  'org.freedesktop.DBus.NameHasOwner', 'net.local.CecActivity')
    if owner == 'true':
        raise RuntimeError('Another activity monitor owns the D-Bus name')
    for name in ('kwin-cec-firefox-bridge', 'kwin-cec-firefox-live',
                 'kwin-cec-activity-test', 'cec-tv-firefox', 'cec-tv-activity'):
        qdbus('org.kde.KWin', '/Scripting', 'org.kde.kwin.Scripting.unloadScript',
              name, required=False)
    for name, file in (('cec-tv-firefox', 'firefox.js'), ('cec-tv-activity', 'activity.js')):
        ident = qdbus('org.kde.KWin', '/Scripting', 'org.kde.kwin.Scripting.loadScript',
                      str(BASE / file), name)
        if not ident.isdigit():
            raise RuntimeError('KWin could not load ' + name + ': ' + ident)
    qdbus('org.kde.KWin', '/Scripting', 'org.kde.kwin.Scripting.start')
    command = ['/usr/bin/python3', str(BASE / 'monitor.py'), '--require-snapshot']
    if config_path:
        command += ['--config', str(config_path)]
    else:
        command += ['--kde-timeout']
    os.execv('/usr/bin/python3', command)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('CEC startup failed: ' + str(error), flush=True)
        sys.exit(1)
