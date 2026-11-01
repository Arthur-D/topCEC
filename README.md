# topCEC

Intelligent per-display HDMI-CEC power management for Linux

Project-authored topCEC code is licensed under **GPL-3.0-or-later**; see
[`LICENSE`](LICENSE). Third-party dependencies and separately identified
external material retain their own licenses. This project license does not
relicense those components.

Baseline snapshot dated 2026-10-27 from magne-desktop. The imported source was
initially copied byte-for-byte; `SNAPSHOT.json` records those original hashes.
Focused development changes may alter the current files. This is not an installer
or a portable release.

## Included

- `cec-tv/`: installed monitor, startup script, CEC command helper, KDE settings
  reader, hardware-independent activity policy and CEC power-state machine, and
  structural interfaces for activity, media and CEC providers, and the
  `activity.js` / `firefox.js` KWin bridges loaded by `start.py`.
- `systemd/user/topcec.service`: current topCEC controller unit.
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
- The packaged user unit runs from `%h/.local/share/topcec/cec-tv/start.py`.
  Direct checkout operation remains possible; older legacy helpers use
  `/home/arthur/.local/bin/`. Machine device paths in the defaults are not
  credentials.
- Requires KDE Plasma/KWin 6 on Wayland, session D-Bus, qdbus, kreadconfig6,
  cec-client/libCEC, Python with dbus-python, PyGObject/GLib, evdev and pyatspi.
  External dependencies are not vendored or version-pinned.
- Uses Plasma AC/Display idle settings (default 600 seconds), not battery or
  locked-screen timeouts. A disabled timeout prevents automatic OFF.
- Firefox audio detection uses the WebExtension signal when it is installed and
  reports fresh data; otherwise it falls back to AT-SPI's English `Mute tab`
  label. Other browsers/apps are not covered. Ambiguous/stale window matching
  blocks OFF. Snapshot interval 2 seconds; mapping TTL 15 seconds.
- Axis deadzones: ABS_RZ 5%, other axes 2%. Missing input devices stop the monitor;
  systemd retries after 15 seconds. Failed ON can retry upon activity after 10 seconds.
- CEC operations are bounded by a 130-second monitor deadline. An unconfirmed OFF
  does not trigger an automatic ON; a wake requested during the operation remains
  queued and cancels the in-flight standby helper. The queued ON resolves uncertain
  TV state; a CEC fault blocks further OFF until a command is confirmed.
- Shutdown may attempt to wake the TV; forced termination/power loss cannot guarantee
  recovery. Legacy controllers must not run alongside the current controller.
- Runtime diagnostics can contain window titles. No runtime logs are included.
- Some original comments retain older test names or timing descriptions. The source
  is authoritative. Hardware operation and reboot/login startup were not retested.

## Firefox web apps and accessibility

KWin reports window PIDs. The monitor verifies the host Firefox executable
through /proc/<pid>/exe, including web apps with custom window classes.
Missing or invalid process information blocks automatic OFF until recovery.
Chromium is not supported.

### Firefox media detection

The optional Firefox extension uses `tabs.Tab.audible` together with
`mutedInfo.muted`; the monitor retains AT-SPI as a fallback if no fresh
extension snapshot is available. The extension sends only each Firefox
window's active tab title and per-tab audible/muted booleans to a local native
messaging host. It does not send URLs, page contents, or inactive tab titles.

