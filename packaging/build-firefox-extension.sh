#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
set -euo pipefail

SOURCE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
OUTPUT="${TOPCEC_FIREFOX_EXTENSION_OUTPUT:-$SOURCE_DIR/dist/topcec-firefox-media.zip}"
mkdir -p "$(dirname -- "$OUTPUT")"
python3 - "$SOURCE_DIR/firefox-extension" "$OUTPUT" <<'PY'
from pathlib import Path
import sys
from zipfile import ZIP_DEFLATED, ZipFile

source = Path(sys.argv[1])
target = Path(sys.argv[2])
with ZipFile(target, 'w', compression=ZIP_DEFLATED) as archive:
    for name in ('manifest.json', 'background.js', 'video.js'):
        path = source / name
        if not path.is_file():
            raise SystemExit(f'Missing Firefox extension file: {path}')
        archive.write(path, name)
print(f'Firefox extension archive written to {target}')
PY
