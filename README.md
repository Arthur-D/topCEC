# topCEC

Intelligent per-display HDMI-CEC power management for Linux

Project-authored topCEC code is licensed under **GPL-3.0-or-later**; see
[`LICENSE`](LICENSE). Third-party dependencies and separately identified
external material retain their own licenses. This project license does not
relicense those components.

Baseline snapshot dated 2026-10-27 from a local KDE Plasma installation. The imported source was
initially copied byte-for-byte; `SNAPSHOT.json` records those original hashes.
Focused development changes may alter the current files. This is not an installer
or a portable release.

## Included

The original TV/power-symbol application icon is
[`cec-tv/net.local.topcec.svg`](cec-tv/net.local.topcec.svg), licensed
GPL-3.0-or-later. The Qt window, desktop launcher, user installer, RPM GUI package
and Flatpak share the `net.local.topcec` identity. Packages install the scalable
icon under `share/icons/hicolor/scalable/apps`; checkout GUI runs load the source
SVG directly when no installed icon is available.

- `cec-tv/`: installed monitor, startup script, CEC command helper, KDE settings
  reader, hardware-independent activity policy and CEC power-state machine, and
  structural interfaces for activity, media and CEC providers, and the
  `activity.js` / `firefox.js` KWin bridges loaded by `start.py`.
- `systemd/user/topcec.service`: current topCEC controller unit.
- `legacy/`: three older systemd units and their three shell helpers, retained
  as historical context. They are not enabled by this repository. The inspected
  enablement directories contain the current unit, not these older units.
- `tests/original/`: four historical hardware-free test scripts, with assertions
  preserved and personal import paths sanitized.
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
  The bridge reports activity with its actual output name; the monitor filters
  it using `target_output`, including non-default displays. No separate KWin
  target configuration is required. Legacy TV-only mouse reports are accepted
  only for the original default display.
- CEC adapter: `/dev/serial/by-id/usb-Pulse-Eight_CEC_Adapter_v12-if00`;
  commands address TV logical address 0. This is one TV, not a general multi-TV manager.
- Input defaults remain `/dev/input/event10` and `/dev/input/event14` for
  compatibility. Configure `devices` for your keyboard/wheel using stable
  `/dev/input/by-id/` paths; event numbers are not portable between systems.
- The packaged user unit runs from `%h/.local/share/topcec/cec-tv/start.py`.
  Direct checkout operation remains possible; older legacy helpers use
  `$HOME/.local/bin/`. The default CEC adapter path identifies a device model,
  not a unique serial; set `cec_port` for your adapter. No devices are auto-selected.
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
- TopCEC CLI messages, help, service diagnostics and GUI text are English.
  External command errors, system/Qt dialogs and user-supplied window titles may
  still follow the desktop locale. Firefox AT-SPI mute-tab labels must match
  Firefox's language; translating the interface does not change detection labels.
  Existing D-Bus focus tokens and diagnostic JSON keys are retained for compatibility.
- Some original comments retain older test names or timing descriptions. The source
  is authoritative. Hardware operation and reboot/login startup were not retested.

Build output under `repo/`, `repo-local/`, `dist/`, `builddir/`, `build-dir/`
and `.flatpak-builder/`, plus the obsolete temporary `topcec-local.yml`, is
ignored and is not part of the source payload. Use only `net.local.topcec.yml`
for Flatpak builds. Ignore rules do not remove files already committed in another
checkout or redact earlier history. The owner-provided origin statement and its verification limits are documented
in `PROVENANCE.md`.

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
python3 -B tests/run.py equipment
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
status and configuration through `GetStatus`/`GetConfig`, cached read-only
equipment choices through `GetEquipment`, accepts serialized
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

GUI headings, explanations, status, diagnostics, commands and text fields support
selection and copying with Ctrl+C. Right-click a button caption, checkbox,
selector or numeric value and choose **Copy text** without activating it (the
keyboard Menu key opens the same action). **Copy page text** copies the current
page, including disabled control captions and the window title; it excludes
the hidden setup/configuration page.

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
The Flatpak contains only the GUI: the host service and its hardware dependencies
must be installed separately, outside the sandbox. The setup view in the GUI
provides these same steps and a retry action:

1. In a terminal, clone the official repository and enter its root directory:

   ```sh
   git clone https://github.com/Arthur-D/topCEC.git
   cd topCEC
   ```