Mozilla's WebExtensions `tabs.Tab.audible` property is a better candidate:
Mozilla documents it as whether a tab is producing sound, and `tabs.onUpdated`
reports changes to `audible`. `mutedInfo.muted` should be checked as well,
because an audible tab can be muted. See
[tabs.Tab](https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/API/tabs/Tab#audible)
and
[tabs.onUpdated](https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/API/tabs/onUpdated).

`Mapping.browser_window_output` correlates the extension's active title only
with a unique, fresh Firefox window caption reported by KWin, stripping only
known Firefox brand suffixes. It never uses focus or substring matching. If
audible playback cannot be uniquely associated with a display, standby remains
blocked. PipeWire stream state is not a replacement by itself: it identifies
application audio streams, not the producing tab or display.

Install the user-level native host registration with
`bash packaging/install-firefox-native-host.sh` (also run by
`install-user.sh`). Load the extension from
`~/.local/share/topcec/firefox-extension/manifest.json` temporarily through
Firefox's `about:debugging` during development. For normal Firefox releases,
the extension needs Mozilla signing; create a ZIP for signing with
`bash packaging/build-firefox-extension.sh` (output defaults to `dist/`).
Firefox Flatpak native messaging is not claimed as
supported: its sandbox may prevent launching the host executable outside its
filesystem, so use the WebExtension path only with a Firefox installation
whose native-messaging support is confirmed. AT-SPI remains the safe fallback.

Separate Flatpak profiles on this machine needed GNOME_ACCESSIBILITY=1,
passed with flatpak run --env=GNOME_ACCESSIBILITY=1 org.mozilla.firefox.
Personal desktop launchers are outside this repository. Fresh profiles must
complete the Firefox welcome dialog before tabs become accessible. A live test
of the same process confirmed zero tabs before and one tab after completion.

Only the WebRTC indicator with AT-SPI attributes id:webrtcIndicator and tag:html
is excluded. Other frames without readable tabs still fail the scan.
Socket warnings may remain while frames are readable; no sockets were deleted.

## Hardware-free verification

From the repository root, run:

```sh
python3 -B tests/run.py self-test
python3 -B tests/run.py cec-power
python3 -B tests/run.py cec-power-state
python3 -B tests/run.py activity-policy
python3 -B tests/run.py providers
python3 -B tests/run.py firefox-media
python3 -B tests/run.py configuration
python3 -B tests/run.py gui
python3 -B tests/run.py license
python3 -B tests/run.py test_cec_live.py
python3 -B tests/run.py test_kde_settings.py
python3 -B tests/run.py check_fixed.py
python3 -B tests/run.py check_cec.py
```

The KWin activity bridge also has hardware-free JavaScript regression tests,
executed with Qt's JavaScript engine (requires Python `PySide6` / QtQml):

```sh
python3 -B tests/test_activity_bridge.py
```

These cover screen boundaries, scaled/rearranged outputs, gaps and overlaps,
geometry changes, hotplug subscriptions, and TV-only mouse activity throttling.

Do not execute `start.py`, the power helpers or legacy scripts to verify this
snapshot: those are operational programs. See `VALIDATION.md` for actual results.

## Versioned configuration

The monitor accepts an optional JSON file with `--config PATH`. Its required
`schema_version` is currently `1`; omitted keys retain the defaults shown below.
Explicit command-line options override file values. Invalid versions, unknown
keys, malformed values, or unreadable files stop startup with an error.

```json
{
  "schema_version": 1,
  "target_output": "HDMI-A-2",
  "timeout_seconds": 60,
  "mapping_ttl_seconds": 15,
  "devices": ["/dev/input/event10", "/dev/input/event14"],
  "mute_labels": ["Mute tab"],
  "cec_enabled": false,
  "cec_port": "/dev/serial/by-id/usb-Pulse-Eight_CEC_Adapter_v12-if00",
  "kde_timeout": false,
  "require_snapshot": false,
  "axis_deadzone_percent": 2.0,
  "rz_deadzone_percent": 5.0
}
```

Set `timeout_seconds` to `null` to disable inactivity standby. CEC remains
disabled by default; enabling it retains the live Firefox snapshot requirement.
The installed live launcher can load the same file with
`cec-tv/start.py --config ~/.config/topcec/config.json`; it continues to force
live CEC and the fresh-snapshot safety requirement. If no `--config` is passed,
the launcher automatically loads `~/.config/topcec/config.json` when it exists
(or `$XDG_CONFIG_HOME/topcec/config.json`).

## Optional KDE GUI

Run `python3 -B cec-tv/topcec_gui.py` in the active Plasma session. It requires
PySide6 QtDBus/QtQml, Kirigami QML modules, and `systemctl --user`; the service
is needed for status and manual control but native settings can be edited before
its first start. The GUI is optional; the service remains independently
operable and owns all CEC commands. Its session D-Bus API publishes monitor
status and configuration through `GetStatus`/`GetConfig`, accepts serialized
`on`/`off` requests through `RequestPower`, and validates/saves settings and
queues a user-service restart through `ApplySettings` on
`net.local.CecActivity`. Manual standby is rejected while monitor safety checks
fail or a CEC recovery/standby operation is active.

The panel provides output and adapter selection, input-device and Firefox
mute-label settings, KDE-managed/custom/disabled inactivity timeouts, current
power and service status, diagnostics, and manual controls. The native GUI saves
the versioned config to the XDG default path and restarts the user service, so it
can configure the service before its first start. “Simulate manual actions”
previews GUI button requests only; it does not pause or simulate the independently
running background service.
The GUI's hardware-free settings, manual-control safety, and QML-load checks run
with `python3 -B tests/run.py gui`.

## User-level installation and packaging

Install the current checkout without root using:

```sh
bash packaging/install-user.sh
```

This copies runtime files to `~/.local/share/topcec`, installs the user unit
under `${XDG_CONFIG_HOME:-~/.config}/systemd/user`, and adds
`~/.local/bin/topcec-gui`. It reloads the user systemd manager but does not
enable or start the service. Add `~/.local/bin` to `PATH`, configure the input
devices and adapter with `topcec-gui`, then enable the service using the command
shown by the installer. To remove the installed program, run
`bash packaging/uninstall-user.sh`; it stops/disables topcec.service if needed
and leaves the user's configuration untouched. The installer/uninstaller have
staged filesystem tests: `python3 -B tests/test_packaging.py`.

An RPM spec and isolated builder are provided in `packaging/topcec.spec` and
`bash packaging/build-rpm.sh`. They package only GPL-3.0-or-later TopCEC source,
license/provenance documentation, and systemd/desktop integration; dependencies
are expressed as RPM requirements rather than bundled. Build with
`packaging/build-rpm.sh` on an RPM development host with `rpmbuild` installed;
the default output goes to `dist/` and can be changed with
`TOPCEC_RPM_OUTPUT_DIR`. The package does not enable or start the service; after
installation, reload the user manager and enable it explicitly with
`systemctl --user daemon-reload` and
`systemctl --user enable --now topcec.service`. The RPM spec and install scripts
are covered by `python3 -B tests/run.py packaging`. Third-party dependency
licenses remain separate; no third-party source is included in the RPM payload.

The optional Flatpak GUI is a client for the separately installed host service;
it does not bundle or access the monitor, CEC adapter, input devices, KWin, or
host configuration files. The client uses only the `net.local.CecActivity`
session-D-Bus name. The host service exposes `GetStatus`, `GetConfig`,
`RequestPower`, and `ApplySettings`; the host validates and atomically saves
configuration, then asks the user systemd manager to restart `topcec.service`.
The service must already be installed and running to view or change settings.
The manifest uses KDE's Python runtime and Qt/PySide BaseApp for PySide6. See
[KDE's Python Flatpak guidance](https://develop.kde.org/docs/getting-started/python/python-flatpak/).
Building requires `flatpak-builder` and the matching KDE Platform, KDE SDK, and
`io.qt.PySide.BaseApp` runtimes for branch 6.11. Build the client from the
repository root with:

```sh
flatpak-builder --force-clean build-dir \
  packaging/flatpak/net.local.topcec.yml
```

The manifest grants Wayland/X11 display access and the single topCEC session
bus name, but no host filesystem, device, systemd, or KWin access. The GUI also
avoids invoking host commands or enumerating host device paths; output and
adapter fields remain editable and are initialized from the host service
configuration. The host service and hardware dependencies must still be
installed outside Flatpak. The regular user-local/RPM GUI retains direct
configuration-file access so it can configure the service before first start;
the Flatpak launcher selects the D-Bus-only client mode.

Commit: `Initial snapshot of working CEC controller`  
Tag: `baseline-2026-10-27`
