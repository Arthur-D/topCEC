#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Forward approved Firefox media snapshots to the topCEC session service."""
import json
import sys

from firefox_media import FirefoxWebExtensionProvider
from native_messaging import read_message, write_message

SERVICE = 'net.local.CecActivity'


def main():
    try:
        import dbus
    except ImportError as error:
        print('dbus-python is required for the topCEC Firefox bridge: ' + str(error),
              file=sys.stderr)
        return 2
    while True:
        try:
            message = read_message(sys.stdin.buffer)
            if message is None:
                return 0
            windows = FirefoxWebExtensionProvider.decode_snapshot(
                json.dumps(message))
            payload = json.dumps({'version': 1, 'windows': windows},
                                 separators=(',', ':'))
            bus = dbus.SessionBus()
            service = bus.get_object(SERVICE, '/net/local/CecActivity')
            dbus.Interface(service, SERVICE).Report(
                'Firefox-media-snapshot: ' + payload)
            write_message(sys.stdout.buffer, {'accepted': True})
        except (ValueError, TypeError, UnicodeError, EOFError,
                dbus.DBusException) as error:
            print('Firefox native-messaging bridge failed: ' + str(error),
                  file=sys.stderr)
            return 1


if __name__ == '__main__':
    sys.exit(main())