2. From the repository root, install the host files and user service. Calling
   the script through `bash` works even when the interactive shell is fish:

   ```sh
   bash packaging/install-user.sh
   ```

3. Configure the correct KWin display, CEC adapter, and input devices with the
   native host GUI installed by the script:

   ```sh
   ~/.local/bin/topcec-gui
   ```

4. Enable and start the host service:

   ```sh
   systemctl --user enable --now topcec.service
   ```

5. Return to the Flatpak GUI. It reconnects when the D-Bus service appears, with
   a low-frequency retry as a fallback; use **Retry Connection** to retry
   immediately.

The installer installs the unit but does not enable or start it. The native GUI
continues to work independently of Flatpak and can save the host configuration
before the service is first started.

If an input device is missing or unreadable when the service starts, the host
stays available in **configuration-only** mode instead of exiting. The Flatpak
then shows the normal configuration panel and the input error. Choose the
correct keyboard/wheel paths (prefer stable `/dev/input/by-id/` paths), then use
**Save settings and restart service** to retry monitoring. No CEC commands or
monitoring run in this mode, and both live manual power actions are rejected.
Unsaved GUI edits are retained across connection loss and reconnection.

### Configured values and detected equipment

The configured display, adapter and input paths are saved settings (or legacy
defaults when no settings have been saved), **not evidence of detected hardware**.
The host backend supplies the actual configuration selectors with detected
equipment, including in configuration-only mode. Choose your display and CEC
adapter from those selectors, and check the input devices to monitor. Unplugged
choices disappear unless currently selected; selected saved/default or unsaved
values remain explicitly labelled **unavailable / not detected**, never shown as
available hardware. Uncheck an unwanted input to remove it. Manual output names
and adapter paths can still be entered; **Edit input paths manually** exposes
the input-path editor for unusual devices or an older backend. Native offline
configuration retains that editor. Nothing is selected or saved automatically.

Discovery runs outside Flatpak in a bounded background helper approximately every
10 seconds after the previous scan completes (each scan has an 8-second limit).
The already-open GUI reads the cached inventory with its existing 5-second
status refresh, so plug/unplug/replug updates require no application restart.
There are no extra signal subscriptions or invasive probes; this is bounded
refresh rather than instantaneous udev/compositor notification. Manual selections
and drafts are preserved across those updates. It reads connected output names
from `kscreen-doctor -o`, CEC-named
paths in `/dev/serial/by-id`, and input-device paths/names from `/dev/input` and
sysfs. Input paths prefer `/dev/input/by-id` aliases, then `/dev/input/by-path`
when available, before falling back to event paths. It does not
open input/serial devices, probe libCEC or send CEC commands. Disabled but
connected displays are labelled; disconnected displays are excluded. This cannot
identify which connected screen is your TV, discover every CEC adapter type, or
guarantee that a listed device is readable by the service. Missing metadata and
discovery errors are shown separately; configured values absent from the latest
inventory remain editable rather than being silently replaced.

Both host backend and GUI need this update. An older backend without
`GetEquipment` leaves manual configuration working and displays an update
message instead of presenting defaults as detected choices. Update the host
using the checkout/install/restart commands below; updating Flatpak alone is
insufficient. No additional Flatpak permissions are needed.

### Input-device access

The host user must have read access to the selected input devices. Changing a
path does not grant access; if the intended device is still permission-denied,
the GUI shows **Input device access** guidance supplied by the host. When the
host verifies that the device is group-readable by the existing `input` group
and your account is not a member, it offers **Copy input-group command**.
Paste the displayed `sudo usermod -aG input -- YOUR_USERNAME` command into a
host terminal and run it yourself; `YOUR_USERNAME` is replaced with the backend
account name in the GUI. This command works with fish as well as Bash. It needs
administrator authorization and is never executed by the GUI.

On Atomic desktops such as Bazzite, `input` may exist only in `/usr/lib/group`.
In that case `usermod` alone does not persist membership, even after reboot.
The host detects this layout and offers a `sudo sh -c ...` command that first
copies the vendor `input` entry to `/etc/group` if missing, then runs `usermod`.
The check is repeated when the command runs, so rerunning it does not append
a duplicate group. Run it in a host terminal, outside Toolbox/Distrobox.

