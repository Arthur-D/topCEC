#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
set -euo pipefail

SOURCE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="${TOPCEC_VERSION:-0.1.0}"
OUTPUT_DIR="${TOPCEC_RPM_OUTPUT_DIR:-$SOURCE_DIR/dist}"
if ! command -v rpmbuild >/dev/null 2>&1; then
    printf 'rpmbuild is required to build the RPM; no package was installed.\n' >&2
    exit 127
fi

WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/topcec-rpm.XXXXXX")"
trap 'rm -rf -- "$WORK_DIR"' EXIT
for directory in BUILD BUILDROOT RPMS SOURCES SPECS SRPMS; do
    mkdir -p "$WORK_DIR/$directory"
done

ARCHIVE_ROOT="$WORK_DIR/topcec-$VERSION"
mkdir -p "$ARCHIVE_ROOT/cec-tv" "$ARCHIVE_ROOT/packaging" \
    "$ARCHIVE_ROOT/firefox-extension" "$ARCHIVE_ROOT/chromium-extension"
for file in \
    activity.js activity_policy.py cec-kde-settings.py cec-power-command.py \
    cec_power_state.py configuration.py equipment.py firefox_media.py chromium_media.py standby_apps.py firefox-native-host.py chromium-native-host.py \
    native_messaging.py firefox.js monitor.py providers.py \
    start.py topcec_gui.py topcec.qml net.local.topcec.svg; do
    install -m 0644 "$SOURCE_DIR/cec-tv/$file" "$ARCHIVE_ROOT/cec-tv/$file"
done
for file in LICENSE README.md PROVENANCE.md; do
    install -m 0644 "$SOURCE_DIR/$file" "$ARCHIVE_ROOT/$file"
done
for file in topcec.service topcec-gui topcec-gui.desktop \
    net.local.topcec.media.json setup-chromium-extension.py; do
    install -m 0644 "$SOURCE_DIR/packaging/$file" "$ARCHIVE_ROOT/packaging/$file"
done
for file in manifest.json background.js; do
    install -m 0644 "$SOURCE_DIR/firefox-extension/$file" \
        "$ARCHIVE_ROOT/firefox-extension/$file"
    install -m 0644 "$SOURCE_DIR/chromium-extension/$file" \
        "$ARCHIVE_ROOT/chromium-extension/$file"
done

tar -C "$WORK_DIR" -czf "$WORK_DIR/SOURCES/topcec-$VERSION.tar.gz" \
    "topcec-$VERSION"
cp "$SOURCE_DIR/packaging/topcec.spec" "$WORK_DIR/SPECS/topcec.spec"
rpmbuild -ba "$WORK_DIR/SPECS/topcec.spec" \
    --define "_topdir $WORK_DIR" \
    --define "_topcec_version $VERSION" \
    --define "_sourcedir $WORK_DIR/SOURCES"
mapfile -d '' -t RPM_FILES < <(
    find "$WORK_DIR/RPMS" "$WORK_DIR/SRPMS" -type f -name '*.rpm' -print0)
if ((${#RPM_FILES[@]} == 0)); then
    printf 'rpmbuild completed without producing an RPM artifact.\n' >&2
    exit 1
fi
mkdir -p "$OUTPUT_DIR"
cp -- "${RPM_FILES[@]}" "$OUTPUT_DIR/"
printf 'RPM output copied to %s\n' "$OUTPUT_DIR"
