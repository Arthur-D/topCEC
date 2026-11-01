#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""TV activity monitor with opt-in real CEC. Default remains simulation.
--cec enables actual power commands, requires fresh KWin snapshots and stops on
adapter failures. Use start-cec-live.fish to exclude the old idle controller.
"""
import argparse
from collections import Counter
import json
import math
import selectors
import subprocess
import subprocess
import sys
import time
from pathlib import Path

from activity_policy import ActivityPolicy, DEFAULT_TIMEOUT
from cec_power_state import CecPowerStateMachine
from configuration import (
    DEFAULT_CONFIG, default_config_path, load_config, merge_cli, save_config,
    validate_config,
)
from firefox_media import FirefoxWebExtensionProvider
from providers import ActivityProvider as ActivityProviderContract
from providers import CecBackend, MediaProvider as MediaProviderContract

TARGET = 'HDMI-A-2'
TIMEOUT = DEFAULT_TIMEOUT
SCAN_INTERVAL = 2.0
SCAN_TIMEOUT = 5.0
SCAN_MAX_AGE = 8.0


def log(message):
    print(time.strftime('[%H:%M:%S]'), message, flush=True)


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
                    raise RuntimeError(result.get('error', errors or 'CEC feilet'))
                log('CEC bekreftet: TV ' + result['state'])
                self.state_machine.confirm(result['state'])
            except Exception as error:
                self.state_machine.fail(error, self.sent)
                log('CEC-FEIL: ' + self.fault + '; videre AV sperret')
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
            log('CEC sender: ' + ('AV' if action == 'off' else 'PÅ'))

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
            log('Avslutter: forsøker å sette TV på igjen')
            try:
                result = subprocess.run(
                    [sys.executable, str(Path(__file__).with_name('cec-power-command.py')),
                     'on', '--port', self.port], capture_output=True, text=True, timeout=130)
                log('CEC avslutning: ' + result.stdout.strip())
            except Exception as error:
                log('CEC avslutningsfeil: ' + str(error))


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
    def __init__(self):
        self.process = None
        self.next_read = 0
        self.started = 0
        self.error = 'venter på KDE-tidsgrense'
        self.value = 'unread'

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
                        raise ValueError('ugyldig tidsgrense')
                    if value != self.value:
                        self.value = value
                        timer.set_timeout(value, now)
                        log('KDE-tidsgrense (nettstrøm): ' +
                            ('aldri — automatisk AV deaktivert' if value is None
                             else f'{value} sekunder ({value / 60:g} minutter)'))
                    self.error = None
                except Exception as error:
                    self.error = 'kan ikke lese KDE-tidsgrense: ' + str(error)
                self.process = None
                self.next_read = now + 5
            elif now - self.started > 5:
                self.process.kill()
                self.process.communicate()
                self.process = None
                self.next_read = now + 5
                self.error = 'KDE-innstillinger svarte ikke'
        if self.process is None and now >= self.next_read:
            self.process = subprocess.Popen(
                [sys.executable, str(Path(__file__).with_name('cec-kde-settings.py'))],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            self.started = now
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
    def __init__(self, ecodes, axis_deadzone_percent, rz_deadzone_percent):
        self.ecodes = ecodes
        self.axis_deadzone_percent = axis_deadzone_percent
        self.rz_deadzone_percent = rz_deadzone_percent

    def seed(self, device):
        ecodes = self.ecodes
        return {code: Axis(info, self.rz_deadzone_percent if code == ecodes.ABS_RZ
                           else self.axis_deadzone_percent) for code, info in
                device.capabilities(absinfo=True).get(ecodes.EV_ABS, [])
                if code < ecodes.ABS_MT_SLOT}

    def event_activity(self, state, event, focused):
        ecodes = self.ecodes
        if event.type == ecodes.EV_ABS:
            axis = state['axes'].get(event.code)
            if axis and axis.update(event.value, focused):
                return (f'ratt/pedal ({ecodes.ABS.get(event.code, event.code)}, '
                        f'verdi {event.value}, terskel {axis.threshold})')
        elif event.type == ecodes.EV_KEY and event.value in (1, 2) and focused:
            return 'tastatur/ratt'
        return None


def firefox_window_snapshot(payload, read_exe=None):
    """Resolve KWin PIDs on the host; never infer browser identity from titles."""
    if read_exe is None:
        read_exe = lambda pid: str(Path(f"/proc/{pid}/exe").readlink())
    rows = json.loads(payload)
    if not isinstance(rows, list):
        raise ValueError("Ugyldig skrivebordssnapshot")
    result = []
    for row in rows:
        if (not isinstance(row, dict) or type(row.get("pid")) is not int
                or row["pid"] <= 0 or not isinstance(row.get("title"), str)
                or not isinstance(row.get("output"), str)):
            raise ValueError("Ugyldig vindusidentitet")
        executable = Path(read_exe(row["pid"]))
        if (executable.name in ("firefox", "firefox-bin")
                and executable.parent.name == "firefox"):
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
                raise ValueError('Ugyldig Firefox-snapshot')
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
            return 'ugyldig Firefox-snapshot'
        if self.snapshot_stamp is None:
            return 'venter på Firefox-snapshot fra live-broen' if required else None
        if now - self.snapshot_stamp > self.ttl:
            return 'Firefox-broens oppdateringer har stoppet'
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
            return [f'MATCH-DIAG: samsvar gjenopprettet etter {duration:.1f} s']
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
            return 'ukjent' if stamp is None else f'{now - stamp:.1f} s'
        details = {
            'mangler_i_AT_SPI': missing,
            'bare_i_AT_SPI': sorted({title for title, _ in atspi} -
                                   {title for title, _ in kwin}),
            'KWin': [{'tittel': title, 'skjerm': output} for title, output in kwin],
            'AT_SPI': [{'tittel': title, 'lyd': audio} for title, audio in atspi],
        }
        return [f'MATCH-DIAG: avvik i {now - self.started:.1f} s; '
                f'KWin-rapport alder {age(mapping.snapshot_stamp)}; '
                f'AT-SPI-resultat alder {age(scan_stamp)}',
                'MATCH-DIAG: ' + json.dumps(details, ensure_ascii=False)]


def decode_scan(output, errors, returncode):
    """stderr is diagnostic text, not the scanner's structured result."""
    result = json.loads(output)
    if returncode or result.get('ok') is not True:
        raise RuntimeError(result.get('error', 'AT-SPI-skanning feilet'))
    frames = result.get('frames')
    if not isinstance(frames, list) or any(
        not isinstance(frame, dict)
        or not isinstance(frame.get('title'), str)
        or not isinstance(frame.get('audio'), bool)
        for frame in frames
    ):
        raise RuntimeError('Ugyldig AT-SPI-resultat')
    if errors.strip() and not frames:
        raise RuntimeError('AT-SPI-advarsel og ingen lesbare Firefox-frames')
    return frames


