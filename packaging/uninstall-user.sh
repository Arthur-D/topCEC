#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
set -euo pipefail

HOME_DIR="${TOPCEC_HOME:-$HOME}"
APP_DIR="${TOPCEC_APP_DIR:-$HOME_DIR/.local/share/topcec}"
BIN_DIR="${TOPCEC_BIN_DIR:-$HOME_DIR/.local/bin}"
UNIT_DIR="${TOPCEC_USER_UNIT_DIR:-${XDG_CONFIG_HOME:-$HOME_DIR/.config}/systemd/user}"
DATA_DIR="${XDG_DATA_HOME:-$HOME_DIR/.local/share}"
NATIVE_HOST_MANIFEST="${TOPCEC_FIREFOX_NATIVE_DIR:-$HOME_DIR/.mozilla/native-messaging-hosts}/net.local.topcec.media.json"
NATIVE_HOST_PATH="$APP_DIR/cec-tv/firefox-native-host.py"

if [[ "${TOPCEC_SKIP_SYSTEMCTL:-0}" != 1 && -f "$UNIT_DIR/topcec.service" ]]; then
    if systemctl --user is-active --quiet topcec.service; then
        systemctl --user stop topcec.service
    fi
    unit_state="$(systemctl --user is-enabled topcec.service 2>/dev/null || true)"
    case "$unit_state" in
        enabled|enabled-runtime|linked|linked-runtime|alias)
            systemctl --user disable topcec.service
            ;;
    esac
fi

rm -f -- "$BIN_DIR/topcec-gui" "$UNIT_DIR/topcec.service"
rm -f -- "$DATA_DIR/applications/net.local.topcec.desktop" \
    "$DATA_DIR/icons/hicolor/scalable/apps/net.local.topcec.svg"
if [[ -f "$NATIVE_HOST_MANIFEST" ]]; then
    if python3 - "$NATIVE_HOST_MANIFEST" "$NATIVE_HOST_PATH" <<'PY'
import json
import sys
try:
    with open(sys.argv[1], encoding='utf-8') as stream:
        manifest = json.load(stream)
except (OSError, UnicodeError, json.JSONDecodeError):
    raise SystemExit(1)
raise SystemExit(0 if manifest.get('name') == 'net.local.topcec.media'
                 and manifest.get('path') == sys.argv[2] else 1)
PY
    then
        rm -f -- "$NATIVE_HOST_MANIFEST"
    else
        printf 'Preserved modified or unrelated Firefox native host manifest: %s\n' \
            "$NATIVE_HOST_MANIFEST"
    fi
fi
for file in \
    activity_policy.py cec_power_state.py configuration.py equipment.py firefox_media.py chromium_media.py standby_apps.py \
    native_messaging.py providers.py firefox-native-host.py chromium-native-host.py \
    monitor.py start.py cec-kde-settings.py cec-power-command.py \
    topcec_gui.py activity.js firefox.js topcec.qml; do
    rm -f -- "$APP_DIR/cec-tv/$file"
done
rm -f -- "$APP_DIR/firefox-extension/manifest.json" \
    "$APP_DIR/firefox-extension/background.js" "$APP_DIR/firefox-extension/video.js"
rm -f -- "$APP_DIR/topcec-firefox-media.zip"
rm -f -- "$APP_DIR/chromium-extension/manifest.json" \
    "$APP_DIR/chromium-extension/background.js" "$APP_DIR/chromium-extension/video.js" \
    "$APP_DIR/packaging/setup-chromium-extension.py"
rmdir -- "$APP_DIR/chromium-extension" "$APP_DIR/packaging" 2>/dev/null || true
rmdir -- "$APP_DIR/firefox-extension" 2>/dev/null || true
if rmdir -- "$APP_DIR/cec-tv" 2>/dev/null; then
    if ! rmdir -- "$APP_DIR" 2>/dev/null; then
        printf 'Preserved non-empty application directory: %s\n' "$APP_DIR"
    fi
elif [[ -d "$APP_DIR/cec-tv" ]]; then
    printf 'Preserved non-empty application directory: %s/cec-tv\n' "$APP_DIR"
fi

if [[ "${TOPCEC_SKIP_SYSTEMCTL:-0}" != 1 ]]; then
    systemctl --user daemon-reload
fi

printf 'Removed topCEC application files and user unit.\n'
printf 'User configuration under %s/topcec was left untouched.\n' \
    "${XDG_CONFIG_HOME:-$HOME_DIR/.config}"
