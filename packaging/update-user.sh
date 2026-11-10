#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
set -euo pipefail

SOURCE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

# The service and installed Flatpak belong to the desktop host, not Toolbx.
if [[ -f /run/.containerenv || -f /.dockerenv ]]; then
    if ! command -v host-spawn >/dev/null; then
        printf 'Run this script on the desktop host (host-spawn is unavailable).\n' >&2
        exit 1
    fi
    exec host-spawn bash "$SOURCE_DIR/packaging/update-user.sh" "$@"
fi

main() {
    if (( $# )); then
        printf 'Usage: %s\n' "$0" >&2
        return 2
    fi
    cd -- "$SOURCE_DIR"
    for command in git systemctl flatpak; do
        command -v "$command" >/dev/null || {
            printf 'Required command missing: %s\n' "$command" >&2
            return 1
        }
    done

    local -a builder
    if command -v flatpak-builder >/dev/null; then
        builder=(flatpak-builder)
    elif flatpak info org.flatpak.Builder >/dev/null 2>&1; then
        builder=(flatpak run --command=flatpak-builder org.flatpak.Builder)
    else
        printf 'Install flatpak-builder or the org.flatpak.Builder Flatpak first.\n' >&2
        return 1
    fi

    if [[ -n "$(git status --porcelain --untracked-files=normal)" ]]; then
        printf 'The checkout has local changes. Commit or stash them before updating.\n' >&2
        return 1
    fi
    printf 'Pulling the current branch from its Git upstream...\n'
    git pull --ff-only

    printf 'Installing host files and restarting topcec.service...\n'
    bash packaging/install-user.sh
    systemctl --user restart topcec.service
    systemctl --user is-active --quiet topcec.service

    printf 'Building and installing the user Flatpak...\n'
    "${builder[@]}" --user --install --install-deps-from=flathub \
        --force-clean --repo=repo builddir net.local.topcec.yml

    # Close an old instance only after a successful build/install.
    if [[ -n "$(flatpak ps --columns=application | sed -n '/^net\.local\.topcec$/p')" ]]; then
        flatpak kill net.local.topcec
    fi
    printf 'Starting topCEC Flatpak...\n'
    exec flatpak run net.local.topcec
}

# Read the whole function before git pull can replace this script.
main "$@"
