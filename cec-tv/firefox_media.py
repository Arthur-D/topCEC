# SPDX-License-Identifier: GPL-3.0-or-later
"""Strict, hardware-independent Firefox WebExtension media snapshots."""
import json


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
                        or type(tab.get('muted')) is not bool):
                    raise ValueError('Invalid Firefox media tab fields')
                checked_tabs.append({
                    'audible': tab['audible'],
                    'muted': tab['muted'],
                })
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
