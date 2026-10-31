# TopCEC

Intelligent per-display HDMI-CEC power management for Linux

Baseline snapshot dated 2026-10-27 from magne-desktop. The imported source was
initially copied byte-for-byte; `SNAPSHOT.json` records those original hashes.
Focused development changes may alter the current files. This is not an installer
or a portable release.

## Included

- `cec-tv/`: installed monitor, startup script, CEC command helper, KDE settings
  reader, and the `activity.js` / `firefox.js` KWin bridges loaded by `start.py`.
- `systemd/user/cec-activity.service`: current controller unit.
- `legacy/`: three older systemd units and their three shell helpers, retained
  as historical context. They are not enabled by this repository. The inspected
  enablement directories contain the current unit, not these older units.
- `tests/original/`: four existing hardware-free test scripts, unchanged.
- `tests/run.py`: hardware-free runner redirects historical test paths in memory
  to this copy, adapts legacy wake scenarios, blocks real child processes, device
  access and connections, and runs direct mocked tests of the current CEC coordinator.
- `SNAPSHOT.json`: original source paths and SHA-256 hashes for all 17 baseline files.
- `PROVENANCE.md` and `VALIDATION.md`: origin/licensing and verification details.

Local backups, logs, journals, caches, compiled Python files, unrelated desktop
configuration, external research repositories and credentials are excluded.

## Machine-specific values and limitations

- Target display is `HDMI-A-2`. The mouse bridge maps cursor position using KWin's
  current output geometries; gaps and overlapping geometry are treated as unknown.
- CEC adapter: `/dev/serial/by-id/usb-Pulse-Eight_CEC_Adapter_v12-if00`;
  commands address TV logical address 0. This is one TV, not a general multi-TV manager.
- Startup input paths: `/dev/input/by-id/usb-Logitech_G29_Driving_Force_Racing_Wheel-event-joystick`
  and `/dev/input/by-id/usb-Glorious_GMBK_75__ISO_SL125211940100411-event-kbd`.
  Direct monitor defaults instead use `/dev/input/event10` and `/dev/input/event14`.
- Installation path is `/home/arthur/.local/share/cec-tv/`; older helpers use
  `/home/arthur/.local/bin/`. Device identifier and local paths are intentionally
  retained to preserve the exact baseline; they are not credentials.
- Requires KDE Plasma/KWin 6 on Wayland, session D-Bus, qdbus, kreadconfig6,
  cec-client/libCEC, Python with dbus-python, PyGObject/GLib, evdev and pyatspi.
  External dependencies are not vendored or version-pinned.
- Uses Plasma AC/Display idle settings (default 600 seconds), not battery or
  locked-screen timeouts. A disabled timeout prevents automatic OFF.
- Firefox audio detection depends on AT-SPI, exact window-title matching and the
  English `Mute tab` label. Other browsers/apps are not covered. Ambiguity or
  stale data blocks OFF. Snapshot interval 2 seconds; mapping TTL 15 seconds.
- Axis deadzones: ABS_RZ 5%, other axes 2%. Missing input devices stop the monitor;
  systemd retries after 15 seconds. Failed ON can retry upon activity after 10 seconds.
- CEC operations are bounded by a 130-second monitor deadline. An unconfirmed OFF
  does not trigger an automatic ON; a wake requested during the operation remains
  queued, and later activity can request ON while the CEC fault blocks further OFF.
- Shutdown may attempt to wake the TV; forced termination/power loss cannot guarantee
  recovery. Legacy controllers must not run alongside the current controller.
- Runtime diagnostics can contain window titles. No runtime logs are included.
- Some original comments retain older test names or timing descriptions. The source
  is authoritative. Hardware operation and reboot/login startup were not retested.

## Hardware-free verification

From the repository root, run:

```sh
python3 -B tests/run.py self-test
python3 -B tests/run.py cec-power
python3 -B tests/run.py test_cec_live.py
python3 -B tests/run.py test_kde_settings.py
python3 -B tests/run.py check_fixed.py
python3 -B tests/run.py check_cec.py
```

Do not execute `start.py`, the power helpers or legacy scripts to verify this
snapshot: those are operational programs. See `VALIDATION.md` for actual results.

Commit: `Initial snapshot of working CEC controller`  
Tag: `baseline-2026-10-27`
