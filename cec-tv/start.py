#!/usr/bin/env python3
"""Load the two KWin bridges, then run the monitor in the desktop session."""
import os
from pathlib import Path
import subprocess
import sys

BASE = Path(__file__).resolve().parent


def qdbus(*args, required=True):
    result = subprocess.run(['/usr/bin/qdbus', *args], capture_output=True,
                            text=True, timeout=10)
    if required and result.returncode:
        raise RuntimeError(result.stderr or result.stdout)
    return result.stdout.strip()


def main():
    owner = qdbus('org.freedesktop.DBus', '/org/freedesktop/DBus',
                  'org.freedesktop.DBus.NameHasOwner', 'net.local.CecActivity')
    if owner == 'true':
        raise RuntimeError('En annen aktivitetsmonitor eier D-Bus-navnet')
    for name in ('kwin-cec-firefox-bridge', 'kwin-cec-firefox-live',
                 'kwin-cec-activity-test', 'cec-tv-firefox', 'cec-tv-activity'):
        qdbus('org.kde.KWin', '/Scripting', 'org.kde.kwin.Scripting.unloadScript',
              name, required=False)
    for name, file in (('cec-tv-firefox', 'firefox.js'), ('cec-tv-activity', 'activity.js')):
        ident = qdbus('org.kde.KWin', '/Scripting', 'org.kde.kwin.Scripting.loadScript',
                      str(BASE / file), name)
        if not ident.isdigit():
            raise RuntimeError('KWin kunne ikke laste ' + name + ': ' + ident)
    qdbus('org.kde.KWin', '/Scripting', 'org.kde.kwin.Scripting.start')
    os.execv('/usr/bin/python3', ['/usr/bin/python3', str(BASE / 'monitor.py'),
             '--cec', '--require-snapshot', '--kde-timeout',
             '--device', '/dev/input/by-id/usb-Logitech_G29_Driving_Force_Racing_Wheel-event-joystick',
             '--device', '/dev/input/by-id/usb-Glorious_GMBK_75__ISO_SL125211940100411-event-kbd'])


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('CEC oppstart feilet: ' + str(error), flush=True)
        sys.exit(1)