def scan_atspi(mute_labels):
    """Separate process so broken AT-SPI cannot freeze evdev/D-Bus handling."""
    import pyatspi
    desktop = pyatspi.Registry.getDesktop(0)
    frames = []
    visited = 0

    def walk(node, inside_tab=False):
        nonlocal visited
        visited += 1
        if visited > 12000:
            raise RuntimeError('AT-SPI-treet er for stort; ufullstendig skanning')
        if node is None:
            raise RuntimeError('AT-SPI returnerte tom node')
        if node.getState().contains(pyatspi.STATE_DEFUNCT):
            raise RuntimeError('AT-SPI-node forsvant under skanning')
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
            raise RuntimeError('AT-SPI-applikasjon mangler')
        if 'firefox' not in (app.name or '').casefold():
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
                raise RuntimeError('Firefox-frame uten lesbare page tabs: ' + title)
            frames.append({'title': title, 'audio': bool(sounding)})
        if not found:
            raise RuntimeError('Firefox funnet, men ingen tilgjengelige frames')
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
        log('Mangler Python-avhengighet: ' + str(error))
        log('Trenger dbus-python, PyGObject/GLib, evdev og pyatspi i vertens Python.')
        return 2

    DBusGMainLoop(set_as_default=True)
    target_output = getattr(args, 'target', TARGET)
    timer = Timer(time.monotonic(), timeout=getattr(args, 'timeout_seconds', DEFAULT_TIMEOUT))
    kde_settings = KdeTimeout() if args.kde_timeout else None
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
    worker_started = next_scan = 0.0
    frames = []
    scan_stamp = None
    scan_error = 'venter på første AT-SPI-skanning'
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
        'fail_safe_reason': 'monitor poll has not completed',
        'playback_active': False,
        'scan_status': scan_error,
    }
    config_path = (Path(args.config).expanduser()
                   if getattr(args, 'config', None) else default_config_path())
    runtime_config = validate_config({
        'schema_version': 1,
        'target_output': target_output,
        'timeout_seconds': getattr(args, 'timeout_seconds', int(DEFAULT_TIMEOUT)),
        'mapping_ttl_seconds': getattr(args, 'mapping_ttl', 15.0),
        'devices': getattr(args, 'device', None) or DEFAULT_CONFIG['devices'],
        'mute_labels': getattr(args, 'mute_label', None) or DEFAULT_CONFIG['mute_labels'],
        'cec_enabled': bool(args.cec),
        'cec_port': args.cec_port,
        'kde_timeout': bool(args.kde_timeout),
        'require_snapshot': bool(args.require_snapshot or args.cec),
        'axis_deadzone_percent': args.axis_deadzone_percent,
        'rz_deadzone_percent': args.rz_deadzone_percent,
    })

    def activity(source):
        now = time.monotonic()
        message = timer.activity(now)
        if power:
            power.activity(wake_requested=bool(message))
        elif message:
            log(message)

    class Receiver(dbus.service.Object):
        @dbus.service.method('net.local.CecActivity', in_signature='s', out_signature='')
        def Report(self, message):
            nonlocal focus
            message = str(message)
            if message.startswith('Fokus: '):
                new_focus = message[len('Fokus: '):].strip()
                if new_focus != focus:
                    focus = new_focus
                    # No comparison across focus boundaries.
                    for state in devices.values():
                        for axis in state['axes'].values():
                            axis.reset()
            elif message == 'TV-aktivitet: mus':
                activity('mus (TV-melding fra KWin)')
            elif message.startswith("Desktop-snapshot: "):
                first = mapping.snapshot_stamp is None
                try:
                    payload = firefox_window_snapshot(message[len("Desktop-snapshot: "):])
                except (ValueError, TypeError, OSError) as error:
                    mapping.snapshot_error = "Vindusprosesser kunne ikke verifiseres: " + str(error)
                else:
                    if mapping.snapshot(payload, time.monotonic()) and first:
                        log("Firefox-livebro tilkoblet; prosessidentitet verifisert")
            elif message.startswith('Firefox-snapshot: '):
                first = mapping.snapshot_stamp is None
                if mapping.snapshot(message[len('Firefox-snapshot: '):], time.monotonic()):
                    if first:
                        log('Firefox-livebro tilkoblet; komplette vindusrapporter mottas')
            elif message.startswith('Firefox-media-snapshot: '):
                if not webextension_media.update(
                        message[len('Firefox-media-snapshot: '):], time.monotonic()):
                    log('Ugyldig Firefox WebExtension-snapshot; bruker AT-SPI-fallback')
            elif message.startswith('Firefox-vindu: '):
                payload = message[len('Firefox-vindu: '):]
                if ' | ' in payload:
                    output, title = payload.split(' | ', 1)
                    if title:
                        mapping.report(output.strip(), title, time.monotonic())

        @dbus.service.method('net.local.CecActivity', in_signature='', out_signature='s')
        def GetStatus(self):
            return json.dumps(status_snapshot, sort_keys=True)

        @dbus.service.method('net.local.CecActivity', in_signature='', out_signature='s')
        def GetConfig(self):
            if config_path.exists():
                try:
                    config = load_config(config_path)
                except ValueError as error:
                    raise dbus.DBusException(str(error))
            else:
                config = runtime_config
            return json.dumps({'schema_version': 1, **config}, sort_keys=True)

        @dbus.service.method('net.local.CecActivity', in_signature='s', out_signature='s')
        def ApplySettings(self, serialized_config):
            try:
                config = validate_config(json.loads(str(serialized_config)))
                if config.get('cec_enabled'):
                    config['require_snapshot'] = True
                saved = save_config(
                    config_path, {'schema_version': 1, **config})
            except (ValueError, TypeError, OSError) as error:
                raise dbus.DBusException('Could not save settings: ' + str(error))
            try:
                result = subprocess.run(
                    ['/usr/bin/systemctl', '--user', 'restart', '--no-block',
                     'topcec.service'],
                    capture_output=True, text=True, timeout=10)
                if result.returncode:
                    raise RuntimeError(result.stderr.strip() or result.stdout.strip())
            except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
                raise dbus.DBusException(
                    'Settings were saved, but the service restart could not be '
                    'queued: ' + str(error))
            return json.dumps({
                'accepted': True,
                'config': saved,
            }, sort_keys=True)

        @dbus.service.method('net.local.CecActivity', in_signature='s', out_signature='s')
        def RequestPower(self, action):
            try:
                request_manual_power(power, str(action),
                                     status_snapshot.get('fail_safe_reason'))
            except (RuntimeError, ValueError) as error:
                raise dbus.DBusException(str(error))
            return json.dumps({'accepted': True, 'action': str(action)})

    bus = dbus.SessionBus()
    try:
        name = dbus.service.BusName('net.local.CecActivity', bus=bus,
                                   do_not_queue=True)
        receiver = Receiver(bus, '/net/local/CecActivity')
    except dbus.DBusException as error:
        log('Kan ikke eie D-Bus-navnet. Stopp gammel monitor først: ' + str(error))
        return 2

    if activity_provider_factory is None:
        activity_provider_factory = EvdevActivityProvider
    activity_provider: ActivityProviderContract = activity_provider_factory(
        ecodes, args.axis_deadzone_percent, args.rz_deadzone_percent)

    try:
        for path in dict.fromkeys(args.device or ['/dev/input/event10', '/dev/input/event14']):
            device = InputDevice(path)
            try:
                axes = activity_provider.seed(device)
                selector.register(device, selectors.EVENT_READ)
            except Exception:
                device.close()
                raise
            devices[device.fd] = {'device': device, 'axes': axes, 'dropped': False}
    except OSError as error:
        log('Kan ikke lese input; testen stoppes uten endringer: ' + str(error))
        for state in devices.values():
            state['device'].close()
        selector.close()
        return 2

    loop = GLib.MainLoop()
    runtime_failed = False

    def poll():
        nonlocal worker, worker_started, next_scan, frames, scan_stamp, runtime_failed
        nonlocal scan_error, previous_status, warning_reported, previous_playback
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
                                state['axes'] = seed(device)
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
                        frames = media_provider.decode_scan(output, errors, worker.returncode)
                        if errors.strip() and not warning_reported:
                            log('AT-SPI-advarsel, men skanningen returnerte lesbare '
                                'Firefox-frames. Advarsel vises bare én gang:')
                            log(errors.strip()[:800])
                            warning_reported = True
                        scan_stamp = now
                        scan_error = None
                    except Exception as error:
                        scan_error = str(error)
                    worker = None
                    next_scan = now + SCAN_INTERVAL
                elif now - worker_started >= SCAN_TIMEOUT:
                    worker.kill()
                    worker.communicate()
                    worker = None
                    scan_error = 'AT-SPI svarte ikke innen 5 sekunder'
                    next_scan = now + SCAN_INTERVAL
            if worker is None and now >= next_scan:
                command = [sys.executable, str(Path(__file__).resolve()), '--atspi-scan']
                for label in args.mute_label:
                    command += ['--mute-label', label]
                worker = subprocess.Popen(command, stdout=subprocess.PIPE,
                                          stderr=subprocess.PIPE, text=True)
                worker_started = now
            reason = None
            audible = False
            native_audio_state = webextension_media.audio_state(
                mapping, now, target_output, mapping.ttl)
            if native_audio_state is not None:
                audible, uncertain_audio = native_audio_state
                if uncertain_audio:
                    reason = (
                        'Firefox WebExtension reports audio, but its active window '
                        'cannot be uniquely matched to a KWin display')
            else:
                reason = scan_error
                if scan_stamp is None or now - scan_stamp > SCAN_MAX_AGE:
                    reason = reason or 'AT-SPI-resultat mangler eller er foreldet'
                if reason is None:
                    if mapping.health(now, required=True) is None:
                        for message in match_diagnostics.update(
                                frames, mapping, now, scan_stamp):
                            log(message)
                    audible, uncertain_audio = media_provider.audio_state(
                        frames, mapping, now, target_output)
                    if uncertain_audio:
                        reason = (
                            'Firefox audio is active, but window mapping is '
                            'unknown, ambiguous or stale')
                    recent_titles = {
                        title for (title, _), stamp in mapping.reports.items()
                        if now - stamp <= mapping.ttl}
                    scanned_titles = {frame['title'] for frame in frames}
                    if recent_titles - scanned_titles:
                        reason = 'KWin-vinduer mangler i AT-SPI; venter på samsvar'
                    if not frames and mapping.reports:
                        reason = 'KWin har meldt Firefox, men AT-SPI finner ingen frames'
            reason = reason or mapping.health(now, args.require_snapshot)
            if kde_settings:
                settings_error = kde_settings.poll(timer, now)
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
                    reason = reason or 'venter på CEC-status fra TV'
            if focus is None:
                reason = reason or 'venter på Fokus-melding fra KWin'
            if any(state['dropped'] for state in devices.values()):
                reason = reason or 'venter på input-resynkronisering'
            if audible:
                activity('Firefox: Mute tab i frame på ' + target_output)
            # Logging state is separate from activity and fail-safe decisions.
            # Unknown monitoring state must not be reported as playback stopping.
            if reason is None and audible != previous_playback:
                log('Firefox-avspilling på TV ' + ('startet' if audible else 'stoppet'))
                previous_playback = audible
            if reason != previous_status:
                log('FAIL-SAFE: ' + reason + '; AV sperret' if reason else
                    'FAIL-SAFE opphevet; overvåking gjenopprettet')
                previous_status = reason
            message = timer.tick(now, uncertain=bool(reason))
            if message:
                if power:
                    power.request('off')
                else:
                    log(message)
            state_machine = getattr(power, 'state_machine', None)
            state = getattr(state_machine, 'state', None)
            power_state = getattr(state, 'value', 'unknown')
            if not isinstance(power_state, str):
                power_state = 'unknown'
            status_snapshot.update({
                'service': 'running',
                'power_state': power_state,
                'pending_action': power.pending if power else None,
                'cec_fault': power.fault if power else None,
                'fail_safe_reason': reason,
                'playback_active': audible,
                'scan_status': scan_error,
            })
        except Exception as error:
            # An input disconnect or callback failure must never become silence.
            runtime_failed = True
            log('Testen stoppes fail-safe: ' + repr(error))
            loop.quit()
            return False
        return True

    log(('FAKTISK CEC — følger KDE (nettstrøm).' if kde_settings else
         'FAKTISK CEC — 60 sekunder.') if power else
        'SIMULERING — 60 sekunder. Ingen CEC sendes. Ctrl+C avslutter.')
    log('Forventer eksisterende KWin-bro. Mute tab må være eksponert av Firefox.')
    GLib.timeout_add(100, poll)
    try:
        loop.run()
    except KeyboardInterrupt:
        pass
    finally:
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
        if power:
            power.close()
        log('Monitor avsluttet.' if power else 'Test avsluttet. Ingen CEC sendt.')
    return 2 if runtime_failed else 0


