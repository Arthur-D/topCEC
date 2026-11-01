# SPDX-License-Identifier: GPL-3.0-or-later
%global _topcec_appdir %{_libexecdir}/topcec
%global _userunitdir %{_prefix}/lib/systemd/user

Name:           topcec
Version:        %{_topcec_version}
Release:        1%{?dist}
Summary:        Per-display HDMI-CEC power management for KDE Plasma
License:        GPL-3.0-or-later
BuildArch:      noarch
Source0:        topcec-%{version}.tar.gz

Requires:       python3
Requires:       python3-dbus
Requires:       python3-gobject
Requires:       python3-evdev
Requires:       python3-pyatspi
Requires:       systemd
Requires:       /usr/bin/qdbus
Requires:       /usr/bin/kreadconfig6
Requires:       /usr/bin/cec-client

%description
topCEC monitors KDE Wayland activity and Firefox audio accessibility state to
control one configured HDMI-CEC television. The service runs in the user's
graphical session and is not enabled automatically.

%package gui
Summary:        Optional Kirigami control panel for topCEC
Requires:       %{name} = %{version}-%{release}
Requires:       python3-pyside6
Requires:       kirigami
Requires:       /usr/bin/kscreen-doctor

%description gui
Optional PySide6/Kirigami graphical settings and manual-control client. The
topCEC service remains independently operable without this subpackage.

%prep
%autosetup -n topcec-%{version}

%build
# Python scripts and QML are installed as source; no compilation is required.

%install
install -d %{buildroot}%{_topcec_appdir}/cec-tv
install -m 0644 cec-tv/activity.js \
    cec-tv/activity_policy.py \
    cec-tv/cec-kde-settings.py \
    cec-tv/cec-power-command.py \
    cec-tv/cec_power_state.py \
    cec-tv/configuration.py \
    cec-tv/firefox_media.py \
    cec-tv/firefox.js \
    cec-tv/monitor.py \
    cec-tv/native_messaging.py \
    cec-tv/providers.py \
    cec-tv/start.py \
    %{buildroot}%{_topcec_appdir}/cec-tv/
install -m 0755 cec-tv/firefox-native-host.py \
    %{buildroot}%{_topcec_appdir}/cec-tv/firefox-native-host.py
install -d %{buildroot}%{_prefix}/lib/mozilla/native-messaging-hosts
install -m 0644 packaging/net.local.topcec.media.json \
    %{buildroot}%{_prefix}/lib/mozilla/native-messaging-hosts/net.local.topcec.media.json
install -d %{buildroot}%{_datadir}/topcec/firefox-extension
install -m 0644 firefox-extension/manifest.json firefox-extension/background.js \
    %{buildroot}%{_datadir}/topcec/firefox-extension/
install -d %{buildroot}%{_userunitdir}
install -m 0644 packaging/topcec.service \
    %{buildroot}%{_userunitdir}/topcec.service
install -m 0755 cec-tv/cec-kde-settings.py \
    %{buildroot}%{_topcec_appdir}/cec-tv/cec-kde-settings.py
install -m 0755 cec-tv/cec-power-command.py \
    %{buildroot}%{_topcec_appdir}/cec-tv/cec-power-command.py
install -m 0755 cec-tv/monitor.py \
    %{buildroot}%{_topcec_appdir}/cec-tv/monitor.py
install -m 0755 cec-tv/start.py \
    %{buildroot}%{_topcec_appdir}/cec-tv/start.py

install -d %{buildroot}%{_bindir}
install -m 0755 packaging/topcec-gui %{buildroot}%{_bindir}/topcec-gui
install -m 0755 cec-tv/topcec_gui.py \
    %{buildroot}%{_topcec_appdir}/cec-tv/topcec_gui.py
install -m 0644 cec-tv/topcec.qml \
    %{buildroot}%{_topcec_appdir}/cec-tv/topcec.qml
install -d %{buildroot}%{_datadir}/applications
install -m 0644 packaging/topcec-gui.desktop \
    %{buildroot}%{_datadir}/applications/net.local.topcec.desktop
install -D -m 0644 cec-tv/net.local.topcec.svg \
    %{buildroot}%{_datadir}/icons/hicolor/scalable/apps/net.local.topcec.svg

%files
%license LICENSE
%doc README.md PROVENANCE.md
%dir %{_topcec_appdir}
%dir %{_topcec_appdir}/cec-tv
%{_topcec_appdir}/cec-tv/activity.js
%{_topcec_appdir}/cec-tv/activity_policy.py
%{_topcec_appdir}/cec-tv/cec-kde-settings.py
%{_topcec_appdir}/cec-tv/cec-power-command.py
%{_topcec_appdir}/cec-tv/cec_power_state.py
%{_topcec_appdir}/cec-tv/configuration.py
%{_topcec_appdir}/cec-tv/firefox_media.py
%{_topcec_appdir}/cec-tv/native_messaging.py
%{_topcec_appdir}/cec-tv/firefox-native-host.py
%{_topcec_appdir}/cec-tv/firefox.js
%{_topcec_appdir}/cec-tv/monitor.py
%{_topcec_appdir}/cec-tv/providers.py
%{_topcec_appdir}/cec-tv/start.py
%{_userunitdir}/topcec.service
%{_prefix}/lib/mozilla/native-messaging-hosts/net.local.topcec.media.json
%dir %{_datadir}/topcec
%{_datadir}/topcec/firefox-extension/manifest.json
%{_datadir}/topcec/firefox-extension/background.js

%files gui
%{_bindir}/topcec-gui
%{_topcec_appdir}/cec-tv/topcec_gui.py
%{_topcec_appdir}/cec-tv/topcec.qml
%{_datadir}/applications/net.local.topcec.desktop
%{_datadir}/icons/hicolor/scalable/apps/net.local.topcec.svg

%changelog
* Sun Nov 01 2026 topCEC contributors - 0.1.0-1
- Initial RPM package
