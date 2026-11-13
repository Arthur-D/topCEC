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

- The target display, CEC adapter, and input devices have no hardware-specific
  defaults. Select detected hardware in the settings UI or configure its paths
  explicitly. The mouse bridge maps cursor position using KWin's current output
  geometries; gaps and overlapping geometry are treated as unknown. The bridge
  reports activity with its actual output name; the monitor filters it using the
  configured `mouse_outputs` list. No separate KWin target configuration is required.
  This is one TV, not a general multi-TV manager.
- The packaged user unit runs from `%h/.local/share/topcec/cec-tv/start.py`.
  Direct checkout operation remains possible; older legacy helpers use
  `$HOME/.local/bin/`. A sole detected display or adapter may be selected
  automatically; otherwise choose the intended hardware explicitly.
- Requires KDE Plasma/KWin 6 on Wayland, session D-Bus, qdbus, kreadconfig6,
  cec-client/libCEC, Python with dbus-python, PyGObject/GLib, evdev and pyatspi.
  External dependencies are not vendored or version-pinned.
- Follows Plasma's AC/Display idle setting (default 600 seconds), not battery
  or locked-screen timeouts. If that setting cannot be read, it uses the
  configured fallback (5 minutes by default). An explicitly disabled Plasma
  timeout still prevents automatic OFF.