Membership in `input` grants access to keyboard and other input events, not just
the selected device. Consider scoped device permissions with your administrator
instead if that broad access is inappropriate. Fully log out and back in so the
desktop and user service inherit the new group. If the user manager persists
across logout (for example with lingering), reboot. Then use **Retry Connection**
and **Save settings and restart service** to retry monitoring. If your account is
already a member but the running backend has not inherited it, the GUI explains
the session restart instead of offering a duplicate membership command. If the
backend already has that group, or the device ownership/read bits do not support
this remedy, check the selected device, ACLs and host security policy instead;
the GUI does not claim that every permission error is a missing group.

Do not grant device access to Flatpak or run the GUI as root. The installer
copies files but does not configure device permissions or install host
dependencies. This recovery requires the updated host backend as well as the
updated GUI; a backend predating configuration-only recovery still exits on
input initialization failure. If configuration-only mode is available but the
permission guidance is missing, the installed host backend may predate that
guidance even when the Flatpak is current. Update the host separately from an
existing checkout of the official repository:

```sh
cd /path/to/topCEC
git pull --ff-only
bash packaging/install-user.sh
systemctl --user restart topcec.service
```

Replace `/path/to/topCEC` with your actual checkout path. The installer preserves
configuration and group membership; restarting loads the updated host code.
Return to the GUI and use **Retry Connection**. Updating or rebuilding only the
Flatpak does not update the files used by `topcec.service`. Clients without
detailed host permission diagnostics provide generic input-access guidance
instead of recommending an unverified group change.

For connection problems on the host, inspect the user unit and its current-boot
logs, then verify that its D-Bus name is owned:

```sh
systemctl --user status topcec.service
journalctl --user -u topcec.service -b
busctl --user list | grep -F net.local.CecActivity
```

The Flatpak is granted only the `net.local.CecActivity` session-bus name. Its
sandbox cannot inspect host systemd units or files, so an unavailable name is
reported as generic and the GUI does not claim that the service is uninstalled.
The native GUI can distinguish a definitely missing unit or an installed but
stopped unit when the user systemd manager reports that state; D-Bus failures
and other uncertain states remain connection errors/unavailable rather than
being misreported as an installation problem. Neither client adds host
filesystem/device access, broad D-Bus permissions, or a host-command bridge.
The root-level manifest uses KDE Platform/SDK 6.11 and builds the required
PySide6 modules from checksum-pinned upstream source against that SDK.
PySide uses Qt's private ABI: the previous PySide BaseApp 6.11.2 failed to
import against KDE's Qt 6.11.3 despite sharing the same branch. Building the
bindings against the SDK avoids relying on a stale binary BaseApp. An import
check for QtCore, QtDBus, QtGui, QtQml, and QtQuick runs during the build.
When updating the KDE branch or Qt patch version, review the pinned PySide
source and LLVM SDK extension as well; the import check must still pass.
Upstream PySide/Shiboken license texts are installed under
`/app/share/licenses/pyside`; other third-party notices remain in their packages.
The source URL and checksum are recorded in `packaging/flatpak/pyside.yml`.

Build from the repository root with the Flatpak-packaged builder (this builds
and exports the app without installing it):

```sh
flatpak run --command=flathub-build org.flatpak.Builder net.local.topcec.yml
flatpak build-bundle repo dist/net.local.topcec.flatpak net.local.topcec
```

The root-level source path works directly with `flathub-build`; no temporary
manifest or `sed` workaround is needed. The first build also downloads the
KDE SDK/runtime and LLVM 22 SDK extension, and compiles the required bindings.
If using a native builder instead, run
`flatpak-builder --user --install-deps-from=flathub --force-clean --repo=repo builddir net.local.topcec.yml`.
Add `--install` to the builder command only if you want to replace/install the
user's GUI app. This does not install or restart the separate host service.
After installing the GUI, verify the actual runtime import with:

```sh
flatpak run --command=python3 net.local.topcec -c \
  'from PySide6 import QtCore, QtDBus, QtGui, QtQml, QtQuick; print(QtCore.qVersion())'
flatpak run net.local.topcec
```

The manifest grants Wayland/X11 display access and the single topCEC session
bus name, but no host filesystem, device, systemd, or KWin access. The GUI also
avoids invoking host commands or enumerating host device paths; output and
adapter fields remain editable and are initialized from the host service
configuration. The host service and hardware dependencies must still be
installed outside Flatpak. The regular user-local/RPM GUI retains direct
configuration-file access so it can configure the service before first start;
the Flatpak launcher selects the D-Bus-only client mode.

The original baseline is recorded in `SNAPSHOT.json`. Its historical commit and
tag were superseded by the privacy history cleanup.
