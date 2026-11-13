#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""TV activity monitor with opt-in real CEC. Default remains simulation.
--cec enables actual power commands, requires fresh KWin snapshots and stops on
adapter failures. Use start-cec-live.fish to exclude the old idle controller.
"""
import argparse
from collections import Counter
import grp
import json
import math
import os
import pwd
import selectors
import shlex
import stat
import subprocess
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from activity_policy import ActivityPolicy, DEFAULT_TIMEOUT
from cec_power_state import CecPowerStateMachine
from configuration import (
    DEFAULT_CONFIG, SCHEMA_VERSION, default_config_path, load_config, merge_cli, save_config,
    validate_config, mouse_outputs,
)
from firefox_media import FirefoxWebExtensionProvider
from standby_apps import (InhibitionHistory, PlasmaInhibitions, decode_windows,
                          forced_inhibitions, matching_inhibitions, observed_apps)
from providers import ActivityProvider as ActivityProviderContract
from providers import CecBackend, MediaProvider as MediaProviderContract

TARGET = DEFAULT_CONFIG['target_output']
TIMEOUT = DEFAULT_TIMEOUT
SCAN_INTERVAL = 2.0
SCAN_TIMEOUT = 5.0
SCAN_MAX_AGE = 8.0


def log(message):
    print(time.strftime('[%H:%M:%S]'), message, flush=True)


def input_group_command(username, gid, local_path='/etc/group',
                        vendor_path='/usr/lib/group'):
    """Handle Atomic desktops whose vendor groups are invisible to usermod."""
    command = 'usermod -aG input -- ' + shlex.quote(username)
    try:
        local = Path(local_path).read_text().splitlines()
        vendor = Path(vendor_path).read_text().splitlines()
    except OSError:
        return 'sudo ' + command, False
    if (not any(line.startswith('input:') for line in local)
            and any(line.split(':')[:3] == ['input', 'x', str(gid)]
                    for line in vendor)):
        # Recheck at execution time so copying/rerunning never duplicates a group.
        script = (
            "set -eu; if ! grep -q '^input:' /etc/group; then "
            "grep '^input:' /usr/lib/group >> /etc/group; fi; " + command)
        return 'sudo sh -c ' + shlex.quote(script), True
    return 'sudo ' + command, False


def input_permission_help(error):
    help_text = (
        'Check that the selected input path belongs to the intended keyboard or '
        'controller. Choose a stable /dev/input/by-id/ path in Input. '
        'The host user needs read access to that device; changing the path does '
        'not grant access. Ask your administrator for scoped device permissions.')
    result = {'message': help_text, 'command': ''}
    if not isinstance(error, PermissionError) or not error.filename:
        return result
    result['path'] = os.fsdecode(error.filename)
    try:
        device = os.stat(error.filename)
        group = grp.getgrnam('input')
        user = pwd.getpwuid(os.getuid())
        process_groups = {*os.getgroups(), os.getgid()}
    except (OSError, KeyError) as diagnostic_error:
        log('Could not inspect input permission recovery: ' + str(diagnostic_error))
        return result
    if (not stat.S_ISCHR(device.st_mode) or device.st_gid != group.gr_gid
            or not device.st_mode & stat.S_IRGRP):
        return result
    warning = (
        'The input group grants access to keyboard and other input events, '
        'not just this device. Only join it if you trust applications running '
        'as your user; scoped device permissions are a narrower alternative. ')
    session = (
        'Fully log out and log back in after changing membership so the desktop '
        'and user service inherit it. If the user manager persists across logout, '
        'reboot. After signing back in, open Diagnostics and select Retry '
        'monitoring. Older GUIs can retry by saving and applying settings.')
    if group.gr_gid in process_groups:
        result['message'] = (
            help_text + '\nThe backend already has the input group. Joining it '
            'again will not fix this error; check device ACLs or other host '
            'security policy.')
    elif user.pw_gid == group.gr_gid or user.pw_name in group.gr_mem:
        result['message'] = (
            'Your account already belongs to input, but the backend session '
            'has not inherited that membership. ' + warning + session)
    else:
        result['message'] = (
            'This device is group-readable by input, and the backend user is '
            'not a member. First confirm this is the intended input device. '
            'To join input, run the command below manually in a host terminal '
            '(administrator password required). ' + warning + session)
        result['command'], vendor_only = input_group_command(
            user.pw_name, group.gr_gid)
        if vendor_only:
            result['message'] += (
                '\nOn this Atomic desktop, input exists only in /usr/lib/group. '
                'usermod alone cannot persist membership in that vendor group. '
                'The command first copies the input entry into /etc/group if '
                'missing, then adds your account. Rebooting before this step '
                'does not fix membership.')
    return result


class CecPower:
    OPERATION_TIMEOUT = 130.0

    def __init__(self, port):
        self.port = port
        self.state_machine = CecPowerStateMachine()
        self.process = None
        self.pending = None
        self.sent = None
        self.started = 0
        self.on_retry_after = 0.0

    @property
    def fault(self):
        return self.state_machine.fault

    @fault.setter
    def fault(self, error):
        self.state_machine.set_fault(error)

    @property
    def may_be_off(self):
        return self.state_machine.may_be_off

    def request(self, action):
        if action == 'off' and not self.state_machine.can_standby:
            return
        if action == 'on' and self.process is not None and self.sent == 'on':
            # Activity cancels a queued OFF but never duplicates an in-flight ON.
            self.pending = None
            return
        self.pending = action
        if action == 'on' and self.process is not None and self.sent == 'off':
            pid = getattr(self.process, 'pid', None)
            if pid is None:
                self.state_machine.set_fault(
                    'Could not cancel standby command: process PID unavailable')
            else:
                import os
                import signal
                try:
                    os.killpg(pid, signal.SIGTERM)
                    log('CEC standby cancellation requested for wake')
                except ProcessLookupError:
                    pass
                except OSError as error:
                    self.state_machine.set_fault(
                        f'Could not cancel standby command: {error}')

    def activity(self, wake_requested=False):
        if wake_requested or self.may_be_off:
            self.request('on')

    def validate_port(self):
        fd = os.open(self.port, os.O_RDWR | os.O_NONBLOCK | os.O_NOCTTY)
        try:
            if not stat.S_ISCHR(os.fstat(fd).st_mode):
                raise OSError('CEC adapter must be a host character device: ' + self.port)
        finally:
            os.close(fd)

    def poll(self):
        timed_out = False
        if self.process is not None:
            if self.process.poll() is None:
                if time.monotonic() - self.started < self.OPERATION_TIMEOUT:
                    return
                import os, signal
                try:
                    os.killpg(self.process.pid, signal.SIGKILL)
                    timed_out = True
                except ProcessLookupError:
                    # The child can exit between poll() and killpg(); its final
                    # status/output below remains authoritative in that race.
                    pass
            output, errors = self.process.communicate()
            try:
                if timed_out:
                    raise TimeoutError(
                        f'CEC operation exceeded {self.OPERATION_TIMEOUT:g}-second deadline')
                result = json.loads(output)
                if self.process.returncode or not result.get('ok'):
                    raise RuntimeError(result.get('error', errors or 'CEC failed'))
                log('CEC confirmed: TV ' + result['state'])
                self.state_machine.confirm(result['state'])
            except Exception as error:
                self.state_machine.fail(error, self.sent)
                log('CEC ERROR: ' + self.fault + '; further standby blocked')
                if self.sent == 'on':
                    # A new activity event may queue a retry, at most once per
                    # ten seconds after failure. Never retry without activity.
                    self.on_retry_after = time.monotonic() + 10.0
            self.process = None
        if self.pending is not None:
            if self.pending == 'on' and time.monotonic() < self.on_retry_after:
                return
            action, self.pending = self.pending, None
            if action == 'off' and not self.state_machine.can_standby:
                return
            helper = str(Path(__file__).with_name('cec-power-command.py'))
            process = subprocess.Popen(
                [sys.executable, helper, action, '--port', self.port],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                start_new_session=True)
            self.state_machine.begin(action)
            self.process = process
            self.started, self.sent = time.monotonic(), action
            log('CEC sending: ' + ('standby' if action == 'off' else 'on'))

    def close(self):
        # Do not abandon a delayed OFF after the monitor has stopped.
        self.pending = None
        if self.process is not None:
            try:
                self.process.communicate(timeout=self.OPERATION_TIMEOUT)
            except subprocess.TimeoutExpired:
                import os, signal
                os.killpg(self.process.pid, signal.SIGKILL)
                self.process.communicate()
            self.process = None
        if self.may_be_off:
            log('Shutting down: attempting to turn TV back on')
            try:
                result = subprocess.run(
                    [sys.executable, str(Path(__file__).with_name('cec-power-command.py')),
                     'on', '--port', self.port], capture_output=True, text=True, timeout=130)
                log('CEC shutdown: ' + result.stdout.strip())
            except Exception as error:
                log('CEC shutdown error: ' + str(error))


def request_manual_power(power, action, fail_safe_reason):
    if action not in ('on', 'off'):
        raise ValueError('Power action must be "on" or "off"')
    if power is None:
        raise RuntimeError('CEC power control is not enabled')
    if action == 'off':
        if fail_safe_reason:
            raise RuntimeError('Standby blocked: ' + str(fail_safe_reason))
        process = getattr(power, 'process', None)
        if not power.state_machine.can_standby or power.pending == 'on' or (
            process is not None and getattr(power, 'sent', None) == 'on'
        ):
            raise RuntimeError('Standby blocked by CEC recovery state')
        if power.pending == 'off' or (
            process is not None and getattr(power, 'sent', None) == 'off'
        ):
            raise RuntimeError('Standby request is already in progress')
    power.request(action)
    if action == 'off' and power.pending != 'off':
        raise RuntimeError('Standby request was not queued')


class KdeTimeout:
    def __init__(self, fallback_timeout=DEFAULT_TIMEOUT):
        self.process = None
        self.next_read = 0
        self.started = 0
        self.error = 'Waiting for KDE display timeout'
        self.value = 'unread'
        self.fallback_timeout = fallback_timeout
        self.fallback_active = False

    def use_fallback(self, timer, now):
        if self.fallback_active:
            return
        self.fallback_active = True
        timer.set_timeout(self.fallback_timeout, now)
        timeout = ('disabled' if self.fallback_timeout is None else
                   f'{self.fallback_timeout:g} seconds')
        log(f'{self.error}; using fallback timeout of {timeout}')

    def poll(self, timer, now):
        if self.process is not None:
            if self.process.poll() is not None:
                output, errors = self.process.communicate()
                try:
                    result = json.loads(output)
                    value = result.get('timeout')
                    if self.process.returncode or not result.get('ok'):
                        raise ValueError(result.get('error', errors))
                    if value is not None and (type(value) is not int or value <= 0):
                        raise ValueError('Invalid display timeout')
                    if value != self.value or self.fallback_active:
                        self.value = value
                        timer.set_timeout(value, now)
                        log('KDE display timeout (AC power): ' +
                            ('never; automatic standby disabled' if value is None
                             else f'{value} seconds ({value / 60:g} minutes)'))
                    self.error = None
                    self.fallback_active = False
                except Exception as error:
                    self.error = 'Cannot read KDE display timeout: ' + str(error)
                    self.use_fallback(timer, now)
                self.process = None
                self.next_read = now + 5
            elif now - self.started > 5:
                self.process.kill()
                self.process.communicate()
                self.process = None
                self.next_read = now + 5
                self.error = 'KDE settings did not respond'
                self.use_fallback(timer, now)
        if self.process is None and now >= self.next_read:
            try:
                self.process = subprocess.Popen(
                    [sys.executable, str(Path(__file__).with_name('cec-kde-settings.py'))],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                self.started = now
            except (OSError, subprocess.SubprocessError) as error:
                self.error = 'Cannot read KDE display timeout: ' + str(error)
                self.next_read = now + 5
                self.use_fallback(timer, now)
        return self.error

    def close(self):
        if self.process is not None:
            if self.process.poll() is None:
                self.process.kill()
            self.process.communicate()


class Timer(ActivityPolicy):
    """Compatibility name for the extracted activity policy."""


class Axis:
    def __init__(self, info, deadzone_percent=2.0):
        self.low, self.high = info.min, info.max
        span = self.high - self.low
        # Deadband around the last accepted position, not around zero:
        # pedals may rest at an endpoint and the wheel may rest off-centre.
        # Never cap the threshold at 100 on high-resolution steering axes.
        self.threshold = max(1, 2 * info.fuzz + 1,
                             math.ceil(max(0, span) * deadzone_percent / 100))
        self.current = self.anchor = info.value

    def reset(self):
        self.anchor = self.current

    def update(self, value, active):
        if self.high <= self.low or not self.low <= value <= self.high:
            # Bad samples must not become the baseline for a later false jump.
            return False
        self.current = value
        if not active:
            self.anchor = value
            return False
        if abs(value - self.anchor) >= self.threshold:
            self.anchor = value
            return True
        return False


class EvdevActivityProvider:
    def __init__(self, ecodes, axis_deadzone_percent, rz_deadzone_percent,
                 device_axis_deadzones=None):
        self.ecodes = ecodes
        self.axis_deadzone_percent = axis_deadzone_percent
        self.rz_deadzone_percent = rz_deadzone_percent
        self.device_axis_deadzones = device_axis_deadzones or {}

    def seed(self, device, path=None):
        ecodes = self.ecodes
        device_path = path or getattr(device, 'path', None)
        overrides = {}
        if device_path and self.device_axis_deadzones:
            identity = Path(device_path).resolve()
            for path, axes in self.device_axis_deadzones.items():
                if Path(path).resolve() == identity:
                    overrides.update(axes)
        return {code: Axis(info, overrides.get(
            str(code), self.rz_deadzone_percent if code == ecodes.ABS_RZ
            else self.axis_deadzone_percent)) for code, info in
                device.capabilities(absinfo=True).get(ecodes.EV_ABS, [])
                if code < ecodes.ABS_MT_SLOT}

    def event_activity(self, state, event, focused):
        ecodes = self.ecodes
        if event.type == ecodes.EV_ABS:
            axis = state['axes'].get(event.code)
            if axis and axis.update(event.value, focused):
                return (f'wheel/pedal ({ecodes.ABS.get(event.code, event.code)}, '
                        f'value {event.value}, threshold {axis.threshold})')
        elif event.type == ecodes.EV_KEY and event.value in (1, 2) and focused:
            return 'keyboard/wheel'
        return None


def is_firefox_executable(path):
    executable = Path(path)
    return (executable.name in ("firefox", "firefox-bin")
            and executable.parent.name == "firefox")


def firefox_window_snapshot(payload, read_exe=None):
    """Resolve KWin PIDs on the host; never infer browser identity from titles."""
    if read_exe is None:
        read_exe = lambda pid: str(Path(f"/proc/{pid}/exe").readlink())
    rows = json.loads(payload)
    if not isinstance(rows, list):
        raise ValueError("Invalid desktop snapshot")
    result = []
    for row in rows:
        if (not isinstance(row, dict) or type(row.get("pid")) is not int
                or row["pid"] <= 0 or not isinstance(row.get("title"), str)
                or not isinstance(row.get("output"), str)):
            raise ValueError("Invalid window identity")
        if is_firefox_executable(read_exe(row["pid"])):
            result.append({"title": row["title"], "output": row["output"]})
    return json.dumps(result)


class Mapping:
    def __init__(self, ttl):
        self.ttl = ttl
        self.reports = {}
        self.snapshot_stamp = None
        self.snapshot_counts = Counter()
        self.snapshot_error = None

    def report(self, output, title, now):
        if self.snapshot_stamp is not None:
            return  # Old bridges cannot contaminate an atomic snapshot.
        self.reports[(title, output)] = now
        self.reports = {k: t for k, t in self.reports.items()
                        if now - t <= self.ttl}

    def snapshot(self, payload, now):
        try:
            rows = json.loads(payload)
            if not isinstance(rows, list) or any(
                not isinstance(row, dict)
                or not isinstance(row.get('title'), str)
                or not isinstance(row.get('output'), str)
                for row in rows
            ):
                raise ValueError('Invalid Firefox snapshot')
        except (ValueError, TypeError) as error:
            self.snapshot_error = str(error)
            return False
        self.reports = {(row['title'], row['output']): now for row in rows}
        self.snapshot_counts = Counter(row['title'] for row in rows)
        self.snapshot_stamp = now
        self.snapshot_error = None
        return True

    def health(self, now, required=False):
        if self.snapshot_error:
            return 'Invalid Firefox snapshot'
        if self.snapshot_stamp is None:
            return 'Waiting for Firefox snapshot from the live bridge' if required else None
        if now - self.snapshot_stamp > self.ttl:
            return 'Firefox bridge updates have stopped'
        return None

    def output(self, title, counts, now):
        # Never fall back to current focus, active tab title or substring match.
        if self.health(now):
            return None
        if self.snapshot_stamp is not None and self.snapshot_counts[title] != 1:
            return None
        if not title or counts[title] != 1:
            return None
        candidates = {output for (name, output), stamp in self.reports.items()
                      if name == title and now - stamp <= self.ttl}
        if len(candidates) != 1:
            return None
        output = next(iter(candidates))
        return None if output in ('ingen', 'unknown', '') else output

    @staticmethod
    def _normalized_firefox_caption(title):
        for suffix in (
                ' — Mozilla Firefox', ' - Mozilla Firefox',
                ' — Firefox', ' - Firefox', ' — Mozilla Firefox ESR',
                ' - Mozilla Firefox ESR'):
            if title.endswith(suffix):
                return title[:-len(suffix)].rstrip()
        return title

    def browser_window_output(self, active_title, now):
        if not active_title or self.health(now):
            return None
        expected = active_title.strip()
        matches = [
            output for (title, output), stamp in self.reports.items()
            if now - stamp <= self.ttl
            and self._normalized_firefox_caption(title) == expected
        ]
        if len(matches) != 1:
            return None
        output = matches[0]
        return None if output in ('ingen', 'unknown', '') else output


def audio_state(frames, mapping, now, target_output=TARGET):
    counts = Counter(frame['title'] for frame in frames)
    audible_tv, uncertain = False, False
    for frame in frames:
        if frame['audio']:
            output = mapping.output(frame['title'], counts, now)
            audible_tv |= output == target_output
            uncertain |= output is None
    return audible_tv, uncertain


class FirefoxMediaProvider:
    def decode_scan(self, output, errors, returncode):
        return decode_scan(output, errors, returncode)

    def audio_state(self, frames, mapping, now, target_output=TARGET):
        return audio_state(frames, mapping, now, target_output)


class MatchDiagnostics:
    """Read-only diagnostics; caller must supply fresh, valid scans and snapshots.

    Never changes mapping, activity or timeout state.
    """
    def __init__(self):
        self.started = None
        self.signature = None
        self.last_log = float('-inf')

    def update(self, frames, mapping, now, scan_stamp):
        kwin = sorted((title, output) for (title, output), stamp in mapping.reports.items()
                      if now - stamp <= mapping.ttl)
        atspi = sorted((frame['title'], frame['audio']) for frame in frames)
        missing = sorted({title for title, _ in kwin} - {title for title, _ in atspi})
        if not missing:
            if self.started is None:
                return []
            duration = now - self.started
            self.started = self.signature = None
            return [f'MATCH-DIAG: matching restored after {duration:.1f} s']
        first = self.started is None
        if first:
            self.started = now
        signature = (kwin, atspi)
        # Print first discrepancy, then changed details at most every 5 seconds,
        # or a reminder after 30 seconds for an unchanged persistent mismatch.
        if not first and (now - self.last_log < 5 or
                          (signature == self.signature and now - self.last_log < 30)):
            return []
        self.signature, self.last_log = signature, now
        def age(stamp):
            return 'unknown' if stamp is None else f'{now - stamp:.1f} s'
        details = {
            'mangler_i_AT_SPI': missing,
            'bare_i_AT_SPI': sorted({title for title, _ in atspi} -
                                   {title for title, _ in kwin}),
            'KWin': [{'tittel': title, 'skjerm': output} for title, output in kwin],
            'AT_SPI': [{'tittel': title, 'lyd': audio} for title, audio in atspi],
        }
        return [f'MATCH-DIAG: mismatch for {now - self.started:.1f} s; '
                f'KWin report age {age(mapping.snapshot_stamp)}; '
                f'AT-SPI result age {age(scan_stamp)}',
                'MATCH-DIAG: ' + json.dumps(details, ensure_ascii=False)]


def decode_scan(output, errors, returncode):
    """stderr is diagnostic text, not the scanner's structured result."""
    result = json.loads(output)
    if returncode or result.get('ok') is not True:
        raise RuntimeError(result.get('error', 'AT-SPI scan failed'))
    frames = result.get('frames')
    if not isinstance(frames, list) or any(
        not isinstance(frame, dict)
        or not isinstance(frame.get('title'), str)
        or not isinstance(frame.get('audio'), bool)
        for frame in frames
    ):
        raise RuntimeError('Invalid AT-SPI result')
    if errors.strip() and not frames:
        raise RuntimeError('AT-SPI warning and no readable Firefox frames')
    return frames


