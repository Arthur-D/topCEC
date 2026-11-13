# SPDX-License-Identifier: GPL-3.0-or-later
"""Plasma idle-inhibition observation and per-display matching."""
import json
import os
from pathlib import Path
import tempfile
import time

from chromium_media import BROWSERS, executable_browser

SERVICE = 'org.kde.Solid.PowerManagement.PolicyAgent'
PATH = '/org/kde/Solid/PowerManagement/PolicyAgent'
PROPERTIES = 'org.freedesktop.DBus.Properties'
MAX_AGE = 8.0
INTERVAL = 2.0


def app_key(value):
    value = value.strip().casefold()
    return value[:-8] if value.endswith('.desktop') else value


def window_aliases(identity, details):
    aliases = {identity}
    if details.get('window_class'):
        aliases.add(app_key(details['window_class']))
    if details.get('steam_id'):
        aliases.add('steam_app_' + details['steam_id'])
    return aliases


def observed_apps(names, apps):
    result = {}
    for name in names:
        key = app_key(name)
        matches = [app for app in apps
                   if key in (app_key(app['id']), app_key(app['name']))]
        groups = {app.get('launcher_group') for app in matches}
        if len(matches) == 1:
            app = matches[0]
        else:
            app = {'id': name, 'name': name}
            if len(groups) == 1 and None not in groups:
                app['launcher_group'] = groups.pop()
        result[app['id']] = app
    return list(result.values())


class InhibitionHistory:
    def __init__(self, path):
        self.path = Path(path)
        self.names = set()
        self.error = None
        self.dirty = False
        self.next_retry = 0.0
        try:
            data = json.loads(self.path.read_text(encoding='utf-8'))
            if (not isinstance(data, list)
                    or any(not isinstance(name, str) or not name.strip() for name in data)):
                raise ValueError('Expected a list of app names')
            self.names = set(data)
        except FileNotFoundError:
            pass
        except (OSError, UnicodeError, ValueError) as error:
            self.error = ('Cannot read inhibitor history: ' + str(error)
                          + '; correct the file and restart the host service.')

    def observe(self, requests, now=None):
        now = time.monotonic() if now is None else now
        names = {request['app'].strip() for request in requests
                 if request['kind'] == 'idle' and request['app'].strip()}
        if not names.issubset(self.names):
            self.names.update(names)
            self.dirty = True
        if (not self.dirty or now < self.next_retry
                or self.error and self.error.startswith('Cannot read')):
            return
        temporary = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(prefix=self.path.name + '.', dir=self.path.parent)
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                json.dump(sorted(self.names), stream, ensure_ascii=False)
                stream.write('\n')
            os.replace(temporary, self.path)
            self.dirty = False
            self.error = None
        except OSError as error:
            self.error = 'Cannot save inhibitor history: ' + str(error)
            self.next_retry = now + 10
        finally:
            if temporary is not None and os.path.exists(temporary):
                os.unlink(temporary)


def forced_inhibitions(enabled, apps, windows, windows_fresh, outputs):
    if not enabled or not outputs:
        return []
    if not windows_fresh:
        return [{'app': 'Selected apps', 'reason': 'Window status unavailable',
                 'locationUnknown': True, 'identityUnknown': False}]
    installed = {app_key(app['id']): app for app in apps}
    result = []
    for app in enabled:
        identity = app_key(app)
        details = installed.get(identity, {})
        aliases = window_aliases(identity, details)
        matches = [window for window in windows
                   if aliases & {app_key(window['desktop']), app_key(window['class'])}]
        relevant = [window for window in matches
                    if window['output'] in outputs or window['output'] in ('', 'ingen', 'unknown')]
        if relevant:
            result.append({'app': details.get('name', app), 'reason': 'Force inhibit (window open)',
                           'locationUnknown': any(window['output'] in ('', 'ingen', 'unknown')
                                                  for window in relevant),
                           'identityUnknown': False})
    if any(not window['desktop'].strip() and not window['class'].strip()
           and window['output'] in (*outputs, '', 'ingen', 'unknown') for window in windows):
        result.append({'app': 'Selected apps', 'reason': 'Window identity unavailable',
                       'locationUnknown': True, 'identityUnknown': True})
    return result


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
    installed = {}
    for app in apps:
        identity = app_key(app['id'])
        identities.add(identity)
        installed[identity] = app
        aliases.setdefault(app_key(app['name']), set()).add(identity)
    selected = []
    for request in inhibitions:
        if request['kind'] != 'idle':
            continue
        identity = app_key(request['app'])
        candidates = ({identity} if identity in identities or identity in enabled
                      else aliases.get(identity, set()))
        resolved = None
        if identity.startswith('/'):
            browser = executable_browser(identity)
            if browser in BROWSERS:
                browser_apps = [app_key(app['id']) for app in apps
                                if app_key(app['id']) in BROWSERS[browser][1]]
                if len(browser_apps) == 1:
                    resolved = browser_apps[0]
                    candidates = {identity, resolved}
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
        ambiguous = resolved is None and len(candidates) != 1
        identity = resolved or next(iter(matches))
        window_ids = window_aliases(identity, installed.get(identity, {}))
        app_windows = [
            row for row in windows
            if window_ids & {app_key(row['desktop']), app_key(row['class'])}
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
