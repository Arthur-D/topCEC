# SPDX-License-Identifier: GPL-3.0-or-later
"""Plasma idle-inhibition observation and per-display matching."""
import json
import time

SERVICE = 'org.kde.Solid.PowerManagement.PolicyAgent'
PATH = '/org/kde/Solid/PowerManagement/PolicyAgent'
PROPERTIES = 'org.freedesktop.DBus.Properties'
MAX_AGE = 8.0
INTERVAL = 2.0


def app_key(value):
    value = value.strip().casefold()
    return value[:-8] if value.endswith('.desktop') else value


def decode_windows(payload):
    rows = json.loads(payload)
    if not isinstance(rows, list) or len(rows) > 4096:
        raise ValueError('Invalid app window snapshot')
    result = []
    for row in rows:
        if (not isinstance(row, dict)
                or not all(isinstance(row.get(key), str)
                           for key in ('desktop', 'class', 'output'))):
            raise ValueError('Invalid app window identity')
        result.append({key: row[key] for key in ('desktop', 'class', 'output')})
    return result


def matching_inhibitions(inhibitions, enabled, apps, windows, windows_fresh, outputs):
    """Return selected idle requests on selected outputs or with unknown location."""
    outputs = {outputs} if isinstance(outputs, str) else set(outputs)
    if not outputs:
        return []
    enabled = {app_key(item): item for item in enabled}
    aliases = {}
    identities = set()
    for app in apps:
        identity = app_key(app['id'])
        identities.add(identity)
        aliases.setdefault(app_key(app['name']), set()).add(identity)
    selected = []
    for request in inhibitions:
        if request['kind'] != 'idle':
            continue
        identity = app_key(request['app'])
        candidates = ({identity} if identity in identities or identity in enabled
                      else aliases.get(identity, set()))
        matches = candidates & enabled.keys()
        if not matches:
            if not candidates and enabled:
                selected.append({
                    'app': request['app'],
                    'reason': request['reason'],
                    'locationUnknown': True,
                    'identityUnknown': True,
                })
            continue
        # A non-unique app name cannot be safely assigned to a specific window.
        ambiguous = len(candidates) != 1
        identity = next(iter(matches))
        app_windows = [
            row for row in windows
            if identity in (app_key(row['desktop']), app_key(row['class']))
        ]
        unknown = (ambiguous or not windows_fresh or not app_windows
                   or any(row['output'] in ('', 'ingen', 'unknown') for row in app_windows))
        if not unknown and not any(row['output'] in outputs for row in app_windows):
            continue
        selected.append({
            'app': request['app'],
            'reason': request['reason'],
            'locationUnknown': unknown,
            'identityUnknown': False,
        })
    return selected


class PlasmaInhibitions:
    def __init__(self, bus, dbus, clock=time.monotonic):
        self.bus = bus
        self.dbus = dbus
        self.clock = clock
        self.requests = []
        self.stamp = None
        self.error = 'Waiting for Plasma idle-inhibition status'
        self.next_poll = 0.0
        self.started = None
        self.generation = 0

    def poll(self, now):
        if self.started is not None and now - self.started > MAX_AGE:
            self.generation += 1
            self.started = None
            self.error = 'Plasma idle-inhibition request timed out'
        if self.started is not None or now < self.next_poll:
            return
        self.next_poll = now + INTERVAL
        self.started = now
        self.generation += 1
        generation = self.generation

        def failed(error):
            if generation != self.generation:
                return
            self.started = None
            self.error = 'Cannot read Plasma idle inhibitions: ' + str(error)

        def received(rows):
            if generation != self.generation:
                return
            try:
                result = []
                for row in rows:
                    if len(row) != 5 or any(not isinstance(value, str) for value in row[:4]):
                        raise ValueError('Invalid Plasma inhibition entry')
                    result.append({'kind': str(row[0]), 'app': str(row[1]),
                                   'reason': str(row[2]), 'mode': str(row[3])})
            except (TypeError, ValueError) as error:
                failed(error)
                return
            self.requests = result
            self.stamp = self.clock()
            self.error = None
            self.started = None

        try:
            proxy = self.bus.get_object(SERVICE, PATH, introspect=False)
            interface = self.dbus.Interface(proxy, PROPERTIES)
            interface.Get(SERVICE, 'ActiveInhibitions', reply_handler=received,
                          error_handler=failed, timeout=MAX_AGE)
        except (self.dbus.DBusException, AttributeError) as error:
            failed(error)

    def health(self, now):
        if self.error:
            return self.error
        if self.stamp is None or now - self.stamp > MAX_AGE:
            return 'Plasma idle-inhibition status is stale'
        return None
