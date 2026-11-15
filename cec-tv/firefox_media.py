# SPDX-License-Identifier: GPL-3.0-or-later
"""Strict, hardware-independent Firefox WebExtension media snapshots."""
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path


UNKNOWN_OUTPUTS = ('', 'unknown', 'ingen')
PIP_CAPTION = 'Picture-in-Picture'


def is_firefox_executable(path):
    executable = Path(path)
    return (executable.name in ('firefox', 'firefox-bin')
            and executable.parent.name == 'firefox')


def _size(value):
    if (isinstance(value, (tuple, list)) and len(value) == 2
            and all(type(dimension) is int and dimension > 0 for dimension in value)):
        return tuple(value)
    return None


def _flatpak_firefox_scope(pid):
    groups = Path(f'/proc/{pid}/cgroup').read_text().splitlines()
    return next((group for group in groups
                 if re.search(r'/app-flatpak-org\.mozilla\.firefox-\d+\.scope$', group)),
                None)


def _pip_controls(frame):
    """Read Firefox's browser chrome only, without traversing page documents."""
    pending = [frame]
    controls = None
    found = set()
    for _ in range(128):
        if not pending:
            break
        node = pending.pop()
        if node is None or node.getRoleName() in (
                'document web', 'document frame', 'internal frame', 'page tab list'):
            continue
        attrs = dict(item.split(':', 1) for item in node.getAttributes() if ':' in item)
        node_id = attrs.get('id')
        if node_id == 'controls':
            controls = attrs.get('class', '').split()
        elif node_id in ('unpip', 'playpause'):
            found.add(node_id)
        if controls is not None and found == {'unpip', 'playpause'}:
            return 'playing' in controls
        pending.extend(node.getChildAtIndex(i) for i in reversed(range(node.childCount)))
    return None


def scan_firefox_pip(pids):
    """Read native PiP players from the Firefox processes verified by KWin."""
    import pyatspi

    scopes = defaultdict(list)
    verified = set()
    for pid in pids:
        try:
            exe = Path(f'/proc/{pid}/exe').readlink()
            if not is_firefox_executable(exe):
                continue
            verified.add(pid)
            scope = _flatpak_firefox_scope(pid)
            if scope:
                scopes[scope].append(pid)
        except OSError:
            continue
    players = []
    for app in pyatspi.Registry.getDesktop(0):
        pid = app.get_process_id()
        if pid not in verified:
            try:
                if Path(f'/proc/{pid}/exe').readlink().name != 'xdg-dbus-proxy':
                    continue
                matches = scopes.get(_flatpak_firefox_scope(pid), [])
            except OSError:
                continue
            if len(matches) != 1:
                continue
            pid = matches[0]
        for frame in app:
            if frame.getRoleName() != 'frame':
                continue
            playing = _pip_controls(frame)
            if playing is not None:
                try:
                    bounds = frame.queryComponent().getExtents(pyatspi.DESKTOP_COORDS)
                    size = _size((bounds.width, bounds.height))
                except (NotImplementedError, AttributeError):
                    size = None
                players.append({'pid': pid, 'title': frame.name or '',
                                'size': size, 'playing': playing})
    return players


