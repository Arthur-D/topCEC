#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
set -euo pipefail

SOURCE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
HOME_DIR="${TOPCEC_HOME:-$HOME}"
APP_DIR="${TOPCEC_APP_DIR:-$HOME_DIR/.local/share/topcec}"
HOST_DIR="$APP_DIR/cec-tv"
EXTENSION_DIR="$APP_DIR/firefox-extension"
MANIFEST_DIR="${TOPCEC_FIREFOX_NATIVE_DIR:-$HOME_DIR/.mozilla/native-messaging-hosts}"
MANIFEST="$MANIFEST_DIR/net.local.topcec.media.json"

install -d "$HOST_DIR" "$EXTENSION_DIR" "$MANIFEST_DIR"
install -m 0644 "$SOURCE_DIR/cec-tv/firefox_media.py" "$HOST_DIR/firefox_media.py"
install -m 0644 "$SOURCE_DIR/cec-tv/native_messaging.py" "$HOST_DIR/native_messaging.py"
install -m 0755 "$SOURCE_DIR/cec-tv/firefox-native-host.py" \
    "$HOST_DIR/firefox-native-host.py"
install -m 0644 "$SOURCE_DIR/firefox-extension/manifest.json" "$EXTENSION_DIR/"
install -m 0644 "$SOURCE_DIR/firefox-extension/background.js" "$EXTENSION_DIR/"
TOPCEC_FIREFOX_EXTENSION_OUTPUT="$APP_DIR/topcec-firefox-media.zip" \
    bash "$SOURCE_DIR/packaging/build-firefox-extension.sh"
python3 - "$MANIFEST" "$HOST_DIR/firefox-native-host.py" <<'PY'
import json
import sys
from pathlib import Path

target = Path(sys.argv[1])
manifest = {
    'name': 'net.local.topcec.media',
    'description': 'topCEC Firefox media status bridge',
    'path': str(Path(sys.argv[2]).resolve()),
    'type': 'stdio',
    'allowed_extensions': ['topcec-media@topcec.local'],
}
if target.exists():
    try:
        existing = json.loads(target.read_text(encoding='utf-8'))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SystemExit(f'Cannot safely replace native host manifest: {error}')
    if (existing.get('name') != manifest['name']
            or existing.get('path') != manifest['path']):
        raise SystemExit(
            f'Refusing to overwrite an unrelated native host manifest: {target}')
temporary = target.with_suffix('.json.tmp')
temporary.write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
temporary.chmod(0o600)
temporary.replace(target)
PY
printf 'Registered Firefox native host: %s\n' "$MANIFEST"
printf 'Extension source: %s (load/sign it in Firefox to activate the bridge)\n' \
    "$EXTENSION_DIR"