def scan_atspi(mute_labels, read_exe=None):
    """Separate process so broken AT-SPI cannot freeze evdev/D-Bus handling."""
    import pyatspi
    if read_exe is None:
        read_exe = lambda pid: str(Path(f'/proc/{pid}/exe').readlink())
    desktop = pyatspi.Registry.getDesktop(0)
    frames = []
    visited = 0

    def walk(node, inside_tab=False):
        nonlocal visited
        visited += 1
        if visited > 12000:
            raise RuntimeError('AT-SPI tree is too large; incomplete scan')
        if node is None:
            raise RuntimeError('AT-SPI returned an empty node')
        if node.getState().contains(pyatspi.STATE_DEFUNCT):
            raise RuntimeError('AT-SPI node disappeared during scan')
        role = node.getRoleName()
        # Do not mistake webpage buttons named Mute tab for browser tab audio.
        if role in ('document web', 'document frame', 'internal frame'):
            return 0, False
        in_tab = inside_tab or role == 'page tab'
        count = int(role == 'page tab')
        audio = (in_tab and role in ('push button', 'button')
                 and node.name in mute_labels)
        for index in range(node.childCount):
            tabs, sounding = walk(node.getChildAtIndex(index), in_tab)
            count += tabs
            audio |= sounding
        return count, audio

    for index in range(desktop.childCount):
        app = desktop.getChildAtIndex(index)
        if app is None:
            raise RuntimeError('AT-SPI application is missing')
        pid = app.get_process_id()
        if type(pid) is not int or pid <= 0:
            raise RuntimeError('AT-SPI application process identity is unavailable')
        if not is_firefox_executable(read_exe(pid)):
            continue
        found = False
        for child_index in range(app.childCount):
            frame = app.getChildAtIndex(child_index)
            if frame.getRoleName() != 'frame':
                continue
            found = True
            title = frame.name or ''
            # Firefox exports its WebRTC indicator as a frame without tabs.
            # Identify only this browser-owned auxiliary window; unknown
            # tabless frames must still fail the scan.
            attributes = dict(item.split(":", 1) for item in frame.getAttributes()
                              if ":" in item)
            if (attributes.get("id") == "webrtcIndicator"
                    and attributes.get("tag") == "html"):
                continue
            tabs, sounding = walk(frame)
            if tabs == 0:
                raise RuntimeError('Firefox frame has no readable page tabs: ' + title)
            frames.append({'title': title, 'audio': bool(sounding)})
        if not found:
            raise RuntimeError('Firefox found, but no accessible frames')
    return frames