class FirefoxPiPScan:
    """Keep accessibility calls off the D-Bus and input event loop."""

    INTERVAL = 2.0
    TIMEOUT = 5.0
    MAX_AGE = 8.0

    def __init__(self):
        self.worker = None
        self.pids = ()
        self.next_scan = 0
        self.players = []
        self.stamp = None

    def close(self):
        if self.worker is not None:
            if self.worker.poll() is None:
                self.worker.kill()
            self.worker.communicate()
            self.worker = None

    def poll(self, now, windows):
        pids = tuple(sorted({window['pid'] for window in windows
                             if type(window.get('pid')) is int and window['pid'] > 0}))
        if pids != self.pids:
            self.close()
            self.pids = pids
            self.next_scan = now
            self.stamp = None
        if self.worker is not None:
            if self.worker.poll() is not None:
                output, _ = self.worker.communicate()
                try:
                    self.players = json.loads(output) if self.worker.returncode == 0 else []
                except (ValueError, TypeError):
                    self.players = []
                self.stamp = now
                self.worker = None
                self.next_scan = now + self.INTERVAL
            elif now >= self.next_scan:
                self.close()
                self.stamp = None
                self.next_scan = now + self.INTERVAL
        if self.pids and self.worker is None and now >= self.next_scan:
            command = [sys.executable, str(Path(__file__).with_name('monitor.py')),
                       '--atspi-pip-scan', *map(str, self.pids)]
            try:
                self.worker = subprocess.Popen(command, stdout=subprocess.PIPE,
                                               stderr=subprocess.DEVNULL, text=True)
                self.next_scan = now + self.TIMEOUT
            except OSError:
                self.next_scan = now + self.INTERVAL
        if self.stamp is None or now - self.stamp > self.MAX_AGE:
            return []
        return self.players


def _pip_groups(windows, players):
    observed = defaultdict(list)
    for player in players:
        observed[player['pid'], player['title']].append(player)
    grouped = defaultdict(list)
    normal = []
    for window in windows:
        key = window.get('pid'), window['title']
        if key in observed or window['title'] == PIP_CAPTION:
            grouped[key].append(window)
        else:
            normal.append(window)
    groups = []
    for key, rows in grouped.items():
        matching = observed[key]
        sizes = Counter(_size(row.get('size')) for row in rows)
        player_sizes = Counter(_size(player['size']) for player in matching)
        # Accessible and KWin window order can differ. Use sizes only when both
        # snapshots describe the same set, and keep identical players grouped.
        if None not in sizes and sizes == player_sizes:
            for size in sizes:
                groups.append(([row['output'] for row in rows if _size(row['size']) == size],
                               [player['playing'] for player in matching
                                if _size(player['size']) == size]))
        else:
            states = [player['playing'] for player in matching]
            if len(states) != len(rows):
                states = [None] * len(rows)
            groups.append(([row['output'] for row in rows], states))
    return normal, groups