- Firefox audio detection uses the WebExtension signal when it is installed and
  reports fresh data; otherwise it falls back to AT-SPI's English `Mute tab`
  label. The Firefox row's “Block standby while playing audio” option
  controls this detection; it uses the displays selected for mouse activity.
  Other apps' media types cannot currently be detected. Ambiguous/stale window
  matching blocks OFF.
  The Standby page reports when Firefox audio detection is unavailable instead
  of treating it as inactive. Snapshot interval 2 seconds; mapping TTL 15 seconds.
  Monitoring warnings appear on Diagnostics; standby remains blocked when
  Firefox audio status is uncertain. AT-SPI updates are event-driven, with no
  documented fixed update interval
  ([AT-SPI cache protocol](https://gnome.pages.gitlab.gnome.org/at-spi2-core/devel-docs/doc-org.a11y.atspi.Cache.html)).
  The AT-SPI fallback identifies Firefox by its process executable before
  querying application accessibility data, avoiding unrelated unresponsive apps.
- “Allow standby” is on by default. Turn it off to let an app's Plasma
  idle-inhibition requests block topCEC standby independently of its media
  settings. Sleep-only inhibitions are ignored; matching requests and their
  reasons appear under “Currently blocking standby”. This setting affects
  topCEC, not Plasma's power policy. Unknown app identity or display, stale
  Plasma status, and failed installed-app discovery block standby when an app
  is selected to block. Existing selections remain unchanged, including for
  uninstalled apps. The default list shows Firefox, current and previously observed
  idle-inhibiting apps, and selected apps. Its search filters to apps currently
  requesting screen inhibition; “Show all installed apps” searches all apps.
  Observed app names are stored in `observed-inhibitors.json` beside the host
  configuration.
- Each app also has a “Force block standby” option: an open window on a selected mouse
  display blocks TV standby even without an app inhibition request. A window on
  an unknown display, or a stale window snapshot, blocks conservatively. This
  matches KWin's desktop-file or window-class identity, including a desktop
  entry's `StartupWMClass`. An unidentified window blocks conservatively.
  Background processes without windows do not count. It does not inhibit Plasma
  idle or system sleep.
- Axis deadzones: 0% by default. Missing input devices stop the monitor;
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
python3 -B tests/run.py standby-apps
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
  "target_output": "",
  "timeout_seconds": 300,
  "mapping_ttl_seconds": 15,
  "devices": [],
  "consider_input_devices": true,
  "mouse_output": null,
  "mouse_outputs": null,
  "mute_labels": ["Mute tab"],
  "cec_enabled": false,
  "cec_port": "",
  "kde_timeout": true,
  "require_snapshot": false,
  "axis_deadzone_percent": 0.0,
  "rz_deadzone_percent": 0.0,
  "device_axis_deadzones": {}
}
```

`timeout_seconds` is the fallback inactivity timeout when following Plasma, and
the default is 300 seconds (5 minutes). Set it to `null` to disable standby if
the Plasma setting cannot be read. Set `kde_timeout` to `false` to use this
timeout directly. An explicitly disabled Plasma timeout also disables automatic
standby. CEC remains disabled by default; enabling it requires explicit display
and adapter selections and retains the live Firefox snapshot requirement.
Display, adapter, and input paths are left unselected by default; choose
hardware detected on the host or set the paths explicitly.
Set `consider_input_devices` to `false` to ignore the selected input devices
without removing their paths. `mouse_outputs` lists displays whose mouse movement
or selected app activity prevents standby; an empty list selects none. A `null`
value preserves the legacy `mouse_output` setting, which follows `target_output`
when also null. Mouse movement is independent of the input-device setting.
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
applies them live through `ApplySettings` on
`net.local.CecActivity`. Manual standby is rejected while monitor safety checks
fail or a CEC recovery/standby operation is active.

The native Qt Quick/Kirigami panel follows the current Plasma theme. Its
**Overview** shows TV power, service state, recovery notices, and equipment and
standby summaries. The navigation sidebar opens **Display**, **Standby**,
**Input**, and **Diagnostics**; on narrow windows it becomes a navigation
drawer. **Input** keeps device choices visible, with disclosures for manual
paths and controller deadzones. **Standby** contains the input-device toggle
and mouse-movement display selector, and **Overview** contains manual
power-action simulation. The **Save and apply**
footer appears when there are edits to apply or configuration needs attention.
Switching sections preserves unsaved settings and input selections.

The panel provides output and adapter selection, input-device settings,
KDE-managed/custom/disabled inactivity timeouts, diagnostics, and manual power
controls. The native GUI saves
through the host service when connected. When offline it saves the versioned
config to the XDG default path for the next service start, without starting or
restarting systemd. “Simulate manual actions”
previews GUI button requests only; it does not pause or simulate the independently
running background service.
The GUI's hardware-free settings, manual-control safety, and QML-load checks run
with `python3 -B tests/run.py gui`.

GUI headings, explanations, status, diagnostics, commands and text fields support
selection and copying with Ctrl+C. Right-click a button caption, checkbox,
selector or numeric value and choose **Copy text** without activating it (the
keyboard Menu key opens the same action). **Copy page text** copies the current
page, including visible disabled control captions and the window title.
**Copy diagnostics** includes the device inventory and host status even when
their disclosures are closed.

### Qt AT-SPI diagnostic

Some accessibility clients produce this console warning:

```text
qt.accessibility.atspi: AtSpiAdaptor::applicationInterface does not implement "GetApplicationBusAddress" "/org/a11y/atspi/accessible/root"
```

This is an upstream **Qt AT-SPI bridge protocol gap**, not a topCEC method to
implement in QML and not the monitor's Firefox/AT-SPI frame warning.
Qt's [6.11.2](https://github.com/qt/qtbase/blob/v6.11.2/src/gui/accessible/linux/atspiadaptor.cpp)
and [6.11.3](https://github.com/qt/qtbase/blob/v6.11.3/src/gui/accessible/linux/atspiadaptor.cpp)
application-interface handler lack that method and emit this exact diagnostic.
The [AT-SPI application specification](https://github.com/GNOME/at-spi2-core/blob/main/xml/Application.xml)
uses the method to negotiate a direct peer-to-peer D-Bus address.
[libatspi 2.62.0](https://github.com/GNOME/at-spi2-core/blob/2.62.0/atspi/atspi-misc.c)
starts with its existing accessibility-bus connection and retains it when
negotiation returns an error or empty address. Thus this warning alone does not
establish that the accessibility tree or screen-reader navigation is broken.
Repeated clients/reconnections can repeat the diagnostic.

Do not disable accessibility or suppress the accessibility log category to
resolve it. Keep native Qt packages and the KDE Flatpak runtime current, and
report the diagnostic to their Qt/runtime maintainers with the Qt version,
AT-SPI version and whether it occurs in a minimal Qt application. A runtime
containing an upstream bridge correction is the proper resolution; merely
rebuilding PySide or adding accessible labels cannot implement this private Qt
method. No fixed release is asserted here, and updating from 6.11.2 to 6.11.3
alone does not fix the missing handler. The Flatpak uses runtime Qt while native
topCEC uses host Qt, so a correction must reach the applicable runtime.

topCEC leaves accessibility and its diagnostics enabled. Automated checks cover
basic QML accessible roles/names and keyboard focus, not a complete screen-reader
audit. Test real screen-reader reading order, status announcements, focus during
reconnection/hotplug and all settings with your assistive technology before
claiming full accessibility. No additional Flatpak D-Bus/device permissions are
needed to address this upstream warning.

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
configuration and applies it to the same running process; no systemd restart is
requested for settings changes.
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
**Save and apply** to resume monitoring in the same process. If the saved
settings already point to the correct devices, use **Retry monitoring** in
**Diagnostics** to reapply them. No new
standby commands or input monitoring run in this mode, and both live
manual power actions are rejected.
Unsaved GUI edits are retained across connection loss and reconnection.

### Configured values and detected equipment

Input checkbox changes save and apply live automatically. Rapid
changes are queued behind any in-flight apply. Pending selections are retained
locally across closing and reopening the GUI. Deselecting every input saves an
empty list. Failed selections remain pending with an explicit error; they are not
retried every half-second. Change the selection or use **Save and apply settings**
to retry after correcting host permissions. Other fields still use the Save button.

The configured display, adapter and input paths are saved settings (or legacy
defaults when no settings have been saved), **not evidence of detected hardware**.
The host backend supplies the actual configuration selectors with detected
equipment, including in configuration-only mode. Choose your display and CEC
adapter from those selectors, and check the detected input devices to monitor.
Undetected saved/default hardware and drafts are **not preselected** in those
controls: display/adapter selectors show **Choose a detected…**, and absent
inputs have no checked device row. Retained values appear separately in notices
as **unavailable / not detected**, or **availability unknown** if discovery failed.
They are not erased or saved automatically, and the first detected device is
never selected as a substitute.

**Save and apply settings** can retain unchanged display/adapter settings even if
that hardware is unavailable. Changed selections must be resolved. Choose detected
hardware and use **Remove unlisted input values** to explicitly discard retained
inputs, or deliberately enable the
manual display/adapter/input options to inspect, edit and keep undetected values.
The same deliberate manual path supports native offline configuration and older
backends. A hot-unplug clears the detected selection/checkmark and blocks Save
without losing intent; replugging the same device restores that intent, never
substituting another device. Changing unrelated settings cannot silently reapply
hidden defaults or clear untouched equipment configuration.

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

`UnknownMethod` for `GetEquipment` means the backend currently owning the D-Bus
name lacks that API. It does **not** establish that any hardware is absent.
The GUI reports **availability unknown** until discovery completes successfully;
failed/incomplete discovery also leaves undetected values unknown. A
successful inventory can instead mark a retained absent value **unavailable / not
detected** in its notice, not as selected hardware. In either case configured
paths and unsaved edits remain intact.
The GUI detects compatibility by missing D-Bus capabilities, not matching cosmetic
version numbers. An `UnknownMethod` response to `GetStatus`, `GetConfig`,
`GetEquipment`, `ApplySettings` or `RequestPower` identifies an unsupported
capability when it is used. Transport timeouts, denied access and invalid replies
are errors, not proof of an old version. No speculative power/settings calls
are made to test capabilities.

The compatibility message includes **Copy host update command**, visible even
when missing status/configuration capabilities require the setup view. Open a
host terminal **from any directory** and paste it. The command asks for the full
absolute path to your existing official repository checkout's root on `main`.
Paste that path without shell quotes, even when it contains spaces; use the full
path rather than `~`. No location is assumed or searched, and no new checkout is
created if the original was moved or deleted. Supply its current path instead.
This single fish-compatible command invokes Bash explicitly, changes into the
quoted path, checks the repository root, `main` branch and official GitHub origin, pulls
`origin main` with `--ff-only`, installs, then restarts the backend. It stops on
any failed check, update or installation, so stale code is not restarted after a
failed update. It does not infer a source checkout from the installed backend
directory, record or assume a private checkout location, download/run an installer
automatically, or execute through Flatpak. Cancelling the prompt, an empty or
relative path, a missing directory, or an invalid checkout stops before updating.
Noncanonical mirrors/forks must be updated manually using a trusted workflow.

### Input-device access

The input chooser starts collapsed, showing the selected count and up to three
device names. **Choose input devices** opens a bounded, scrolling checklist;
Tab/Shift+Tab and Space work in it. **Copy selected paths** copies the complete
selection, including retained unlisted paths. Missing selections stay visible
in a separate notice and are never silently replaced with another device.

Input checkbox changes and other settings are saved automatically. An empty
input selection is allowed; it does not prevent other settings from being saved.
Saved display and adapter selections are retained when discovery finds different
hardware, until explicitly changed. On save, detected input aliases such as
`/dev/input/event10` are converted to the inventory's preferred stable
`/dev/input/by-id` or `by-path` name when available. This avoids event-number
changes making a saved keyboard selection look like a different device after
restart/replug. All currently detected aliases are reconciled, including when a
new preferred alias appears. Existing configuration is not rewritten on discovery
or launch; undetected/manual paths are retained. Raw event paths without a stable
alias remain vulnerable to Linux event-number reassignment. A `by-path` name
identifies a connection location and may change if the device is moved to another
port.

The manual path editor scrolls when the list is long. **Controller deadzones**
shows the absolute axes detected on selected input devices, with a separate
percentage for each device and axis. Without an override, the existing
`axis_deadzone_percent` default applies, except `ABS_RZ` uses
`rz_deadzone_percent`. Overrides are retained for unavailable devices and
stored in `device_axis_deadzones` by device path and numeric Linux axis code.
Discovery reads sysfs capabilities without opening input devices. An updated
host backend is required to provide axis information to the GUI.

The GUI accepts the host's confirmed saved configuration even if the D-Bus owner
changes before the reply, ignores pre-save refresh replies, and preserves any
further edits made while
saving. The updated backend reports whether a saved configuration file exists;
when none exists, legacy display/adapter/input defaults are not preselected in
the editor, even if those paths currently exist. Older backends cannot provide
that distinction, so their returned configuration is retained as unknown-source
settings rather than guessed to be defaults. Update the host and GUI together
for the full behavior.

### Live settings and rollback

`ApplySettings` stages the requested input set and a replacement selector,
retaining open unchanged devices (including aliases of the same event node).
Additions are opened and seeded before any current device is closed. Deadzone
changes are seeded from current axis metadata. If opening, seeding, registering
an input, validating adapter access or writing the atomic configuration file
fails, staged resources are closed and the prior disk/effective configuration
and functional monitoring set remain active. `GetConfig` reports the effective
runtime configuration, not an unrelated externally edited file.

After a successful save, the same event loop switches to the prepared resources,
closes removed inputs, and applies display, timeout/KDE-timeout mode, mapping
TTL, deadzones, mute-tab labels and CEC settings. Display changes reset axis
baselines and use the current KWin focus output; label changes invalidate old
scans and discard results from the
old label set. Settings changes grant a fresh inactivity interval rather than
immediately issuing standby. CEC fail-safe and wake-recovery policy remain in
force. No new monitor loop, D-Bus subscription or service process is created.
Configuration-only startup failures and later input disconnects can be corrected
with live apply; monitoring resumes without a service restart.

The CEC implementation opens the adapter per power command, not as a persistent
connection. A changed/new adapter is checked with a nonblocking, read/write host
character-device open, then used by subsequent operations. Apply does not send
CEC power/status probes. This checks device access, **not** a complete libCEC/TV
communication handshake; communication faults are still reported when an actual
operation is requested. Adapter changes/disabling CEC are rejected while an
operation is in flight, a command is queued, or TV wake recovery is owed. Complete
a successful TV-on recovery and retry; the old adapter/state remain intact.
Already-queued wake recovery can finish even if input monitoring is paused.

Native and Flatpak GUIs use the same host apply API when connected. Native offline
saves are for the next explicit service start and never execute systemctl.
Input selections retain their existing automatic-save cadence; other settings
still require **Save and apply settings**. A failed apply leaves drafts intact
and reports the error. A later edit is not overwritten by an earlier apply
acknowledgement. `python3 -B tests/run.py live-settings` covers mocked in-process
resource transactions, rollback, same-PID recovery, runtime changes and persistence.

Update the installed host backend once to obtain this API behavior; replacing
running Python code still needs an explicit service restart. An older backend
may restart on `ApplySettings`, and the GUI reports that compatibility limitation
instead of claiming live success. Manual edits to the JSON file require a service
restart; use the GUI/API for live application. Group membership/ACL changes and
host dependency updates still require their applicable host/session steps.

### Input-device permissions

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
across logout (for example with lingering), reboot. Once the GUI reconnects,
open **Diagnostics** and choose **Retry monitoring**. If your account is
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
cd /path/to/topCEC &&
git pull --ff-only origin main &&
bash packaging/install-user.sh &&
systemctl --user restart topcec.service
```

Replace `/path/to/topCEC` with your actual checkout path. The installer preserves
configuration and group membership; restarting loads the updated host code.
Use an up-to-date checkout of the official default branch (`main`).
The installer runs `systemctl --user daemon-reload` to reload unit definitions,
but deliberately does not start or restart the backend. Neither `daemon-reload`
nor `enable --now` replaces an already-running process. An existing service
requires the explicit `restart` above, even if the new files are already on disk.
The `&&` chain stops on failure and works in fish or Bash in a host terminal; these are
instructions for the user, never commands executed by Flatpak.
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
systemctl --user show topcec.service --property=ExecStart --property=MainPID
busctl --user introspect net.local.CecActivity /net/local/CecActivity net.local.CecActivity
```

The live introspection output should include `GetEquipment` after updating and
restarting the host. This checks the running backend, not merely files on disk.

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

To update an existing checkout, reinstall the host files, restart the service,
build/install the user Flatpak, and launch it, run:

```sh
./packaging/update-user.sh
```

The updater requires a clean checkout and pulls the current branch's upstream
with `git pull --ff-only`. Commit or stash local changes first. It uses native
`flatpak-builder` when available, otherwise `flathub-build` from the
`org.flatpak.Builder` Flatpak, and downloads missing build dependencies from
the host user's Flathub remote. It installs the built app through the host's
Flatpak command. From Toolbx it forwards
to the desktop host using `host-spawn`. A failed step stops the update; if the
Flatpak build fails, the host service has already been updated. After a successful
build it closes any running topCEC Flatpak and launches the installed version.
The script stays attached to the GUI until it exits.

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