def run(args, *, activity_provider_factory=None, media_provider=None,
        cec_backend_factory=None):
    try:
        import dbus
        import dbus.service
        from dbus.mainloop.glib import DBusGMainLoop
        from gi.repository import GLib
        from evdev import InputDevice, ecodes
    except ImportError as error:
        log('Missing Python dependency: ' + str(error))
        log('Host Python requires dbus-python, PyGObject/GLib, evdev and pyatspi.')
        return 2

    DBusGMainLoop(set_as_default=True)
    target_output = getattr(args, 'target', TARGET)
    timer = Timer(time.monotonic(), timeout=getattr(args, 'timeout_seconds', DEFAULT_TIMEOUT))
    kde_settings = KdeTimeout() if args.kde_timeout else None
    if kde_settings is not None:
        kde_settings.fallback_timeout = getattr(args, 'timeout_seconds', DEFAULT_TIMEOUT)
    if cec_backend_factory is None:
        cec_backend_factory = CecPower
    power: CecBackend | None = (
        cec_backend_factory(args.cec_port) if args.cec else None)
    if media_provider is None:
        media_provider = FirefoxMediaProvider()
    mapping = Mapping(args.mapping_ttl)
    webextension_media = FirefoxWebExtensionProvider()
    match_diagnostics = MatchDiagnostics()
    selector = selectors.DefaultSelector()
    devices = {}
    focus = None
    worker = None
    worker_labels = None
    worker_started = next_scan = 0.0
    frames = []
    scan_stamp = None
    scan_error = 'Waiting for the first AT-SPI scan'
    previous_status = None
    warning_reported = False
    previous_playback = False
    status_snapshot = {
        'service': 'starting',
        'cec_enabled': power is not None,
        'target_output': target_output,
        'adapter': args.cec_port if power else None,
        'power_state': 'unknown',
        'pending_action': None,
        'cec_fault': None,
        'plasma_timeout_read': False,
        'plasma_timeout_seconds': None,
        'plasma_timeout_fallback': False,
        'fail_safe_reason': 'monitor poll has not completed',
        'playback_active': False,
        'scan_status': scan_error,
    }
    config_path = (Path(args.config).expanduser()
                   if getattr(args, 'config', None) else default_config_path())
    inhibition_history = InhibitionHistory(config_path.parent / 'observed-inhibitors.json')
    runtime_config = validate_config({
        'schema_version': 1,
        'target_output': target_output,
        'timeout_seconds': getattr(args, 'timeout_seconds', int(DEFAULT_TIMEOUT)),
        'mapping_ttl_seconds': getattr(args, 'mapping_ttl', 15.0),
        'devices': DEFAULT_CONFIG['devices'] if args.device is None else args.device,
        'consider_input_devices': getattr(args, 'consider_input_devices', True),
        'mouse_output': getattr(args, 'mouse_output', None),
        'mouse_outputs': getattr(args, 'mouse_outputs', None),
        'mute_labels': DEFAULT_CONFIG['mute_labels'] if args.mute_label is None else args.mute_label,
        'firefox_audio_blocks_standby': getattr(
            args, 'firefox_audio_blocks_standby', True),
        'idle_inhibition_apps': getattr(args, 'idle_inhibition_apps', []),
        'force_inhibition_apps': getattr(args, 'force_inhibition_apps', []),
        'cec_enabled': bool(args.cec),
        'cec_port': args.cec_port,
        'kde_timeout': bool(args.kde_timeout),
        'require_snapshot': bool(args.require_snapshot or args.cec),
        'axis_deadzone_percent': args.axis_deadzone_percent,
        'rz_deadzone_percent': args.rz_deadzone_percent,
        'device_axis_deadzones': getattr(args, 'device_axis_deadzones', {}),
    })
    startup_error = None
    equipment_snapshot = {
        'outputs': [], 'adapters': [], 'inputs': [],
        'errors': ['Host equipment discovery has not completed.'],
    }
    equipment_worker = None
    equipment_output = None
    equipment_started = equipment_next = 0.0
    app_windows = []
    app_windows_stamp = None

    def poll_equipment():
        nonlocal equipment_worker, equipment_output, equipment_started, equipment_next, equipment_snapshot
        now = time.monotonic()
        if equipment_worker is not None:
            if equipment_worker.poll() is not None or now - equipment_started > 8:
                try:
                    if equipment_worker.poll() is None:
                        equipment_worker.kill()
                        raise TimeoutError('Host equipment discovery timed out')
                    equipment_output.seek(0)
                    output = equipment_output.read()
                    if equipment_worker.returncode:
                        raise ValueError(output.strip() or 'Equipment helper failed')
                    inventory = json.loads(output)
                    if not isinstance(inventory, dict) or any(
                            not isinstance(inventory.get(key), list)
                            for key in ('outputs', 'adapters', 'inputs', 'errors')):
                        raise ValueError('Invalid equipment inventory')
                    equipment_snapshot = inventory
                except (OSError, ValueError, TimeoutError) as error:
                    log('Equipment discovery failed: ' + str(error))
                    equipment_snapshot = {
                        'outputs': [], 'adapters': [], 'inputs': [],
                        'errors': ['Host equipment discovery failed: ' + str(error)],
                    }
                finally:
                    equipment_worker.communicate()
                    equipment_output.close()
                    equipment_output = None
                    equipment_worker = None
                    equipment_next = now + 10
        if equipment_worker is None and now >= equipment_next:
            try:
                # A file avoids pipe-buffer stalls on hosts with many input devices.
                equipment_output = tempfile.TemporaryFile(mode='w+t')
                equipment_worker = subprocess.Popen(
                    [sys.executable, str(Path(__file__).with_name('equipment.py'))],
                    stdout=equipment_output, stderr=subprocess.STDOUT, text=True)
                equipment_started = now
            except OSError as error:
                if equipment_output is not None:
                    equipment_output.close()
                    equipment_output = None
                log('Could not launch equipment discovery: ' + str(error))
                equipment_snapshot = {
                    'outputs': [], 'adapters': [], 'inputs': [],
                    'errors': ['Could not launch host equipment discovery: ' + str(error)],
                }
                equipment_next = now + 10
        return True

    def activity(source):
        if startup_error:
            return
        now = time.monotonic()
        message = timer.activity(now)
        if power:
            power.activity(wake_requested=bool(message))
        elif message:
            log(message)

    def power_status():
        state_machine = getattr(power, 'state_machine', None)
        state = getattr(state_machine, 'state', None)
        power_state = getattr(state, 'value', 'unknown')
        return {
            'power_state': power_state if isinstance(power_state, str) else 'unknown',
            'pending_action': power.pending if power else None,
            'cec_fault': power.fault if power else None,
        }

    def apply_live_settings(config):
        nonlocal selector, devices, activity_provider, runtime_config, startup_error
        nonlocal power, kde_settings, target_output, worker, frames, scan_stamp, scan_error, next_scan
        nonlocal previous_status, previous_playback
        replacing_power = (config['cec_enabled'] != (power is not None)
                           or (power is not None and config['cec_port'] != runtime_config['cec_port']))
        if replacing_power and power is not None and (
                power.process is not None or power.pending is not None or power.may_be_off):
            raise RuntimeError(
                'Cannot change or disable the CEC adapter during a power operation '
                'or while TV wake recovery is required. Turn the TV on successfully, then retry.')
        staged_selector = selectors.DefaultSelector()
        staged_devices = {}
        opened = []
        staged_kde = kde_settings
        staged_power = power
        cleanup_errors = []

        def retire(resource, description):
            try:
                resource.close()
            except (OSError, subprocess.SubprocessError) as error:
                message = description + ': ' + str(error)
                cleanup_errors.append(message)
                log('Resource cleanup failed: ' + message)

        try:
            staged_provider = activity_provider_factory(
                ecodes, config['axis_deadzone_percent'], config['rz_deadzone_percent'],
                config['device_axis_deadzones'])
            reseed = any(config[key] != runtime_config[key] for key in (
                'axis_deadzone_percent', 'rz_deadzone_percent', 'device_axis_deadzones'))
            current = {state['identity']: state for state in devices.values()}
            selected_identities = set()
            selected_paths = [] if config['consider_input_devices'] else list(config['devices'])
            for path in dict.fromkeys(config['devices'] if config['consider_input_devices'] else []):
                identity = str(Path(path).resolve())
                if identity in selected_identities:
                    continue
                selected_identities.add(identity)
                selected_paths.append(path)
                state = current.get(identity)
                if state is None:
                    device = InputDevice(path)
                    opened.append(device)
                    state = {'path': path, 'identity': identity, 'device': device,
                             'axes': staged_provider.seed(device, path), 'dropped': False}
                elif reseed or state['path'] != path:
                    state = {**state, 'axes': staged_provider.seed(state['device'], path)}
                if state['path'] != path:
                    state = {**state, 'path': path}
                staged_selector.register(state['device'], selectors.EVENT_READ)
                staged_devices[state['device'].fd] = state
            if replacing_power:
                staged_power = cec_backend_factory(config['cec_port']) if config['cec_enabled'] else None
                if staged_power is not None:
                    staged_power.validate_port()
            if config['kde_timeout'] and kde_settings is None:
                staged_kde = KdeTimeout()
                staged_kde.fallback_timeout = config['timeout_seconds']
            elif not config['kde_timeout']:
                staged_kde = None
            config = {**config, 'devices': selected_paths}
            saved = save_config(config_path, {'schema_version': 1, **config})
        except Exception:
            retire(staged_selector, 'Uncommitted input selector')
            for device in opened:
                retire(device, 'Uncommitted input device')
            if staged_power is not None and staged_power is not power:
                retire(staged_power, 'Uncommitted CEC adapter')
            if staged_kde is not None and staged_kde is not kde_settings:
                retire(staged_kde, 'Uncommitted KDE timeout reader')
            raise

        old_selector, old_devices = selector, devices
        selector, devices, activity_provider = staged_selector, staged_devices, staged_provider
        old_power, power = power, staged_power
        old_config = runtime_config
        runtime_config = saved
        target_output = saved['target_output']
        args.mute_label = saved['mute_labels']
        args.require_snapshot = saved['require_snapshot']
        mapping.ttl = saved['mapping_ttl_seconds']
        old_kde, kde_settings = kde_settings, staged_kde
        if old_kde is not None and old_kde is not kde_settings:
            retire(old_kde, 'Old KDE timeout reader')
        if saved['mute_labels'] != old_config['mute_labels'] or startup_error:
            frames, scan_stamp = [], None
            scan_error = 'Waiting for a scan with the updated mute-tab labels'
            next_scan = 0
        if saved['target_output'] != old_config['target_output']:
            for state in devices.values():
                for axis in state['axes'].values():
                    axis.reset()
            previous_playback = False
        startup_error = None
        previous_status = None
        timer.set_timeout(saved['timeout_seconds'], time.monotonic())
        if kde_settings is not None:
            kde_settings.value = 'unread'
            kde_settings.next_read = 0
        if power is not None and power.pending == 'off':
            power.pending = None
            timer.cancel_standby(time.monotonic())
        status_snapshot.update({
            'service': 'running', 'cec_enabled': power is not None,
            'target_output': target_output, 'adapter': saved['cec_port'] if power else None,
            'fail_safe_reason': 'Settings applied; waiting for a fresh monitoring poll',
            'scan_status': scan_error, 'input_permission_help': None,
            'settings_error': None, 'pending_action': power.pending if power else None,
            'cec_fault': power.fault if power else None,
            'power_state': 'unknown' if replacing_power else status_snapshot['power_state'],
        })
        retire(old_selector, 'Old input selector')
        if old_power is not None and old_power is not power:
            retire(old_power, 'Old CEC adapter')
        for fd, state in old_devices.items():
            if fd not in devices:
                retire(state['device'], 'Removed input device')
        if cleanup_errors:
            status_snapshot['settings_error'] = '; '.join(cleanup_errors)
        log('Settings saved and applied live; service not restarted.')
        return saved

    class Receiver(dbus.service.Object):
        @dbus.service.method('net.local.CecActivity', in_signature='s', out_signature='')
        def Report(self, message):
            nonlocal focus, app_windows, app_windows_stamp
            message = str(message)
            if message.startswith('Fokus: '):
                new_focus = message[len('Fokus: '):].strip()
                if new_focus != focus:
                    focus = new_focus
                    # No comparison across focus boundaries.
                    for state in devices.values():
                        for axis in state['axes'].values():
                            axis.reset()
            elif message.startswith('Mouse-activity: '):
                output = message[len('Mouse-activity: '):].strip()
                if output in mouse_outputs(runtime_config) and output not in ('unknown', 'ingen', ''):
                    activity('mouse (TV activity report from KWin)')
            elif (message == 'TV-aktivitet: mus'
                  and TARGET in mouse_outputs(runtime_config)):
                # Older bridges identify only the original default TV output.
                activity('mouse (TV activity report from KWin)')
            elif message.startswith("Desktop-snapshot: "):
                first = mapping.snapshot_stamp is None
                raw_snapshot = message[len("Desktop-snapshot: "):]
                try:
                    app_windows = decode_windows(raw_snapshot)
                    app_windows_stamp = time.monotonic()
                except (ValueError, TypeError) as error:
                    app_windows_stamp = None
                    log('App window snapshot unavailable: ' + str(error))
                try:
                    payload = firefox_window_snapshot(raw_snapshot)
                except (ValueError, TypeError, OSError) as error:
                    mapping.snapshot_error = "Window processes could not be verified: " + str(error)
                else:
                    if mapping.snapshot(payload, time.monotonic()) and first:
                        log("Firefox live bridge connected; process identity verified")
            elif message.startswith('Firefox-snapshot: '):
                first = mapping.snapshot_stamp is None
                if mapping.snapshot(message[len('Firefox-snapshot: '):], time.monotonic()):
                    if first:
                        log('Firefox live bridge connected; receiving complete window reports')
            elif message.startswith('Firefox-media-snapshot: '):
                if not webextension_media.update(
                        message[len('Firefox-media-snapshot: '):], time.monotonic()):
                    log('Invalid Firefox WebExtension snapshot; using AT-SPI fallback')
            elif message.startswith('Firefox-vindu: '):
                payload = message[len('Firefox-vindu: '):]
                if ' | ' in payload:
                    output, title = payload.split(' | ', 1)
                    if title:
                        mapping.report(output.strip(), title, time.monotonic())

        @dbus.service.method('net.local.CecActivity', in_signature='', out_signature='s')
        def GetStatus(self):
            return json.dumps({
                **status_snapshot, 'configuration_saved': config_path.is_file(),
                'settings_apply': 'live', 'process_id': os.getpid(),
                'installed_apps': equipment_snapshot.get('apps'),
                'installed_apps_error': equipment_snapshot.get(
                    'apps_error', 'Installed app discovery has not completed'),
                'observed_apps': observed_apps(
                    inhibition_history.names, equipment_snapshot.get('apps') or []),
                'active_inhibitor_apps': observed_apps(
                    [request['app'] for request in plasma_inhibitions.requests
                     if request['kind'] == 'idle' and request['app'].strip()
                     and plasma_inhibitions.health(time.monotonic()) is None],
                    equipment_snapshot.get('apps') or []),
                'inhibition_history_error': inhibition_history.error,
            }, sort_keys=True)

        @dbus.service.method('net.local.CecActivity', in_signature='', out_signature='s')
        def GetConfig(self):
            return json.dumps({'schema_version': 1, **runtime_config}, sort_keys=True)

        @dbus.service.method('net.local.CecActivity', in_signature='', out_signature='s')
        def GetEquipment(self):
            return json.dumps(equipment_snapshot, sort_keys=True)

        @dbus.service.method('net.local.CecActivity', in_signature='s', out_signature='s')
        def ApplySettings(self, serialized_config):
            try:
                config = validate_config(json.loads(str(serialized_config)))
                if config.get('cec_enabled'):
                    config['require_snapshot'] = True
                saved = apply_live_settings(config)
            except (ValueError, TypeError, OSError, RuntimeError) as error:
                status_snapshot['settings_error'] = str(error)
                if isinstance(error, OSError) and error.filename in config['devices']:
                    status_snapshot['input_permission_help'] = input_permission_help(error)
                log('Live settings rejected; previous configuration retained: ' + str(error))
                raise dbus.DBusException(
                    'Settings not applied; previous configuration retained: ' + str(error))
            return json.dumps({
                'accepted': True,
                'applied_live': True,
                'config': {'schema_version': SCHEMA_VERSION, **saved},
            }, sort_keys=True)

        @dbus.service.method('net.local.CecActivity', in_signature='s', out_signature='s')
        def RequestPower(self, action):
            try:
                if startup_error:
                    raise RuntimeError(
                        'Monitor is configuration-only: ' + startup_error)
                request_manual_power(power, str(action),
                                     status_snapshot.get('fail_safe_reason'))
            except (RuntimeError, ValueError) as error:
                raise dbus.DBusException(str(error))
            return json.dumps({'accepted': True, 'action': str(action)})

    bus = dbus.SessionBus()
    plasma_inhibitions = PlasmaInhibitions(bus, dbus)
    try:
        name = dbus.service.BusName('net.local.CecActivity', bus=bus,
                                   do_not_queue=True)
        receiver = Receiver(bus, '/net/local/CecActivity')
    except dbus.DBusException as error:
        log('Cannot own the D-Bus name. Stop the existing monitor first: ' + str(error))
        return 2

    if activity_provider_factory is None:
        activity_provider_factory = EvdevActivityProvider
    activity_provider: ActivityProviderContract = activity_provider_factory(
        ecodes, args.axis_deadzone_percent, args.rz_deadzone_percent,
        runtime_config['device_axis_deadzones'])

    try:
        for path in dict.fromkeys(runtime_config['devices'] if runtime_config['consider_input_devices'] else []):
            device = InputDevice(path)
            try:
                axes = activity_provider.seed(device, path)
                selector.register(device, selectors.EVENT_READ)
            except Exception:
                device.close()
                raise
            devices[device.fd] = {'path': path, 'identity': str(Path(path).resolve()),
                                  'device': device, 'axes': axes, 'dropped': False}
    except OSError as error:
        startup_error = 'Cannot read input: ' + str(error)
        log(startup_error + '; configuration-only mode. No CEC commands will be sent.')
        for state in devices.values():
            state['device'].close()
        devices.clear()
        selector.close()
        selector = selectors.DefaultSelector()
        status_snapshot.update({
            'service': 'configuration-only',
            'cec_enabled': False,
            'fail_safe_reason': startup_error,
            'scan_status': 'Monitoring has not started',
            'input_permission_help': input_permission_help(error),
        })

    loop = GLib.MainLoop()
    def poll():
        nonlocal worker, worker_started, next_scan, frames, scan_stamp
        nonlocal worker_labels
        nonlocal scan_error, previous_status, warning_reported, previous_playback
        nonlocal startup_error, selector
        plasma_inhibitions.poll(time.monotonic())
        inhibition_history.observe(plasma_inhibitions.requests, time.monotonic())
        if startup_error:
            try:
                if power is not None and (power.process is not None or power.pending == 'on'):
                    power.poll()
                if worker is not None and (
                        worker.poll() is not None or time.monotonic() - worker_started >= SCAN_TIMEOUT):
                    if worker.poll() is None:
                        worker.kill()
                    worker.communicate()
                    worker = None
                    next_scan = 0
                if kde_settings:
                    kde_settings.poll(timer, time.monotonic())
                    status_snapshot.update({
                        'plasma_timeout_read': kde_settings.value != 'unread',
                        'plasma_timeout_seconds': (
                            kde_settings.value
                            if type(kde_settings.value) is int else None),
                        'plasma_timeout_fallback': (
                            getattr(kde_settings, 'fallback_active', False) is True),
                    })
                status_snapshot.update(power_status())
            except (OSError, subprocess.SubprocessError) as error:
                message = 'Paused monitor recovery failed: ' + str(error)
                if status_snapshot.get('settings_error') != message:
                    log(message)
                status_snapshot['settings_error'] = message
            return True
        try:
            for key, _ in selector.select(timeout=0):
                device = key.fileobj
                state = devices[device.fd]
                try:
                    events = device.read()
                    for event in events:
                        if event.type == ecodes.EV_SYN and event.code == ecodes.SYN_DROPPED:
                            state['dropped'] = True
                            continue
                        if state['dropped']:
                            if event.type == ecodes.EV_SYN and event.code == ecodes.SYN_REPORT:
                                # Discard queued pre-resync data: the ioctl below
                                # reads current state, potentially newer than it.
                                for _discard in events:
                                    pass
                                while True:
                                    try:
                                        for _discard in device.read():
                                            pass
                                    except BlockingIOError:
                                        break
                                state['axes'] = activity_provider.seed(device, state['path'])
                                state['dropped'] = False
                                break
                            continue
                        source = activity_provider.event_activity(
                            state, event, focus == target_output)
                        if source:
                            activity(source)
                except BlockingIOError:
                    pass
            now = time.monotonic()
            if worker is not None:
                if worker.poll() is not None:
                    output, errors = worker.communicate()
                    try:
                        if worker_labels == args.mute_label:
                            frames = media_provider.decode_scan(output, errors, worker.returncode)
                            scan_stamp = now
                            scan_error = None
                        if worker_labels == args.mute_label and errors.strip() and not warning_reported:
                            log('AT-SPI warning, but the scan returned readable '
                                'Firefox frames. Warning shown only once:')
                            log(errors.strip()[:800])
                            warning_reported = True
                    except Exception as error:
                        scan_error = str(error)
                    worker = None
                    next_scan = now + SCAN_INTERVAL if worker_labels == args.mute_label else now
                elif now - worker_started >= SCAN_TIMEOUT:
                    worker.kill()
                    worker.communicate()
                    worker = None
                    scan_error = 'AT-SPI did not respond within 5 seconds'
                    next_scan = now + SCAN_INTERVAL
            if worker is None and now >= next_scan:
                command = [sys.executable, str(Path(__file__).resolve()), '--atspi-scan']
                for label in args.mute_label:
                    command += ['--mute-label', label]
                worker = subprocess.Popen(command, stdout=subprocess.PIPE,
                                          stderr=subprocess.PIPE, text=True)
                worker_started = now
                worker_labels = list(args.mute_label)
            reason = None
            audible = False
            firefox_audio_error = None
            media_outputs = mouse_outputs(runtime_config)
            native_audio_states = [
                webextension_media.audio_state(mapping, now, output, mapping.ttl)
                for output in media_outputs
            ] if runtime_config['firefox_audio_blocks_standby'] else []
            if native_audio_states and all(state is not None for state in native_audio_states):
                audible = any(state[0] for state in native_audio_states)
                uncertain_audio = any(state[1] for state in native_audio_states)
                if uncertain_audio:
                    firefox_audio_error = (
                        'Firefox WebExtension reports audio, but its active window '
                        'cannot be uniquely matched to a KWin display')
                    reason = firefox_audio_error
            elif runtime_config['firefox_audio_blocks_standby'] and media_outputs:
                reason = scan_error
                if scan_stamp is None or now - scan_stamp > SCAN_MAX_AGE:
                    reason = reason or 'AT-SPI result is missing or stale'
                if reason is None:
                    if mapping.health(now, required=True) is None:
                        for message in match_diagnostics.update(
                                frames, mapping, now, scan_stamp):
                            log(message)
                    audio_states = [
                        media_provider.audio_state(frames, mapping, now, output)
                        for output in media_outputs
                    ]
                    audible = any(state[0] for state in audio_states)
                    uncertain_audio = any(state[1] for state in audio_states)
                    if uncertain_audio:
                        reason = (
                            'Firefox audio is active, but window mapping is '
                            'unknown, ambiguous or stale')
                    recent_titles = {
                        title for (title, _), stamp in mapping.reports.items()
                        if now - stamp <= mapping.ttl}
                    scanned_titles = {frame['title'] for frame in frames}
                    if recent_titles - scanned_titles:
                        reason = 'KWin windows are missing from AT-SPI; waiting for a match'
                    if not frames and mapping.reports:
                        reason = 'KWin reported Firefox, but AT-SPI found no frames'
                firefox_audio_error = reason
            mapping_error = mapping.health(now, args.require_snapshot)
            reason = reason or mapping_error
            if runtime_config['firefox_audio_blocks_standby'] and media_outputs:
                firefox_audio_error = firefox_audio_error or mapping_error
            inhibition_error = plasma_inhibitions.health(now)
            apps_error = equipment_snapshot.get('apps_error')
            if equipment_snapshot.get('apps') is None:
                apps_error = apps_error or 'Waiting for installed app discovery'
            blocking_apps = matching_inhibitions(
                plasma_inhibitions.requests if inhibition_error is None else [],
                runtime_config['idle_inhibition_apps'],
                equipment_snapshot.get('apps') or [], app_windows,
                app_windows_stamp is not None
                and now - app_windows_stamp <= mapping.ttl,
                media_outputs)
            blocking_apps.extend(forced_inhibitions(
                runtime_config['force_inhibition_apps'], equipment_snapshot.get('apps') or [],
                app_windows, app_windows_stamp is not None
                and now - app_windows_stamp <= mapping.ttl, media_outputs))
            if media_outputs and runtime_config['idle_inhibition_apps'] and inhibition_error:
                reason = reason or inhibition_error
            if media_outputs and runtime_config['idle_inhibition_apps'] and apps_error:
                reason = reason or str(apps_error)
            if blocking_apps:
                reason = reason or ('App standby block: '
                                    + blocking_apps[0]['app'] + ' — '
                                    + blocking_apps[0]['reason'])
            if kde_settings:
                settings_error = kde_settings.poll(timer, now)
                if settings_error and getattr(kde_settings, 'fallback_active', False) is not True:
                    reason = reason or settings_error
                if timer.timeout is None and power and power.pending == 'off':
                    power.pending = None
                    timer.cancel_standby(now)
            if power:
                if reason and power.pending == 'off':
                    power.pending = None
                    timer.cancel_standby(now)
                power.poll()
                reason = reason or power.fault
                if power.process is not None:
                    reason = reason or 'Waiting for CEC power status from TV'
            if focus is None:
                reason = reason or 'Waiting for a focus report from KWin'
            if any(state['dropped'] for state in devices.values()):
                reason = reason or 'Waiting for input resynchronization'
            if audible:
                activity('Firefox audio on a selected display')
            # Logging state is separate from activity and fail-safe decisions.
            # Unknown monitoring state must not be reported as playback stopping.
            if reason is None and audible != previous_playback:
                log('Firefox playback on a selected display ' + ('started' if audible else 'stopped'))
                previous_playback = audible
            if reason != previous_status:
                log('FAIL-SAFE: ' + reason + '; standby blocked' if reason else
                    'FAIL-SAFE cleared; monitoring restored')
                previous_status = reason
            message = timer.tick(now, uncertain=bool(reason))
            if message:
                if power:
                    power.request('off')
                else:
                    log(message)
            status_snapshot.update({
                'service': 'running',
                **power_status(),
                'plasma_timeout_read': bool(
                    kde_settings and kde_settings.value != 'unread'),
                'plasma_timeout_seconds': (
                    kde_settings.value
                    if kde_settings and type(kde_settings.value) is int else None),
                'plasma_timeout_fallback': bool(
                    kde_settings and
                    getattr(kde_settings, 'fallback_active', False) is True),
                'fail_safe_reason': reason,
                'playback_active': audible,
                'firefox_audio_error': firefox_audio_error,
                'blocking_apps': blocking_apps,
                'inhibitions_error': inhibition_error,
                'scan_status': scan_error,
            })
        except Exception as error:
            # An input disconnect or callback failure must never become silence.
            log('Monitor stopped fail-safe: ' + repr(error))
            startup_error = 'Monitoring input failed: ' + str(error)
            selector.close()
            selector = selectors.DefaultSelector()
            for state in devices.values():
                state['device'].close()
            devices.clear()
            if power is not None and power.pending == 'off':
                power.pending = None
                timer.cancel_standby(time.monotonic())
            status_snapshot.update({
                'service': 'configuration-only', 'cec_enabled': False,
                'fail_safe_reason': startup_error, 'scan_status': 'Monitoring paused',
                'input_permission_help': input_permission_help(error) if isinstance(error, OSError) else None,
            })
            return True
        return True

    timeout_description = (
        'KDE-managed display timeout (AC power)' if kde_settings else
        'automatic standby disabled' if timer.timeout is None else
        f'{timer.timeout:g}-second inactivity timeout')
    if startup_error:
        log('Configuration remains available over D-Bus; save corrected settings '
            'in the GUI to resume monitoring without a restart.')
    else:
        log(('LIVE CEC; ' if power else 'SIMULATION; ') + timeout_description + '.')
        if not power:
            log('No CEC commands will be sent. Press Ctrl+C to stop.')
        log('Requires an existing KWin bridge. Firefox must expose configured mute-tab labels for AT-SPI fallback.')
    try:
        GLib.timeout_add(100, poll)
        GLib.timeout_add(500, poll_equipment)
        loop.run()
    except KeyboardInterrupt:
        pass
    finally:
        if equipment_worker is not None:
            if equipment_worker.poll() is None:
                equipment_worker.kill()
            equipment_worker.communicate()
            equipment_output.close()
        if worker is not None:
            if worker.poll() is None:
                worker.kill()
            worker.communicate()
        for state in devices.values():
            state['device'].close()
        selector.close()
        # Keep D-Bus objects referenced for the entire loop lifetime.
        del receiver, name
        if kde_settings:
            kde_settings.close()
        if power and (not startup_error or power.process is not None or power.may_be_off):
            power.close()
        log('Monitor stopped.' if power else 'Simulation stopped. No CEC commands sent.')
    return 0