class FirefoxWebExtensionProvider:
    MAX_WINDOWS = 256
    MAX_TABS_PER_WINDOW = 1024

    def __init__(self):
        self.windows = None
        self.stamp = None
        self.error = None

    @staticmethod
    def _valid_title(value):
        return isinstance(value, str) and len(value) <= 4096

    @classmethod
    def decode_snapshot(cls, payload):
        value = json.loads(payload)
        if not isinstance(value, dict) or value.get('version') != 1:
            raise ValueError('Unsupported Firefox media snapshot')
        windows = value.get('windows')
        if not isinstance(windows, list) or len(windows) > cls.MAX_WINDOWS:
            raise ValueError('Invalid Firefox media windows')
        result = []
        seen_ids = set()
        for window in windows:
            if not isinstance(window, dict):
                raise ValueError('Invalid Firefox media window')
            window_id = window.get('window_id')
            active_title = window.get('active_title')
            tabs = window.get('tabs')
            if (type(window_id) is not int or window_id < 0
                    or window_id in seen_ids
                    or not cls._valid_title(active_title)
                    or not isinstance(tabs, list)
                    or len(tabs) > cls.MAX_TABS_PER_WINDOW):
                raise ValueError('Invalid Firefox media window fields')
            seen_ids.add(window_id)
            checked_tabs = []
            for tab in tabs:
                if (not isinstance(tab, dict)
                        or type(tab.get('audible')) is not bool
                        or type(tab.get('muted')) is not bool
                        or (tab.get('video') is not None
                            and type(tab['video']) is not bool)):
                    raise ValueError('Invalid Firefox media tab fields')
                video = tab.get('video')
                count = tab.get('playing_videos')
                if (count is not None and
                        (type(count) is not int or count < 0 or video is not (count > 0))):
                    raise ValueError('Invalid Firefox playing video count')
                checked_tabs.append({
                    'audible': tab['audible'],
                    'muted': tab['muted'],
                    'video': video,
                })
                if count is not None:
                    checked_tabs[-1]['playing_videos'] = count
            result.append({
                'window_id': window_id,
                'active_title': active_title,
                'tabs': checked_tabs,
            })
        return result

    def update(self, payload, now):
        try:
            self.windows = self.decode_snapshot(payload)
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            self.windows = None
            self.stamp = None
            self.error = str(error)
            return False
        self.stamp = now
        self.error = None
        return True

    def audio_state(self, mapping, now, target_output, ttl):
        if self.windows is None or self.stamp is None or now - self.stamp > ttl:
            return None
        audible_tv = False
        uncertain = False
        for window in self.windows:
            if not any(tab['audible'] and not tab['muted']
                       for tab in window['tabs']):
                continue
            output = mapping.browser_window_output(window['active_title'], now)
            if output is None:
                uncertain = True
            elif output == target_output:
                audible_tv = True
        return audible_tv, uncertain

    def video_state(self, mapping, now, target_output, ttl, pip_players=()):
        if mapping.health(now, required=True):
            return False, True
        if not any(output in (target_output, *UNKNOWN_OUTPUTS)
                   for (_title, output), stamp in mapping.reports.items()
                   if now - stamp <= mapping.ttl):
            return False, False
        if self.windows is None or self.stamp is None or now - self.stamp > ttl:
            return None
        normal, pip_groups = _pip_groups(mapping.windows, pip_players)
        normal_outputs = defaultdict(list)
        for window in normal:
            title = mapping._normalized_firefox_caption(window['title']).strip()
            normal_outputs[title].append(window['output'])
        caption_counts = Counter({title: len(outputs) for title, outputs in normal_outputs.items()})
        title_counts = Counter(window['active_title'].strip() for window in self.windows)
        uncertain = caption_counts != title_counts
        complete = (not uncertain and all(title and count == 1
                                          for title, count in title_counts.items()))
        tabs = [tab for window in self.windows for tab in window['tabs']]
        complete_counts = (complete and all(window['tabs'] for window in self.windows)
                           and all(tab['video'] is False or 'playing_videos' in tab
                                   for tab in tabs))
        total = sum(tab.get('playing_videos', 0) for tab in tabs) if complete_counts else None
        active_pips = 0
        possible_pips = 0
        possible_away = 0
        for outputs, states in pip_groups:
            playing = states.count(True)
            possible = playing + states.count(None)
            here = outputs.count(target_output)
            away = len(outputs) - here
            # Every matching would put a playing PiP on this display.
            if complete and playing > away:
                return True, False
            uncertain |= bool(possible and any(
                output in (target_output, *UNKNOWN_OUTPUTS) for output in outputs))
            possible_away += min(possible, away)
            active_pips += playing
            possible_pips += possible

        # A Firefox PiP clones a source element. With complete matching counts,
        # every playing source may already be accounted for by a native player.
        all_detached = total is not None and total == active_pips == possible_pips
        local_videos = 0
        for window in self.windows:
            title = window['active_title'].strip()
            if not title or title_counts[title] != 1 or caption_counts[title] != 1:
                uncertain = True
                continue
            states = [tab['video'] for tab in window['tabs']]
            if not states:
                uncertain = True
                continue
            if not any(state is not False for state in states):
                continue
            output = normal_outputs[title][0]
            if output in UNKNOWN_OUTPUTS:
                uncertain = True
            elif output == target_output:
                local_videos += sum(tab.get('playing_videos', 1) for tab in window['tabs']
                                    if tab['video'] is True)
                uncertain |= any(state is None for state in states)
        if not all_detached and local_videos > possible_away:
            return True, False
        uncertain |= bool(local_videos and not all_detached)
        return False, uncertain