def self_test():
    import unittest
    from types import SimpleNamespace

    class Checks(unittest.TestCase):
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
            self.assertIn('AV TV', timer.tick(60))
            self.assertIsNone(timer.tick(61))
            self.assertIn('PÅ TV', timer.activity(62))
            self.assertIsNone(timer.activity(63))

        def test_fail_safe(self):
            timer = Timer(0)
            self.assertIsNone(timer.tick(100, True))
            self.assertIsNone(timer.tick(159))
            self.assertIn('AV TV', timer.tick(160))
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

            quiet = Node('frame', 'PSLive — Mozilla Firefox', [
                Node('page tab', 'PSLive'),
                Node('document web', children=[Node('button', 'Mute tab')])])
            sounding = Node('frame', 'Advanced Preferences — Mozilla Firefox', [
                Node('page tab', 'Advanced Preferences'),
                Node('page tab', 'Background YouTube', [Node('button', 'Mute tab')])])
            indicator = Node('frame', 'Localized sharing indicator',
                             attributes=["id:webrtcIndicator", "tag:html"])
            app = Node('application', 'Firefox', [quiet, indicator, sounding])
            desktop = Node('desktop', children=[app])
            fake = SimpleNamespace(STATE_DEFUNCT=99,
                                   Registry=SimpleNamespace(getDesktop=lambda n: desktop))
            with patch.dict(sys.modules, {'pyatspi': fake}):
                result = scan_atspi(['Mute tab'])
                for attributes in ((), ["id:main-window", "tag:html"],
                                   ["id:webrtcIndicator", "tag:button"]):
                    indicator.attributes = attributes
                    with self.assertRaises(RuntimeError):
                        scan_atspi(['Mute tab'])
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

        def run_monitor_steps(self, steps, diagnostics_enabled=True, config_path=None):
            from unittest.mock import Mock, patch

            clock = SimpleNamespace(now=0)
            context = SimpleNamespace(receiver=None, poll=None)
            workers = []
            messages = []
            timer = Timer(0)
            mapping = Mapping(15)
            diagnostics = MatchDiagnostics()
            update = Mock(wraps=diagnostics.update) if diagnostics_enabled else Mock(return_value=[])
            power = Mock(fault=None, process=None, pending=None)

            class Object:
                def __init__(self, *args):
                    context.receiver = self

            def timeout_add(interval, callback):
                context.poll = callback

            def main_loop():
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
                    if scan is not None:
                        output, errors, returncode = scan
                        workers[-1].poll.return_value = returncode
                        workers[-1].returncode = returncode
                        workers[-1].communicate.return_value = (output, errors)
                    self.assertTrue(context.poll())

            def start_worker(*args, **kwargs):
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
            args = SimpleNamespace(kde_timeout=False, cec=True, cec_port='unused',
                                   mapping_ttl=15, require_snapshot=True, device=['unused'],
                                   mute_label=['Mute tab'], axis_deadzone_percent=2.0,
                                   rz_deadzone_percent=5.0,
                                   config=str(config_path) if config_path else None)
            with patch.dict(sys.modules, modules), \
                    patch.dict(globals(), {
                        'Timer': Mock(return_value=timer), 'CecPower': Mock(return_value=power),
                        'Mapping': Mock(return_value=mapping),
                        'MatchDiagnostics': Mock(return_value=diagnostics),
                        'log': messages.append}), \
                    patch.object(diagnostics, 'update', update), \
                    patch.object(time, 'monotonic', lambda: clock.now), \
                    patch.object(selectors, 'DefaultSelector', return_value=selector), \
                    patch.object(subprocess, 'run', return_value=SimpleNamespace(
                        returncode=0, stdout='', stderr='')) as command_run, \
                    patch.object(subprocess, 'Popen', side_effect=start_worker):
                self.assertEqual(run(args), 0)
            return SimpleNamespace(
                messages=[message for message in messages if message.startswith('MATCH-DIAG:')],
                all_messages=messages, diagnostics=diagnostics, update=update,
                timer=vars(timer), mapping=vars(mapping), power_calls=power.mock_calls,
                receiver=context.receiver, power=power, command_run=command_run,
                status=json.loads(context.receiver.GetStatus()))

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
            self.assertIn('avvik i 0.0 s', result.messages[0])
            self.assertIn('avvik i 30.0 s', result.messages[2])
            self.assertIn('samsvar gjenopprettet etter 33.0 s', result.messages[4])
            self.assertIsNone(result.diagnostics.started)
            self.assertIsNone(result.diagnostics.signature)
            self.assertTrue(any('KWin-vinduer mangler i AT-SPI' in message
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
                    self.assertIn('samsvar gjenopprettet', recovered.messages[-1])

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

        def test_dbus_config_api_validates_persists_and_requests_user_restart(self):
            import tempfile
            from pathlib import Path
            from unittest.mock import patch

            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'config.json'
                result = self.run_monitor_steps([(0, None, None)], config_path=path)
                initial = json.loads(result.receiver.GetConfig())
                self.assertEqual(initial['schema_version'], 1)
                self.assertTrue(initial['cec_enabled'])
                invalid = json.dumps({'schema_version': 2})
                with self.assertRaisesRegex(RuntimeError, 'Unsupported configuration'):
                    result.receiver.ApplySettings(invalid)
                result.command_run.assert_not_called()
                request = {
                    'schema_version': 1,
                    'target_output': 'DP-1',
                    'cec_enabled': True,
                    'require_snapshot': False,
                }
                with patch.object(subprocess, 'run', return_value=SimpleNamespace(
                        returncode=0, stdout='', stderr='')) as command_run:
                    response = json.loads(
                        result.receiver.ApplySettings(json.dumps(request)))
                saved = json.loads(path.read_text(encoding='utf-8'))
                self.assertTrue(response['accepted'])
                self.assertEqual(saved['target_output'], 'DP-1')
                self.assertTrue(saved['require_snapshot'])
                self.assertEqual(
                    json.loads(result.receiver.GetConfig())['target_output'], 'DP-1')
                command_run.assert_called_once_with(
                    ['/usr/bin/systemctl', '--user', 'restart', '--no-block',
                     'topcec.service'],
                    capture_output=True, text=True, timeout=10)

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
    parser.add_argument('--config', help='JSON-konfigurasjonsfil med versjonert skjema')
    parser.add_argument('--target', help='Skjermutgang som styrer TV-en')
    parser.add_argument('--timeout-seconds', type=int,
                        help='Inaktivitet før standby; nullkonfigurasjon deaktiverer')
    parser.add_argument('--rz-deadzone-percent', type=float, default=None,
                        help='Deadzone for ABS_RZ i prosent (standard: 5)')
    parser.add_argument('--axis-deadzone-percent', type=float, default=None,
                        help='Minste aksebevegelse i prosent av området (standard: 2)')
    parser.add_argument('--kde-timeout', action=argparse.BooleanOptionalAction, default=None,
                        help='Følg KDEs skjermtidsgrense for nettstrøm')
    parser.add_argument('--cec', action=argparse.BooleanOptionalAction, default=None,
                        help='Send faktisk CEC av/på')
    parser.add_argument('--cec-port')
    parser.add_argument('--device', action='append', help='Inputsti; kan gjentas')
    parser.add_argument('--mapping-ttl', type=float, default=None,
                        help='Sekunder før vindusrapport blir usikker (standard: 15)')
    parser.add_argument('--mute-label', action='append', default=None,
                        help='Eksakt AT-SPI-knappnavn (standard: Mute tab)')
    parser.add_argument('--require-snapshot', action=argparse.BooleanOptionalAction, default=None,
                        help='Sperr AV uten ferske rapporter fra Firefox-livebroen')
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
    args.mute_label = config['mute_labels']
    args.cec = config['cec_enabled']
    args.cec_port = config['cec_port']
    args.kde_timeout = config['kde_timeout']
    args.require_snapshot = config['require_snapshot']
    args.axis_deadzone_percent = config['axis_deadzone_percent']
    args.rz_deadzone_percent = config['rz_deadzone_percent']
    if args.cec:
        args.require_snapshot = True
    if not math.isfinite(args.rz_deadzone_percent) or not 0 < args.rz_deadzone_percent <= 25:
        parser.error('--rz-deadzone-percent må være større enn 0 og høyst 25')
    if not math.isfinite(args.axis_deadzone_percent) or not 0 < args.axis_deadzone_percent <= 25:
        parser.error('--axis-deadzone-percent må være større enn 0 og høyst 25')
    if not math.isfinite(args.mapping_ttl) or args.mapping_ttl <= 0:
        parser.error('--mapping-ttl må være positiv og endelig')
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
        log('Kunne ikke starte testen: ' + repr(error))
        return 2


if __name__ == '__main__':
    sys.exit(main())