def self_test():
    import unittest
    from types import SimpleNamespace

    class Checks(unittest.TestCase):
        def permission_guidance(self, *, device_gid=50, mode=stat.S_IFCHR | 0o660,
                                members=(), process_groups=(), primary_gid=100,
                                group_exists=True):
            from unittest.mock import patch

            group = SimpleNamespace(gr_gid=50, gr_mem=members)
            user = SimpleNamespace(pw_name='test-user', pw_gid=primary_gid)
            with patch.object(os, 'stat', return_value=SimpleNamespace(
                    st_gid=device_gid, st_mode=mode)), \
                    patch.object(grp, 'getgrnam', return_value=group,
                                 side_effect=None if group_exists else KeyError('input')), \
                    patch.object(pwd, 'getpwuid', return_value=user), \
                    patch.object(os, 'getgroups', return_value=list(process_groups)), \
                    patch.object(os, 'getgid', return_value=primary_gid), \
                    patch.dict(globals(), {'log': lambda message: None}):
                return input_permission_help(PermissionError(
                    13, 'Permission denied', '/dev/input/event10'))

        def test_input_group_command_requires_verified_device_permissions(self):
            result = self.permission_guidance()
            self.assertEqual(result['path'], '/dev/input/event10')
            self.assertEqual(result['command'], 'sudo usermod -aG input -- test-user')
            self.assertIn('keyboard and other input events', result['message'])
            self.assertIn('Fully log out and log back in', result['message'])
            self.assertIn('user manager persists', result['message'])
            self.assertIn('intended input device', result['message'])
            self.assertIn('host terminal', result['message'])
            for arguments in (
                    {'group_exists': False}, {'device_gid': 70},
                    {'mode': stat.S_IFCHR | 0o600},
                    {'mode': stat.S_IFREG | 0o660}):
                with self.subTest(arguments=arguments):
                    self.assertEqual(
                        self.permission_guidance(**arguments)['command'], '')

        def test_vendor_only_group_command(self):
            import tempfile
            with tempfile.TemporaryDirectory() as directory:
                local = Path(directory) / 'group'
                vendor = Path(directory) / 'vendor'
                local.write_text('root:x:0:\n')
                vendor.write_text('input:x:50:\n')
                command, atomic = input_group_command(
                    'test-user', 50, local, vendor)
                self.assertTrue(atomic)
                script = shlex.split(command)
                self.assertEqual(script[:3], ['sudo', 'sh', '-c'])
                self.assertIn("if ! grep -q '^input:' /etc/group", script[3])
                self.assertIn('usermod -aG input -- test-user', script[3])
                local.write_text('input:x:50:test-user\n')
                self.assertEqual(input_group_command('test-user', 50, local, vendor),
                                 ('sudo usermod -aG input -- test-user', False))
                local.write_text('root:x:0:\n')
                self.assertFalse(input_group_command('test-user', 51, local, vendor)[1])

        def test_input_group_membership_and_session_are_distinguished(self):
            result = self.permission_guidance(members=['test-user'])
            self.assertEqual(result['command'], '')
            self.assertIn('already belongs to input', result['message'])
            self.assertIn('log out and log back in', result['message'])
            result = self.permission_guidance(process_groups=[50])
            self.assertEqual(result['command'], '')
            self.assertIn('already has the input group', result['message'])
            self.assertIn('ACLs', result['message'])
            result = self.permission_guidance(primary_gid=50)
            self.assertEqual(result['command'], '')
            self.assertIn('already has the input group', result['message'])

        def test_uninspectable_or_missing_input_does_not_suggest_group_changes(self):
            from unittest.mock import patch

            with patch.object(os, 'stat', side_effect=OSError('unavailable')), \
                    patch.dict(globals(), {'log': lambda message: None}):
                result = input_permission_help(PermissionError(
                    13, 'Permission denied', '/dev/input/event10'))
            self.assertEqual(result['command'], '')
            self.assertIn('selected input path', result['message'])
            result = input_permission_help(FileNotFoundError(
                2, 'No such file', '/dev/input/event10'))
            self.assertEqual(result['command'], '')

        def test_configurable_timeout(self):
            timer = Timer(0, timeout=600)
            self.assertIsNone(timer.tick(60))
            self.assertIsNone(timer.tick(599))
            self.assertIn('600', timer.tick(600))
            timer.activity(601)
            timer.timeout = None
            self.assertIsNone(timer.tick(100000))
            self.assertFalse(timer.expired)

        def test_timer(self):
            timer = Timer(0)
            self.assertIsNone(timer.tick(59.9))
            self.assertIn('TV in standby', timer.tick(60))
            self.assertIsNone(timer.tick(61))
            self.assertIn('TV on', timer.activity(62))
            self.assertIsNone(timer.activity(63))

        def test_fail_safe(self):
            timer = Timer(0)
            self.assertIsNone(timer.tick(100, True))
            self.assertIsNone(timer.tick(159))
            self.assertIn('TV in standby', timer.tick(160))
            self.assertIsNone(timer.tick(170, True))
            self.assertTrue(timer.expired)  # Uncertainty alone never wakes TV.

        def test_axes(self):
            a = Axis(SimpleNamespace(min=0, max=65535, fuzz=2, value=30000),
                     deadzone_percent=0.15)
            self.assertFalse(a.update(30001, True))
            self.assertFalse(a.update(50000, False))
            self.assertFalse(a.update(50001, True))
            self.assertFalse(a.update(-100000, True))
            self.assertFalse(a.update(50002, True))
            self.assertTrue(a.update(50100, True))
            a.update(50150, True)
            a.reset()
            self.assertFalse(a.update(50151, True))
            # Low-range hat axes still work; axes/devices never share state.
            b = Axis(SimpleNamespace(min=-1, max=1, fuzz=0, value=0))
            self.assertTrue(b.update(1, True))
            self.assertEqual(a.current, 50151)

        def test_scan_warning(self):
            frames = [{'title': 'Firefox', 'audio': True}]
            output = json.dumps({'ok': True, 'frames': frames})
            self.assertEqual(decode_scan(output, 'dbind-WARNING: stale socket', 0), frames)
            with self.assertRaises(RuntimeError):
                decode_scan(json.dumps({'ok': True, 'frames': []}), 'warning', 0)
            with self.assertRaises(RuntimeError):
                decode_scan(json.dumps({'ok': False, 'error': 'unreadable'}), '', 1)
            with self.assertRaises(RuntimeError):
                decode_scan(json.dumps({'ok': True, 'frames': [{}]}), '', 0)
            with self.assertRaises(ValueError):
                decode_scan('invalid JSON', '', 0)

        def test_atspi_frames(self):
            from unittest.mock import patch

            class Node:
                def __init__(self, role, name='', children=(), attributes=()):
                    self.role, self.name, self.children = role, name, children
                    self.childCount = len(children)
                    self.attributes = attributes

                def getAttributes(self):
                    return self.attributes

                def getRoleName(self):
                    return self.role

                def getChildAtIndex(self, index):
                    return self.children[index]

                def getState(self):
                    return SimpleNamespace(contains=lambda state: False)

                def get_process_id(self):
                    return 10

            class UnresponsiveApp:
                def get_process_id(self):
                    return 20

                @property
                def name(self):
                    raise AssertionError('Unrelated app name must not be queried')

            quiet = Node('frame', 'PSLive — Mozilla Firefox', [
                Node('page tab', 'PSLive'),
                Node('document web', children=[Node('button', 'Mute tab')])])
            sounding = Node('frame', 'Advanced Preferences — Mozilla Firefox', [
                Node('page tab', 'Advanced Preferences'),
                Node('page tab', 'Background YouTube', [Node('button', 'Mute tab')])])
            indicator = Node('frame', 'Localized sharing indicator',
                             attributes=["id:webrtcIndicator", "tag:html"])
            app = Node('application', 'Firefox', [quiet, indicator, sounding])
            desktop = Node('desktop', children=[UnresponsiveApp(), app])
            fake = SimpleNamespace(STATE_DEFUNCT=99,
                                   Registry=SimpleNamespace(getDesktop=lambda n: desktop))
            executable = lambda pid: {10: '/usr/lib/firefox/firefox',
                                      20: '/usr/bin/unrelated'}[pid]
            with patch.dict(sys.modules, {'pyatspi': fake}):
                result = scan_atspi(['Mute tab'], executable)
                for attributes in ((), ["id:main-window", "tag:html"],
                                   ["id:webrtcIndicator", "tag:button"]):
                    indicator.attributes = attributes
                    with self.assertRaises(RuntimeError):
                        scan_atspi(['Mute tab'], executable)
                with self.assertRaises(OSError):
                    scan_atspi(['Mute tab'], lambda pid: (_ for _ in ()).throw(OSError('denied')))
            self.assertEqual(result, [
                {'title': quiet.name, 'audio': False},
                {'title': sounding.name, 'audio': True}])

        def test_process_window_identity(self):
            rows = [{"pid": 10, "title": "Web App", "output": TARGET},
                    {"pid": 20, "title": "Firefox fake title", "output": TARGET}]
            paths = {10: "/app/lib/firefox/firefox-bin", 20: "/app/chromium/chrome"}
            self.assertEqual(json.loads(firefox_window_snapshot(json.dumps(rows), paths.__getitem__)),
                             [{"title": "Web App", "output": TARGET}])
            def inaccessible(pid):
                raise ProcessLookupError("process disappeared")
            with self.assertRaises(OSError):
                firefox_window_snapshot(json.dumps(rows), inaccessible)
            for pid in (0, -1, True, "10", None):
                rows[0]["pid"] = pid
                with self.assertRaises(ValueError):
                    firefox_window_snapshot(json.dumps(rows), paths.__getitem__)

        def test_snapshots(self):
            m = Mapping(15)
            self.assertIsNotNone(m.health(0, True))
            self.assertTrue(m.snapshot(json.dumps([{'title': 'A', 'output': TARGET}]), 0))
            self.assertEqual(m.output('A', Counter({'A': 1}), 1), TARGET)
            # Rename removes the old title immediately, not after a TTL.
            m.snapshot(json.dumps([{'title': 'B', 'output': TARGET}]), 2)
            self.assertNotIn(('A', TARGET), m.reports)
            # A move replaces the previous output instead of creating ambiguity.
            m.snapshot(json.dumps([{'title': 'B', 'output': 'HDMI-A-1'}]), 3)
            self.assertEqual(m.output('B', Counter({'B': 1}), 4), 'HDMI-A-1')
            m.report(TARGET, 'B', 4)
            self.assertEqual(len(m.reports), 1)
            rows = [{'title': 'B', 'output': TARGET}] * 2
            m.snapshot(json.dumps(rows), 5)
            self.assertIsNone(m.output('B', Counter({'B': 1}), 6))
            self.assertFalse(m.snapshot('[{}]', 7))
            self.assertIsNotNone(m.health(7))
            self.assertTrue(m.snapshot('[]', 8))
            self.assertEqual(m.reports, {})
            self.assertIsNone(m.health(9, True))
            self.assertIsNotNone(m.health(24, True))

        def test_axis_deadzone(self):
            wheel = Axis(SimpleNamespace(min=0, max=65535, fuzz=0, value=32768))
            self.assertEqual(wheel.threshold, 1311)
            for value in [32700, 32800, 33000, 32500, 32768] * 100:
                self.assertFalse(wheel.update(value, True))
            self.assertTrue(wheel.update(34200, True))
            pedal = Axis(SimpleNamespace(min=0, max=255, fuzz=0, value=255))
            self.assertEqual(pedal.threshold, 6)
            for value in [254, 253, 255, 250, 252, 255] * 100:
                self.assertFalse(pedal.update(value, True))
            self.assertTrue(pedal.update(240, True))
            # Off-screen changes always refresh the baseline, without activity.
            self.assertFalse(pedal.update(100, False))
            self.assertFalse(pedal.update(102, True))
            pedal.reset()
            self.assertFalse(pedal.update(103, True))
            noisy = Axis(SimpleNamespace(min=0, max=255, fuzz=5, value=255))
            self.assertEqual(noisy.threshold, 11)

        def test_rz_rest_noise(self):
            # Exercise several startup baselines across the observed rest band.
            for initial in (246, 249, 255):
                axis = Axis(SimpleNamespace(min=0, max=255, fuzz=0, value=initial),
                            deadzone_percent=5.0)
                self.assertEqual(axis.threshold, 13)
                for value in [255, 249, 248, 247, 246, 255] * 100:
                    self.assertFalse(axis.update(value, True))
                self.assertTrue(axis.update(220, True))
                self.assertTrue(axis.update(255, True))
                for value in [249, 246, 255] * 10:
                    self.assertFalse(axis.update(value, True))

        def test_match_diagnostics(self):
            m = Mapping(15)
            m.snapshot(json.dumps([{'title': 'New title', 'output': TARGET}]), 10)
            frames = [{'title': 'Old title', 'audio': True}]
            diag = MatchDiagnostics()
            lines = diag.update(frames, m, 11, 10.5)
            details = json.loads(lines[1].split(': ', 1)[1])
            self.assertEqual(details['mangler_i_AT_SPI'], ['New title'])
            self.assertEqual(details['bare_i_AT_SPI'], ['Old title'])
            self.assertEqual(details['KWin'][0]['skjerm'], TARGET)
            self.assertIn('0.5 s', lines[0])
            self.assertEqual(diag.update(frames, m, 12, 10.5), [])
            resolved = [{'title': 'New title', 'audio': True}]
            self.assertIn('2.0 s', diag.update(resolved, m, 13, 12)[0])
            self.assertEqual(diag.update(resolved, m, 14, 12), [])
            # Diagnostics must not change the matching input or its result.
            self.assertEqual(m.output('New title', Counter({'New title': 1}), 14), TARGET)

        def run_monitor_steps(self, steps, diagnostics_enabled=True, config_path=None,
                              timeout=int(DEFAULT_TIMEOUT), target=TARGET,
                              input_error=None, recovery_action=None,
                              input_error_after=0, equipment_result=None,
                              equipment_failure=None, equipment_updates=None):
            from unittest.mock import Mock, patch

            clock = SimpleNamespace(now=0)
            context = SimpleNamespace(receiver=None, poll=None)
            workers = []
            messages = []
            timer = Timer(0, timeout=timeout)
            mapping = Mapping(15)
            diagnostics = MatchDiagnostics()
            update = Mock(wraps=diagnostics.update) if diagnostics_enabled else Mock(return_value=[])
            power = Mock(fault=None, process=None, pending=None, may_be_off=False)

            class Object:
                def __init__(self, *args):
                    context.receiver = self

            def timeout_add(interval, callback):
                if interval == 100:
                    context.poll = callback
                else:
                    context.equipment_poll = callback

            def main_loop():
                if equipment_updates:
                    for inventory in equipment_updates:
                        worker_count = len(workers)
                        context.equipment_poll()
                        self.assertEqual(len(workers), worker_count + 1)
                        workers[-1].poll.return_value = 0
                        context.equipment_poll()
                        self.assertEqual(json.loads(context.receiver.GetEquipment()), inventory)
                        context.equipment_poll()
                        self.assertEqual(len(workers), worker_count + 1)
                        clock.now += 10
                if equipment_result is not None or equipment_failure:
                    self.assertIn('not completed', json.loads(
                        context.receiver.GetEquipment())['errors'][0])
                    context.equipment_poll()
                    equipment_process = workers[-1]
                    if equipment_failure == 'timeout':
                        clock.now = 9
                    else:
                        equipment_process.poll.return_value = 0
                    if equipment_failure == 'exit':
                        equipment_process.returncode = 1
                    context.equipment_poll()
                    if equipment_failure:
                        self.assertTrue(json.loads(
                            context.receiver.GetEquipment())['errors'])
                    else:
                        self.assertEqual(json.loads(
                            context.receiver.GetEquipment()), equipment_result)
                    worker_count = len(workers)
                    context.equipment_poll()
                    self.assertEqual(len(workers), worker_count)
                if recovery_action:
                    modules['evdev'].InputDevice.side_effect = None
                    recovery_action(context.receiver)
                if input_error:
                    self.assertIsNotNone(context.poll)
                    if not recovery_action:
                        self.assertTrue(context.poll())
                    return
                for step in steps:
                    now, snapshot, scan, *optional = step
                    clock.now = now
                    if snapshot is not None:
                        context.receiver.Report('Firefox-snapshot: ' + snapshot)
                    if optional and optional[0] is not None:
                        context.receiver.Report(
                            'Firefox-media-snapshot: ' + optional[0])
                    if len(optional) > 1 and optional[1] is not None:
                        context.receiver.Report('Fokus: ' + optional[1])
                    if len(optional) > 2:
                        for message in optional[2]:
                            context.receiver.Report(message)
                    if scan is not None:
                        output, errors, returncode = scan
                        workers[-1].poll.return_value = returncode
                        workers[-1].returncode = returncode
                        workers[-1].communicate.return_value = (output, errors)
                    self.assertTrue(context.poll())

            def start_worker(*args, **kwargs):
                if equipment_updates and str(args[0][-1]).endswith('/equipment.py'):
                    kwargs['stdout'].write(json.dumps(equipment_updates[len(workers)]))
                    kwargs['stdout'].flush()
                if (equipment_result is not None or equipment_failure) and str(args[0][-1]).endswith('/equipment.py'):
                    kwargs['stdout'].write(
                        'invalid' if equipment_failure else json.dumps(equipment_result))
                    kwargs['stdout'].flush()
                worker = Mock(returncode=0)
                worker.poll.return_value = None
                worker.communicate.return_value = ('', '')
                workers.append(worker)
                return worker

            session_bus = Mock()
            service = SimpleNamespace(
                Object=Object, BusName=Mock(),
                method=lambda *args, **kwargs: lambda method: method)
            dbus = SimpleNamespace(
                service=service, SessionBus=Mock(return_value=session_bus),
                DBusException=RuntimeError)
            loop = Mock()
            loop.run.side_effect = main_loop
            glib = SimpleNamespace(MainLoop=lambda: loop, timeout_add=timeout_add)
            device = Mock(fd=10)
            device.capabilities.return_value = {}
            selector = Mock()
            selector.select.return_value = []
            modules = {
                'dbus': dbus, 'dbus.service': service,
                'dbus.mainloop': SimpleNamespace(),
                'dbus.mainloop.glib': SimpleNamespace(DBusGMainLoop=Mock()),
                'gi': SimpleNamespace(), 'gi.repository': SimpleNamespace(GLib=glib),
                'evdev': SimpleNamespace(InputDevice=Mock(return_value=device),
                                         ecodes=SimpleNamespace(EV_ABS=3, EV_KEY=1,
                                                                ABS_RZ=2, ABS_MT_SLOT=47,
                                                                ABS={})),
            }
            if input_error:
                modules['evdev'].InputDevice.side_effect = (
                    [device] * input_error_after + [input_error])
            args = SimpleNamespace(kde_timeout=False, cec=True, cec_port='unused',
                                   mapping_ttl=15, require_snapshot=True, device=['unused'],
                                   mute_label=['Mute tab'], axis_deadzone_percent=2.0,
                                   rz_deadzone_percent=5.0,
                                   timeout_seconds=timeout,
                                   target=target,
                                   config=str(config_path) if config_path else None)
            if input_error_after:
                args.device = ['first-input', 'unreadable-input']
            if config_path and config_path.exists():
                stored = load_config(config_path)
                args.device = stored['devices']
                args.target = stored['target_output']
            with patch.dict(sys.modules, modules), \
                    patch.dict(globals(), {
                        'Timer': Mock(return_value=timer), 'CecPower': Mock(return_value=power),
                        'Mapping': Mock(return_value=mapping),
                        'MatchDiagnostics': Mock(return_value=diagnostics),
                        'input_permission_help': Mock(return_value={
                            'message': 'Host input permission guidance', 'command': ''}),
                        'log': messages.append}), \
                    patch.object(diagnostics, 'update', update), \
                    patch.object(time, 'monotonic', lambda: clock.now), \
                    patch.object(selectors, 'DefaultSelector',
                                 side_effect=[selector] + [Mock(select=Mock(return_value=[])) for _ in range(10)]), \
                    patch.object(subprocess, 'run', return_value=SimpleNamespace(
                        returncode=0, stdout='', stderr='')) as command_run, \
                    patch.object(subprocess, 'Popen', side_effect=start_worker):
                self.assertEqual(run(args), 0)
            return SimpleNamespace(
                messages=[message for message in messages if message.startswith('MATCH-DIAG:')],
                all_messages=messages, diagnostics=diagnostics, update=update,
                timer=vars(timer), mapping=vars(mapping), power_calls=power.mock_calls,
                receiver=context.receiver, power=power, command_run=command_run,
                device=device, selector=selector, workers=workers,
                status=json.loads(context.receiver.GetStatus()))

        def test_equipment_api_is_cached_and_available_after_input_failure(self):
            inventory = {
                'outputs': [{'path': 'DP-2', 'label': 'DP-2'}],
                'adapters': [], 'inputs': [], 'errors': [],
            }
            result = self.run_monitor_steps(
                [], input_error=PermissionError(13, 'Permission denied'),
                equipment_result=inventory)
            self.assertEqual(json.loads(result.receiver.GetEquipment()), inventory)
            result.power.poll.assert_not_called()
            result.power.request.assert_not_called()

        def test_equipment_failures_are_reported_without_disabling_configuration(self):
            for failure in ('invalid', 'exit', 'timeout'):
                with self.subTest(failure=failure):
                    result = self.run_monitor_steps(
                        [], input_error=PermissionError(13, 'Permission denied'),
                        equipment_failure=failure)
                    inventory = json.loads(result.receiver.GetEquipment())
                    self.assertEqual(inventory['outputs'], [])
                    self.assertIn('failed', inventory['errors'][0])
                    self.assertEqual(result.status['service'], 'configuration-only')
                    self.assertTrue(json.loads(result.receiver.GetConfig()))
                    if failure == 'timeout':
                        result.workers[0].kill.assert_called_once()

        def test_equipment_cache_refreshes_for_plug_unplug_and_replug(self):
            connected = {
                'outputs': [{'path': 'DP-2', 'label': 'DP-2'}],
                'adapters': [{'path': '/dev/serial/by-id/CEC', 'label': 'CEC'}],
                'inputs': [{'path': '/dev/input/by-id/keyboard', 'label': 'Keyboard'}],
                'errors': [],
            }
            empty = {'outputs': [], 'adapters': [], 'inputs': [], 'errors': []}
            result = self.run_monitor_steps(
                [], input_error=PermissionError(13, 'Permission denied'),
                equipment_updates=[connected, empty, connected])
            self.assertEqual(len(result.workers), 3)
            self.assertEqual(json.loads(result.receiver.GetEquipment()), connected)
            result.power.poll.assert_not_called()
            result.power.request.assert_not_called()

        def test_input_startup_failure_keeps_configuration_api_without_cec(self):
            import tempfile

            for error in (
                    PermissionError(13, 'Permission denied', '/dev/input/event10'),
                    FileNotFoundError(2, 'No such file', '/dev/input/event10')):
                with self.subTest(error=error), tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / 'config.json'

                    def configure(receiver):
                        status = json.loads(receiver.GetStatus())
                        self.assertEqual(status['service'], 'configuration-only')
                        self.assertFalse(status['cec_enabled'])
                        self.assertIn(str(error), status['fail_safe_reason'])
                        self.assertEqual(status['input_permission_help']['message'],
                                         'Host input permission guidance')
                        initial = json.loads(receiver.GetConfig())
                        self.assertFalse(status['configuration_saved'])
                        self.assertTrue(initial['cec_enabled'])
                        for action in ('on', 'off'):
                            with self.assertRaisesRegex(RuntimeError, 'configuration-only'):
                                receiver.RequestPower(action)
                        receiver.Report('Mouse-activity: ' + TARGET)
                        config = {
                            **initial, 'target_output': 'DP-1',
                            'devices': ['/dev/input/by-id/selected-keyboard'],
                        }
                        result = json.loads(receiver.ApplySettings(json.dumps(config)))
                        self.assertTrue(result['accepted'])
                        self.assertTrue(json.loads(receiver.GetStatus())['configuration_saved'])
                        self.assertEqual(
                            json.loads(receiver.GetConfig())['devices'],
                            config['devices'])

                    result = self.run_monitor_steps(
                        [], config_path=path, input_error=error,
                        recovery_action=configure)
                    result.power.request.assert_not_called()
                    result.power.activity.assert_not_called()
                    result.power.poll.assert_not_called()
                    result.power.close.assert_called_once()
                    result.command_run.assert_not_called()
                    self.assertEqual(
                        json.loads(path.read_text())['target_output'], 'DP-1')
                    restarted = self.run_monitor_steps(
                        [], config_path=path, input_error=error)
                    self.assertTrue(restarted.status['configuration_saved'])
                    self.assertEqual(
                        json.loads(restarted.receiver.GetConfig())['devices'],
                        ['/dev/input/by-id/selected-keyboard'])

        def test_partial_input_initialization_is_closed_before_configuration_only(self):
            result = self.run_monitor_steps(
                [], input_error=PermissionError(13, 'Permission denied'),
                input_error_after=1)
            self.assertEqual(result.status['service'], 'configuration-only')
            result.device.close.assert_called_once()
            result.selector.close.assert_called_once()
            self.assertEqual(result.workers, [])
            result.power.poll.assert_not_called()
            result.power.close.assert_not_called()

        def test_mouse_reports_follow_configured_target_not_default_display(self):
            for report, expected in (
                    ('Mouse-activity: DP-1', 1),
                    ('Mouse-activity: HDMI-A-2', 0),
                    ('Mouse-activity: unknown', 0),
                    ('TV-aktivitet: mus', 0)):
                with self.subTest(report=report):
                    result = self.run_monitor_steps([
                        (0, None, None, None, None, [report])], target='DP-1')
                    self.assertEqual(result.power.activity.call_count, expected)
            legacy = self.run_monitor_steps([
                (0, None, None, None, None, ['TV-aktivitet: mus'])])
            legacy.power.activity.assert_called_once()

        def test_runtime_startup_messages_reflect_configured_timeout(self):
            custom = self.run_monitor_steps([(0, None, None)], timeout=600)
            self.assertIn('LIVE CEC; 600-second inactivity timeout.',
                          custom.all_messages)
            disabled = self.run_monitor_steps([(0, None, None)], timeout=None)
            self.assertIn('LIVE CEC; automatic standby disabled.',
                          disabled.all_messages)
            self.assertEqual(
                Mapping(15).health(0, required=True),
                'Waiting for Firefox snapshot from the live bridge')
            self.assertIn('Waiting for the first AT-SPI scan',
                          custom.status['fail_safe_reason'])

        def test_runtime_match_diagnostics(self):
            snapshot = json.dumps([{'title': 'New title', 'output': TARGET}])
            mismatch = (json.dumps({'ok': True, 'frames': [
                {'title': 'Old title', 'audio': False}]}), '', 0)
            match = (json.dumps({'ok': True, 'frames': [
                {'title': 'New title', 'audio': False}]}), '', 0)
            steps = [(0, snapshot, None)]
            for now in range(1, 36):
                steps.append((now, snapshot, (match if now >= 34 else mismatch)
                              if now % 3 == 1 else None))
            result = self.run_monitor_steps(steps)
            self.assertEqual(len(result.messages), 5)
            self.assertIn('mismatch for 0.0 s', result.messages[0])
            self.assertIn('mismatch for 30.0 s', result.messages[2])
            self.assertIn('matching restored after 33.0 s', result.messages[4])
            self.assertIsNone(result.diagnostics.started)
            self.assertIsNone(result.diagnostics.signature)
            self.assertTrue(any('KWin windows are missing from AT-SPI' in message
                                for message in result.all_messages))
            baseline = self.run_monitor_steps(steps, diagnostics_enabled=False)
            self.assertEqual(result.timer, baseline.timer)
            self.assertEqual(result.mapping, baseline.mapping)
            self.assertEqual(result.power_calls, baseline.power_calls)
            self.assertEqual([message for message in result.all_messages
                              if not message.startswith('MATCH-DIAG:')], baseline.all_messages)

        def test_runtime_invalid_scans_preserve_match_diagnostics(self):
            snapshot = json.dumps([{'title': 'New title', 'output': TARGET}])
            mismatch = (json.dumps({'ok': True, 'frames': []}), '', 0)
            match = (json.dumps({'ok': True, 'frames': [
                {'title': 'New title', 'audio': False}]}), '', 0)
            invalid_scans = [
                ('invalid JSON', '', 0),
                (json.dumps({'ok': False, 'error': 'unreadable'}), '', 1),
                (json.dumps({'ok': True, 'frames': [{}]}), '', 0),
                (json.dumps({'ok': True, 'frames': []}), 'warning', 0),
            ]
            for invalid in invalid_scans:
                with self.subTest(scan=invalid):
                    result = self.run_monitor_steps([
                        (0, snapshot, None), (1, None, mismatch),
                        (3, None, None), (4, '[]', invalid),
                        (5, None, None)])
                    self.assertEqual(len(result.messages), 2)
                    self.assertEqual(result.diagnostics.started, 1)
                    self.assertEqual(result.update.call_count, 2)
                    recovered = self.run_monitor_steps([
                        (0, snapshot, None), (1, None, mismatch),
                        (3, None, None), (4, '[]', invalid),
                        (6, None, None), (7, snapshot, match)])
                    self.assertIn('matching restored', recovered.messages[-1])

        def test_runtime_stale_observations_preserve_match_diagnostics(self):
            snapshot = json.dumps([{'title': 'New title', 'output': TARGET}])
            mismatch = (json.dumps({'ok': True, 'frames': []}), '', 0)
            cases = {
                'no scan': [(0, snapshot, None)],
                'no snapshot': [(0, None, None), (1, None, mismatch)],
                'failed snapshot': [(0, snapshot, None), (1, None, mismatch),
                                    (2, '[{}]', None)],
                'stale snapshot': [(0, snapshot, None), (1, None, mismatch),
                                   (16, None, mismatch)],
                'stale scan': [(0, snapshot, None), (1, None, mismatch),
                               (9, None, None), (10, '[]', None)],
                'timed out scan': [(0, snapshot, None), (1, None, mismatch),
                                   (3, None, None), (8, '[]', None)],
            }
            calls = {'no scan': 0, 'no snapshot': 0, 'failed snapshot': 1,
                     'stale snapshot': 1, 'stale scan': 2, 'timed out scan': 2}
            for name, steps in cases.items():
                with self.subTest(case=name):
                    result = self.run_monitor_steps(steps)
                    expected = 0 if name in ('no scan', 'no snapshot') else 2
                    self.assertEqual(len(result.messages), expected)
                    self.assertEqual(result.diagnostics.started,
                                     None if expected == 0 else 1)
                    self.assertEqual(result.update.call_count, calls[name])

        def test_dbus_status_and_manual_control_api(self):
            snapshot = json.dumps([{'title': 'Firefox', 'output': TARGET}])
            result = self.run_monitor_steps([(0, snapshot, None)])
            status = json.loads(result.receiver.GetStatus())
            self.assertEqual(status['service'], 'running')
            self.assertTrue(status['cec_enabled'])
            self.assertIsNotNone(status['fail_safe_reason'])
            with self.assertRaisesRegex(RuntimeError, 'Standby blocked'):
                result.receiver.RequestPower('off')
            result.receiver.RequestPower('on')
            result.power.request.assert_called_once_with('on')

        def test_firefox_scan_timeout_is_exposed_as_unknown_audio_status(self):
            result = self.run_monitor_steps([(0, '[]', None), (6, '[]', None)])
            self.assertFalse(result.status['playback_active'])
            self.assertIn('AT-SPI did not respond', result.status['firefox_audio_error'])
            self.assertIn('AT-SPI did not respond', result.status['fail_safe_reason'])

        def test_dbus_config_api_validates_persists_and_applies_live(self):
            import tempfile
            from pathlib import Path
            from unittest.mock import patch

            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'config.json'
                def apply(receiver):
                    initial = json.loads(receiver.GetConfig())
                    self.assertEqual(initial['schema_version'], 1)
                    self.assertTrue(initial['cec_enabled'])
                    with self.assertRaisesRegex(RuntimeError, 'Unsupported configuration'):
                        receiver.ApplySettings(json.dumps({'schema_version': 2}))
                    request = {**initial, 'target_output': 'DP-1', 'require_snapshot': False}
                    response = json.loads(
                        receiver.ApplySettings(json.dumps(request)))
                    self.assertTrue(response['accepted'])
                    self.assertTrue(response['applied_live'])
                    self.assertEqual(response['config'], json.loads(path.read_text()))
                result = self.run_monitor_steps(
                    [(0, None, None)], config_path=path, recovery_action=apply)
                saved = json.loads(path.read_text(encoding='utf-8'))
                self.assertEqual(saved['target_output'], 'DP-1')
                self.assertTrue(saved['require_snapshot'])
                self.assertEqual(
                    json.loads(result.receiver.GetConfig())['target_output'], 'DP-1')
                result.command_run.assert_not_called()

        def test_webextension_audio_uses_active_window_display_without_atspi(self):
            window_map = json.dumps([
                {'title': 'TV video — Mozilla Firefox', 'output': TARGET},
            ])
            media = json.dumps({
                'version': 1,
                'windows': [{
                    'window_id': 3,
                    'active_title': 'TV video',
                    'tabs': [{'audible': True, 'muted': False}],
                }],
            })
            result = self.run_monitor_steps([
                (0, window_map, None, media, TARGET)])
            self.assertTrue(result.status['playback_active'])
            self.assertIsNone(result.status['fail_safe_reason'])
            self.assertIsNone(result.status['firefox_audio_error'])
            self.assertTrue(any(
                call.kwargs.get('wake_requested') is False
                for call in result.power.activity.call_args_list))

        def test_matching(self):
            m = Mapping(15)
            frames = [{'title': 'Preferences — Mozilla Firefox', 'audio': True}]
            self.assertEqual(audio_state(frames, m, 0), (False, True))
            m.report(TARGET, frames[0]['title'], 0)
            self.assertEqual(audio_state(frames, m, 1), (True, False))
            self.assertEqual(audio_state(frames * 2, m, 1), (False, True))
            m.report('HDMI-A-1', frames[0]['title'], 1)
            self.assertEqual(audio_state(frames, m, 2), (False, True))
            self.assertEqual(audio_state(frames, m, 17), (False, True))
            m.report('HDMI-A-1', frames[0]['title'], 18)
            self.assertEqual(audio_state(frames, m, 18), (False, False))
            frames[0]['audio'] = False
            self.assertEqual(audio_state(frames, m, 99), (False, False))

    suite = unittest.defaultTestLoader.loadTestsFromTestCase(Checks)
    return 0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--config', help='JSON configuration file with a versioned schema')
    parser.add_argument('--target', help='Display output controlling the TV')
    parser.add_argument('--timeout-seconds', type=int,
                        help='Seconds of inactivity before standby; null in configuration disables it')
    parser.add_argument('--rz-deadzone-percent', type=float, default=None,
                        help='ABS_RZ deadzone percentage (default: 0)')
    parser.add_argument('--axis-deadzone-percent', type=float, default=None,
                        help='Minimum axis movement as a percentage of its range (default: 0)')
    parser.add_argument('--kde-timeout', action=argparse.BooleanOptionalAction, default=None,
                        help='Follow KDE display timeout for AC power')
    parser.add_argument('--cec', action=argparse.BooleanOptionalAction, default=None,
                        help='Send real CEC standby/on commands')
    parser.add_argument('--cec-port')
    parser.add_argument('--device', action='append', help='Input device path; may be repeated')
    parser.add_argument('--mapping-ttl', type=float, default=None,
                        help='Seconds before a window report becomes stale (default: 15)')
    parser.add_argument('--mute-label', action='append', default=None,
                        help='Exact Firefox AT-SPI button label (default: Mute tab)')
    parser.add_argument('--require-snapshot', action=argparse.BooleanOptionalAction, default=None,
                        help='Block standby without fresh Firefox live-bridge reports')
    parser.add_argument('--self-test', action='store_true')
    parser.add_argument('--atspi-scan', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        config = load_config(args.config) if args.config else {
            'schema_version': 1, **DEFAULT_CONFIG}
        config = merge_cli(config, args)
    except ValueError as error:
        parser.error(str(error))
    args.target = config['target_output']
    args.timeout_seconds = config['timeout_seconds']
    args.mapping_ttl = config['mapping_ttl_seconds']
    args.device = config['devices']
    args.consider_input_devices = config['consider_input_devices']
    args.mouse_output = config['mouse_output']
    args.mouse_outputs = config['mouse_outputs']
    args.firefox_audio_blocks_standby = config['firefox_audio_blocks_standby']
    args.idle_inhibition_apps = config['idle_inhibition_apps']
    args.force_inhibition_apps = config['force_inhibition_apps']
    args.mute_label = config['mute_labels']
    args.cec = config['cec_enabled']
    args.cec_port = config['cec_port']
    args.kde_timeout = config['kde_timeout']
    args.require_snapshot = config['require_snapshot']
    args.axis_deadzone_percent = config['axis_deadzone_percent']
    args.rz_deadzone_percent = config['rz_deadzone_percent']
    args.device_axis_deadzones = config['device_axis_deadzones']
    if args.cec:
        args.require_snapshot = True
    if not math.isfinite(args.rz_deadzone_percent) or not 0 <= args.rz_deadzone_percent <= 25:
        parser.error('--rz-deadzone-percent must be from 0 to 25')
    if not math.isfinite(args.axis_deadzone_percent) or not 0 <= args.axis_deadzone_percent <= 25:
        parser.error('--axis-deadzone-percent must be from 0 to 25')
    if not math.isfinite(args.mapping_ttl) or args.mapping_ttl <= 0:
        parser.error('--mapping-ttl must be positive and finite')
    if args.self_test:
        return self_test()
    if args.atspi_scan:
        try:
            print(json.dumps({'ok': True, 'frames': scan_atspi(args.mute_label)}))
            return 0
        except Exception as error:
            print(json.dumps({'ok': False, 'error': repr(error)}))
            return 1
    try:
        return run(args)
    except Exception as error:
        log('Could not start monitor: ' + repr(error))
        return 2


if __name__ == '__main__':
    sys.exit(main())
