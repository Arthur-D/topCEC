# topCEC

topCEC uses HDMI-CEC to put one TV on standby after inactivity and wake it when
you return. It runs in a KDE Plasma 6 Wayland session on Linux. You can choose
which displays, input devices and apps keep the TV awake.

## Install and configure

The **host service** runs outside any sandbox and handles hardware, Plasma
activity and settings. Use the user installer or the Fedora 44 RPM for the host.
The optional Flatpak is a GUI for that service.

On the desktop host, make sure you have a CEC adapter supported by libCEC and a
TV with HDMI-CEC enabled. The host needs systemd user services, session D-Bus,
Python 3 with dbus-python, PyGObject, evdev and pyatspi, and the commands
`cec-client`, Qt 6 `qdbus` (for example, `qdbus-qt6` on Fedora),
`/usr/bin/kreadconfig6`, `kscreen-doctor` and `gdbus`. The native GUI also needs PySide6,
Kirigami and Kirigami Addons (FormCard), and Qt Quick Controls and Layouts.

For a user installation, unpack the source from [GitHub Releases](https://github.com/Arthur-D/topCEC/releases)
or clone the repository. From the source root:

```sh
bash packaging/install-user.sh
systemctl --user enable --now topcec.service
~/.local/bin/topcec-gui
```

For Fedora 44, download both binary RPMs, install them together with
`sudo dnf install ./topcec-*.noarch.rpm`, then run
`systemctl --user daemon-reload`, enable the service as above and open
`topcec-gui`. Remove a previous user installation before switching to the RPM.

On first start, the host accepts settings with CEC off. In **Display**, select
the TV output and CEC adapter to enable it. If discovery misses your hardware,
enter its output name or path manually. In **Input**, choose any devices to
monitor; prefer stable `/dev/input/by-id/` or `/dev/input/by-path/` paths.
An empty input list is valid. In **Standby**, choose the timeout and displays
where mouse movement and app activity should count.

Run the service as your desktop user. That user needs read/write access to the
CEC adapter and read access to the selected input devices. Disable any older
CEC controller that manages the same TV. After the service connects, check
**Diagnostics** and verify wake and standby from **Overview**. The simulation
switch only previews manual GUI actions; it does not pause background standby.

You can also [build the optional Flatpak GUI](PACKAGING.md#flatpak). Start the
host first, then install and open the GUI:

```sh
flatpak install --user ./net.local.topcec.flatpak
flatpak run net.local.topcec
```

The bundle needs KDE Platform 6.11 from Flathub. The GUI can configure the host
after it connects and has no direct access to CEC or input devices. Use **Retry
Connection** after starting or updating the host. If the desktop menu opens the
native GUI instead, use `flatpak run net.local.topcec` explicitly.

## Standby settings

- **Timeout:** By default, topCEC follows Plasma's AC display timeout. If it
  cannot read the setting, the fallback is five minutes. If the Plasma timeout
  is explicitly disabled, automatic standby stays disabled. You can also set
  a custom timeout or disable automatic standby in topCEC.
- **Input:** The input device toggle ignores selected devices without clearing
  the list. You can set per-device, per-axis deadzones for controllers. Mouse
  movement is independent and counts only on the displays selected in **Standby**.
- **Apps:** Turn off **Allow standby** for an app to honor its Plasma screen
  inhibition requests. Use **Force block standby** if a window on a selected
  display should count even without an inhibition request. Browser audio is a
  separate option, off by default. See [browser setup](PACKAGING.md#browser-media).
  Stale or ambiguous data can keep the TV awake. Check **Currently blocking
  standby** and **Diagnostics** for the reason.

Settings save automatically after a short pause. A running host applies the
changes without restarting. An offline native GUI saves for the next start.
Saved hardware paths are retained when hardware disappears; choose a replacement
or explicitly remove unlisted inputs.
If saving fails, the draft and error remain visible without repeatedly retrying.
Correct the settings or use **Retry saving** after resolving the error.

## Configure without the GUI

The host reads `${XDG_CONFIG_HOME:-$HOME/.config}/topcec/config.json`; `start.py`
also accepts `--config PATH`. Create the `topcec` directory first. Replace
the example display and adapter with your actual values:

```json
{
  "schema_version": 1,
  "target_output": "HDMI-A-1",
  "cec_port": "/dev/ttyACM0",
  "cec_enabled": true,
  "devices": [],
  "mouse_outputs": ["HDMI-A-1"],
  "kde_timeout": true,
  "timeout_seconds": 300
}
```

Use `kscreen-doctor -o` to find the KWin output name. The display and adapter
have no hardware defaults. Set `kde_timeout` to `false` to use
`timeout_seconds` directly; use `null` for no custom timeout or fallback.
An empty `mouse_outputs` list selects no displays; omitted or `null` falls
back to the legacy `mouse_output`, then `target_output`. The
[configuration schema](cec-tv/configuration.py) lists the remaining keys and
defaults. Unknown keys and invalid values are rejected. Restart the service
after editing JSON by hand. Keep `cec_enabled` false to start without CEC
commands. Selecting a CEC adapter in the GUI enables CEC.

## Recover, update or remove

If the host reports **configuration-only** mode, fix the missing or unreadable
input path in the GUI and save. If the saved paths are already correct, choose
**Diagnostics → Retry monitoring**. Neither a Flatpak device override nor
running the GUI as root fixes host device permissions.

If **Diagnostics** offers an input-group command for your device, run it from
a host terminal. On Atomic desktops such as Bazzite, use the command the GUI
provides for an `input` group defined in `/usr/lib/group`. Joining `input`
grants access to other input events, including keyboard events; ask your
administrator about a per-device permission if that is too broad. Log out
fully and back in (or reboot if the user manager persists), then retry
monitoring. If no group command is offered, check the device's ownership and
access rules.

For connection failures, check the service and its current-boot logs:

```sh
systemctl --user status topcec.service
journalctl --user -b -u topcec.service
```

Use **Copy diagnostics** for reports; logs may contain window or tab titles.
If the GUI reports an older host, update both installations. For a user
installation, rerun the installer from the updated source and then run
`systemctl --user restart topcec.service`. Updating only the Flatpak leaves
the host unchanged. See [Packaging](PACKAGING.md) for the checkout updater.

Remove a user installation with `bash packaging/uninstall-user.sh`. Remove RPM
packages with your package manager after disabling and stopping the user unit.
Remove the Flatpak with `flatpak uninstall --user net.local.topcec`. User
configuration is kept; remove optional browser extensions and overrides
separately.

topCEC is licensed under [GPL-3.0-or-later](LICENSE). See
[Packaging](PACKAGING.md) for builds and tests, and
[Provenance](PROVENANCE.md) for the source history and licensing scope.
