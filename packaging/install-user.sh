#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
set -euo pipefail

SOURCE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
HOME_DIR="${TOPCEC_HOME:-$HOME}"
APP_DIR="${TOPCEC_APP_DIR:-$HOME_DIR/.local/share/topcec}"
BIN_DIR="${TOPCEC_BIN_DIR:-$HOME_DIR/.local/bin}"
UNIT_DIR="${TOPCEC_USER_UNIT_DIR:-${XDG_CONFIG_HOME:-$HOME_DIR/.config}/systemd/user}"
DATA_DIR="${XDG_DATA_HOME:-$HOME_DIR/.local/share}"

install -d "$APP_DIR/cec-tv" "$BIN_DIR" "$UNIT_DIR"
for file in \
    activity_policy.py cec_power_state.py configuration.py equipment.py firefox_media.py chromium_media.py standby_apps.py \
    native_messaging.py providers.py \
    monitor.py start.py cec-kde-settings.py cec-power-command.py \
    firefox-native-host.py chromium-native-host.py topcec_gui.py activity.js firefox.js topcec.qml; do
    mode=0644
    case "$file" in
        monitor.py|start.py|cec-kde-settings.py|cec-power-command.py|\
        firefox-native-host.py|chromium-native-host.py|topcec_gui.py)
            mode=0755
            ;;
    esac
    install -m "$mode" "$SOURCE_DIR/cec-tv/$file" "$APP_DIR/cec-tv/$file"
done
install -d "$APP_DIR/chromium-extension" "$APP_DIR/packaging"
install -m 0644 "$SOURCE_DIR/chromium-extension/manifest.json" \
    "$SOURCE_DIR/chromium-extension/background.js" \
    "$SOURCE_DIR/chromium-extension/video.js" "$APP_DIR/chromium-extension/"
install -m 0755 "$SOURCE_DIR/packaging/setup-chromium-extension.py" "$APP_DIR/packaging/"
TOPCEC_HOME="$HOME_DIR" TOPCEC_APP_DIR="$APP_DIR" \
    bash "$SOURCE_DIR/packaging/install-firefox-native-host.sh"

install -m 0644 "$SOURCE_DIR/systemd/user/topcec.service" \
    "$UNIT_DIR/topcec.service"
printf '#!/usr/bin/env bash\nexec /usr/bin/python3 %q "$@"\n' \
    "$APP_DIR/cec-tv/topcec_gui.py" > "$BIN_DIR/topcec-gui"
chmod 0755 "$BIN_DIR/topcec-gui"
install -D -m 0644 "$SOURCE_DIR/cec-tv/net.local.topcec.svg" \
    "$DATA_DIR/icons/hicolor/scalable/apps/net.local.topcec.svg"
install -D -m 0644 "$SOURCE_DIR/packaging/topcec-gui.desktop" \
    "$DATA_DIR/applications/net.local.topcec.desktop"

if [[ "${TOPCEC_SKIP_SYSTEMCTL:-0}" != 1 ]]; then
    systemctl --user daemon-reload
fi

printf 'Installed topCEC files under %s\n' "$APP_DIR"
printf 'User unit: %s/topcec.service (not enabled or started)\n' "$UNIT_DIR"
printf 'GUI launcher: %s/topcec-gui\n' "$BIN_DIR"
printf 'Desktop launcher: %s/applications/net.local.topcec.desktop\n' "$DATA_DIR"
printf 'Config is preserved separately at %s/topcec/config.json\n' \
    "${XDG_CONFIG_HOME:-$HOME_DIR/.config}"
printf 'Configure settings with topcec-gui, then enable with:\n'
printf '  systemctl --user enable --now topcec.service\n'
printf 'If updating an already-running backend, daemon-reload does not reload its code.\n'
printf 'Restart it explicitly after installation:\n'
printf '  systemctl --user restart topcec.service\n'
