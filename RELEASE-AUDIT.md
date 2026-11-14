# First release audit

The findings below describe source revision `2bd4ef2` as reviewed on 2026-11-14.
The first release fixes host startup, RPM packaging and monitor tests.
It ships source and Fedora 44 RPMs. The optional Flatpak builds from the
manifest; a Flatpak binary and signed browser add-ons are outside this release.

| Priority | Finding | Release exit criterion |
| --- | --- | --- |
| Blocker | [The host launcher](cec-tv/start.py#L46) always passes `--cec`, including on a new install or when a saved file has `cec_enabled: false`. With no configured display or adapter, [configuration validation](cec-tv/configuration.py#L82) exits before the monitor owns its D-Bus name. Flatpak cannot configure this host. A disabled configuration with valid hardware paths can instead be overridden at restart. | Respect the saved CEC flag and start a new installation in a mode that exposes configuration without sending CEC traffic. Test missing config, explicit disable across restart, and first live apply from Flatpak. |
| Blocker | [The RPM GUI launcher](packaging/topcec-gui#L5) uses `runpy.run_path()` on a script file without adding that script's directory to the import path. The extracted package, run with PySide6 available and its path redirected to the staged payload, failed with `ModuleNotFoundError: activity_policy`. | Execute the GUI script directly or put its module directory on the Python path. Test the actual installed command and desktop entry. |
| Blocker | [The RPM dependencies](packaging/topcec.spec#L13) do not match Fedora 44 Plasma 6. Fedora repository metadata resolves `/usr/bin/qdbus`, hard-coded in [start.py](cec-tv/start.py#L16), to Qt 4; Qt 6 provides `/usr/bin/qdbus-qt6`. `kirigami` resolves to KF5, while the [GUI](cec-tv/topcec.qml#L5) imports KF6 Kirigami and Kirigami Addons FormCard. `kscreen-doctor` is required by the host equipment helper but declared only in the GUI subpackage. | Resolve the Qt 6 command on supported hosts, use the Fedora KF6 packages, and require display discovery in the host package. Verify installation on a clean Fedora KDE system. |
| Blocker for the RPM | [The spec](packaging/topcec.spec#L6) gets its version from a macro supplied only by [the builder](packaging/build-rpm.sh). It produced two binary RPMs and a source RPM, but plain `rpmbuild --rebuild` from the source RPM failed because the macro remained unexpanded. | Put a concrete version in the packaged spec and make rebuilding the source RPM without private flags a release check. |
| Blocker for release verification | [The monitor self-test](cec-tv/monitor.py#L1521) fails against the audited checkout: 31 tests, 3 failures and 28 errors (some in subtests). The fixtures use the now-empty default target and assume the earlier inactivity timing; runtime fixtures also hit hardware-selection validation. [Launcher tests](tests/test_configuration.py#L240) currently assert forced CEC or stop short of checking whether the resulting command can start with no config. | Use explicit fake hardware and timeout fixtures, and test the boundary between the launcher and monitor. Run all suites in release CI with their dependencies present. |
| High for a public Flatpak | [The manifest](net.local.topcec.yml#L16) has no AppStream metadata. The existing bundle can be exported and imported, but that is insufficient to establish a catalog listing or prove a fresh install. The [binding build](packaging/flatpak/pyside.yml) includes pinned PySide/Shiboken binaries and upstream license texts; the release still needs a documented source and notices delivery plan for the exact bundled versions. | For a direct bundle, test runtime installation and GUI setup from a fresh profile and review bundled source/notices before distributing. For a catalog submission, also add and validate AppStream metadata and check the app ID and catalog requirements. |
| Optional Firefox deliverable | [The Firefox builder](packaging/build-firefox-extension.sh) generates an unsigned ZIP; the repository and RPM do not supply a signed XPI. Mozilla signing and fresh-profile installation were not verified. | If shipping the extension, attach and test a signed XPI. Otherwise document the AT-SPI fallback and leave the XPI out of the initial release. |

The desktop entry ID is shared by the native installer, RPM and Flatpak.
The local desktop entry can take precedence on systems with multiple install
methods. Test the menu entry you intend users to launch, and document how to
switch between host package types. Also ensure the new README's linked guides
are shipped if it is installed as RPM documentation; the current spec lists
only README and provenance.

## Evidence from the original audit

- Built the binary and source RPMs using Fedora 44 RPM tools staged in a
  temporary directory. Inspected dependency declarations and reproduced the
  launcher and source-RPM rebuild failures without installing either package.
- Parsed the Flatpak manifest, exported and reimported the existing x86_64
  bundle, verified Qt 6.11.3 imports, and loaded one QML root object offscreen.
  The four installed GUI source files matched the audited checkout. The
  repository export is an existing build; no clean rebuild or installation
  was performed.
- Passed the staged installer/uninstaller, configuration, live settings, CEC
  power, activity policy, providers, Firefox and Chromium media (including the
  isolated D-Bus tests), licensing, equipment, historical fixtures and eight
  KWin JavaScript bridge tests. The monitor self-test failed as above.
  The full GUI suite requires a test-capable PySide6 build with QtTest; the
  shipped Flatpak bindings omit QtTest.
- Built and inspected the Firefox ZIP. No add-on submission, service changes,
  or TV power commands were performed.

After the blockers are resolved, choose a tagged revision and verify that exact
source and each advertised artifact on a clean Plasma 6 Wayland system. Test
installation, configuration from an empty profile, login startup, confirmed
standby and wake on hardware, recovery from an absent/unreadable device, and
uninstall with configuration preserved. Publish only the formats that pass,
with versions, supported platform/architecture, checksums and release notes.

## Fixes in 0.1.0

The host honors saved CEC settings and serves its configuration API on first
start. The Fedora RPM requires Qt 6 qdbus, KF6 modules and host discovery tools.
Its GUI executes the installed script directly, and the source RPM carries
its version and rebuilds without local macro overrides. The Flatpak exports
validated AppStream metadata. The monitor fixtures use explicit hardware and
timeouts. Tests exercise startup with missing, disabled, and enabled settings.
Physical HDMI-CEC standby and wake and startup at Plasma login still require
a desktop and hardware test.
