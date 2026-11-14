# SPDX-License-Identifier: GPL-3.0-or-later
"""Chromium-family window snapshots and extension media state."""
from collections import Counter
import json
from pathlib import Path

from firefox_media import FirefoxWebExtensionProvider

BROWSERS = {
    'chromium': ('Chromium', {'chromium', 'chromium-browser', 'org.chromium.chromium'}),
    'chrome': ('Google Chrome', {'google-chrome', 'google-chrome-stable', 'com.google.chrome'}),
    'brave': ('Brave', {'brave-browser', 'brave-browser-stable', 'com.brave.browser'}),
    'edge': ('Microsoft Edge', {'microsoft-edge', 'microsoft-edge-stable', 'com.microsoft.edge'}),
    'vivaldi': ('Vivaldi', {'vivaldi', 'vivaldi-stable', 'com.vivaldi.vivaldi'}),
}
SUFFIXES = {
    'chromium': ('Chromium',),
    'chrome': ('Google Chrome',),
    'brave': ('Brave',),
    'edge': ('Microsoft Edge',),
    'vivaldi': ('Vivaldi',),
}


def browser_key(value):
    value = value.strip().casefold()
    return value[:-8] if value.endswith('.desktop') else value


def executable_browser(path):
    executable = Path(path)
    name = executable.name.casefold()
    full = str(executable).casefold()
    if name in ('chromium', 'chromium-browser'):
        return 'chromium'
    if name in ('brave', 'brave-browser'):
        return 'brave'
    if name in ('msedge', 'microsoft-edge'):
        return 'edge'
    if name in ('vivaldi', 'vivaldi-bin'):
        return 'vivaldi'
    if name in ('chrome', 'google-chrome', 'google-chrome-stable'):
        if 'org.chromium.chromium' in full or '/chromium/' in full:
            return 'chromium'
        if full == '/app/extra/chrome':
            return 'chrome'
        if 'com.google.chrome' in full or '/google/chrome/' in full or name != 'chrome':
            return 'chrome'
        return 'unknown'
    return None


def desktop_windows(payload, read_exe):
    rows = json.loads(payload)
    if not isinstance(rows, list) or len(rows) > 4096:
        raise ValueError('Invalid desktop snapshot')
    result = {browser: [] for browser in BROWSERS}
    unknown = []
    for row in rows:
        if (not isinstance(row, dict) or type(row.get('pid')) is not int
                or row['pid'] <= 0 or any(not isinstance(row.get(key), str)
                                          for key in ('title', 'output', 'desktop', 'class'))):
            raise ValueError('Invalid desktop window')
        keys = {browser_key(row['desktop']), browser_key(row['class'])}
        matches = [browser for browser, (_, aliases) in BROWSERS.items() if keys & aliases]
        executable = executable_browser(read_exe(row['pid']))
        if executable and executable != 'unknown' and executable not in matches:
            matches.append(executable)
        if len(matches) > 1:
            raise ValueError('Ambiguous browser window identity')
        if matches:
            result[matches[0]].append({'title': row['title'], 'output': row['output']})
        elif executable == 'unknown':
            unknown.append(row['output'])
    return result, unknown


def normalized_title(browser, title):
    for name in SUFFIXES[browser]:
        for separator in (' - ', ' — '):
            suffix = separator + name
            if title.endswith(suffix):
                return title[:-len(suffix)].rstrip()
    return title


class ChromiumMedia:
    def __init__(self, read_exe=None):
        self.windows = None
        self.unknown = []
        self.read_exe = read_exe or (lambda pid: str(Path(f'/proc/{pid}/exe').readlink()))
        self.stamp = None
        self.error = None
        self.snapshots = {}
        self.source_errors = {}

    def update_windows(self, payload, now):
        try:
            self.windows, self.unknown = desktop_windows(payload, self.read_exe)
        except (ValueError, TypeError, OSError, json.JSONDecodeError) as error:
            self.windows = None
            self.stamp = None
            self.error = str(error)
            return False
        self.stamp = now
        self.error = None
        return True

    def update(self, payload, now):
        value = json.loads(payload)
        if not isinstance(value, dict):
            raise ValueError('Invalid browser media snapshot')
        browser, instance = value.get('browser'), value.get('instance')
        if (browser not in BROWSERS or not isinstance(instance, str)
                or len(instance) != 32 or any(c not in '0123456789abcdef' for c in instance)):
            raise ValueError('Invalid browser media source')
        try:
            windows = FirefoxWebExtensionProvider.decode_snapshot(json.dumps({
                'version': value.get('version'), 'windows': value.get('windows')}))
        except (ValueError, TypeError) as error:
            self.snapshots.pop((browser, instance), None)
            self.source_errors[browser, instance] = (str(error), now)
            raise
        self.snapshots = {key: item for key, item in self.snapshots.items()
                          if now - item[1] <= 30}
        self.source_errors = {key: item for key, item in self.source_errors.items()
                              if now - item[1] <= 30}
        if (browser, instance) not in self.snapshots and len(self.snapshots) >= 128:
            raise ValueError('Too many browser media sources')
        self.snapshots[browser, instance] = (windows, now)
        self.source_errors.pop((browser, instance), None)

    def state(self, browser, outputs, now, ttl, video=False):
        if self.windows is None or self.stamp is None or now - self.stamp > ttl:
            return False, 'Desktop window status is unavailable or stale'
        if any(output in (*outputs, '', 'unknown', 'ingen') for output in self.unknown):
            return False, 'Browser window identity is unknown'
        windows = self.windows[browser]
        if not any(window['output'] in (*outputs, '', 'unknown', 'ingen')
                   for window in windows):
            return False, None
        if any(kind == browser and now - stamp <= ttl
               for (kind, _), (_, stamp) in self.source_errors.items()):
            return False, 'Browser extension sent invalid media data'
        snapshots = [item for (kind, _), (items, stamp) in self.snapshots.items()
                     if kind == browser and now - stamp <= ttl for item in items]
        if not snapshots:
            return False, 'Browser extension is unavailable or stale'
        captions = [normalized_title(browser, window['title']) for window in windows]
        titles = [window['active_title'].strip() for window in snapshots]
        counts = Counter(captions)
        snapshot_counts = Counter(titles)
        if (not all(title and counts[title] == 1 and snapshot_counts[title] == 1
                    for title in captions)
                or set(captions) != set(titles)):
            return False, 'Browser windows cannot be uniquely matched to extension data'
        by_title = {normalized_title(browser, window['title']): window for window in windows}
        for snapshot in snapshots:
            output = by_title[snapshot['active_title'].strip()]['output']
            tabs = snapshot['tabs']
            active = (any(tab['video'] is True for tab in tabs) if video else
                      any(tab['audible'] and not tab['muted'] for tab in tabs))
            unknown = video and any(tab['video'] is None for tab in tabs)
            if active or unknown:
                if output in ('', 'unknown', 'ingen'):
                    return False, 'Browser media display is unknown'
                if output in outputs:
                    if unknown:
                        return False, 'Browser video state is unknown'
                    return True, None
        return False, None
