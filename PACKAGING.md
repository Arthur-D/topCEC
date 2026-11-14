# Packaging and browser setup

See the [README](README.md) for host requirements, first configuration, and
recovery. The [release audit](RELEASE-AUDIT.md) records the findings and fixes.
The first GitHub release ships source and Fedora 44 RPMs. The Flatpak and
browser extensions are optional local builds.

## RPM

On Fedora 44 with `rpm-build` and Python 3 installed, run from the source root:

```sh
bash packaging/build-rpm.sh
```

The builder stages an allowlist of project files and writes binary RPMs and a
source RPM to `dist/`. Set `TOPCEC_RPM_OUTPUT_DIR` to change the output
directory. The version and runtime requirements come from [the spec](packaging/topcec.spec).
The build and installation do not start or enable the service. Do not install
the RPM over a user installation without removing the user unit and launcher
first: they can take precedence over the system copies.

## Flatpak

From the source root, use installed `org.flatpak.Builder` and the user Flathub
remote:

```sh
flatpak run --command=flathub-build org.flatpak.Builder net.local.topcec.yml
mkdir -p dist
flatpak build-bundle --runtime-repo=https://dl.flathub.org/repo/flathub.flatpakrepo repo dist/net.local.topcec.flatpak net.local.topcec
```

With a native builder, replace the first command with
`flatpak-builder --user --install-deps-from=flathub --force-clean --repo=repo builddir net.local.topcec.yml`.
The manifest builds pinned PySide6 against the KDE 6.11 SDK using LLVM 22.
Keep the Qt, PySide/Shiboken and SDK versions compatible when updating it.
If distributing a Flatpak binary, provide the exact topCEC source and the
matching PySide/Shiboken source archive listed in
[the bindings manifest](packaging/flatpak/pyside.yml), together with the build
manifest and applicable notices. The payload includes the license files.
After installing the bundle, verify the actual runtime imports:

```sh
flatpak run --command=python3 net.local.topcec -c 'from PySide6 import QtCore, QtDBus, QtGui, QtQml, QtQuick; print(QtCore.qVersion())'
flatpak run net.local.topcec
```

For a clean Git checkout with an upstream branch, `bash packaging/update-user.sh`
pulls with `--ff-only`, reinstalls and restarts the user host service, then
builds, installs and launches the Flatpak. A failed GUI build can leave the host
at the newer version. Run on the desktop host, or in Toolbx with `host-spawn`.
For a tagged source archive, reinstall from the new archive instead of using
the Git updater.

## Browser media

Enable **Block standby while playing audio** separately for each browser in
**Standby**. When enabled, missing or ambiguous media information can prevent
standby. The extensions send active tab titles and per-tab audible/muted flags
locally to topCEC so it can match playback with a KWin display. They do not send
URLs or page contents.

### Firefox

For Firefox 140 or newer, choose **Install Add-on From File…** in
`about:addons` and select the Mozilla-signed XPI, if available. Private windows
are excluded. The user installer and RPM register the native host. From source
you can register it separately with
`bash packaging/install-firefox-native-host.sh`.

To prepare the optional add-on for distribution:

1. Run `bash packaging/build-firefox-extension.sh`.
2. Submit `dist/topcec-firefox-media.zip` to the
   [Mozilla Add-ons Developer Hub](https://addons.mozilla.org/developers/) under
   **On your own**. Explain what the native host receives and that it stays local.
3. Download the signed XPI. For temporary development testing, use
   `about:debugging#/runtime/this-firefox` and load `firefox-extension/manifest.json`.

Firefox Flatpak needs a version with native messaging proxy support (the
documented target is Firefox 157 or later), a working host proxy and permission
to talk to `org.freedesktop.NativeMessagingProxy`. In `about:config`, set
`widget.use-xdg-desktop-portal.native-messaging-proxy` to `2` (auto-detect) if
disabled, then restart Firefox.

If the extension is unavailable, topCEC can read Firefox's AT-SPI **Mute tab**
label. For a localized Firefox, set the exact label in `mute_labels` in the
host JSON. Finish any first-run Firefox welcome screens, set
`accessibility.force_disabled` to `-1` if needed, and fully restart Firefox.
If the Flatpak's AT-SPI tree is still unavailable, try
`flatpak run --env=GNOME_ACCESSIBILITY=1 org.mozilla.firefox`.
Check **Diagnostics** for detection status.

### Chromium, Chrome, Brave, Edge and Vivaldi

Open **Set up a browser extension** in topCEC's **Standby** page, select the
browser and its installation type, then select **Prepare extension**. On the
browser's extensions page, enable Developer mode and load the displayed folder
as an unpacked extension. Copy the ID back into topCEC and select
**Register native host**. For a Flatpak browser, check the box granting access
to the browser-media D-Bus service and fully restart the browser.

For command-line setup after a user installation:

```sh
python3 ~/.local/share/topcec/packaging/setup-chromium-extension.py chromium --flatpak
```

Use `chrome`, `brave`, `edge` or `vivaldi` as appropriate and omit
`--flatpak` for a native browser. For an RPM install, the script is under
`/usr/share/topcec/packaging/`. Load the printed directory, then append
`--extension-id ID` to the same command and rerun it. With a custom
`--user-data-dir`, place the generated manifest in that directory's
`NativeMessagingHosts`. For Flatpak, run the override printed by the script
and restart the browser. It grants access to `net.local.topcec.BrowserMedia`;
the browser environment needs `python3` and `gdbus`. The topCEC uninstaller
leaves the browser extension, its Chromium registration and any override in
place.

## Hardware-free checks

Run from the source root with Bash; GUI and bridge tests need PySide6 and the
GUI's QML modules, including QtTest for the GUI suite. Equipment tests need
evdev. Chromium integration tests need dbus-python, PyGObject, `gdbus` and
`dbus-run-session`; Node.js can also check the extension code.

```sh
for suite in self-test cec-power cec-power-state activity-policy providers \
  firefox-media chromium-media standby-apps configuration equipment gui \
  live-settings license packaging test_cec_live.py test_kde_settings.py \
  check_fixed.py check_cec.py; do
  python3 -B tests/run.py "$suite" || exit 1
done
python3 -B tests/test_activity_bridge.py
```

The [validation history](VALIDATION.md) records older live and mocked checks.
The test runner does not replace a clean desktop install and HDMI-CEC smoke test.
