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
        builder=(flatpak-builder --user --install-deps-from=flathub
            --force-clean --repo=repo builddir)
    elif flatpak info org.flatpak.Builder >/dev/null 2>&1; then
        # flathub-build points dependency installation at the host's user
        # Flatpak directory and uses the host Flatpak binary.
        builder=(flatpak run --command=flathub-build org.flatpak.Builder)
    else
        printf 'Install flatpak-builder or the org.flatpak.Builder Flatpak first.\n' >&2
        return 1
    fi

    if git rev-parse --verify -q MERGE_HEAD >/dev/null; then
        printf 'Finish or abort the in-progress Git merge before updating.\n' >&2
        return 1
    fi

    local checkout_status
    checkout_status=$(git status --porcelain --untracked-files=normal)
    if [[ -n "$checkout_status" ]]; then
        printf 'The checkout has local changes. Commit or stash them before updating.\n' >&2
        return 1
    fi
    printf 'Pulling the current branch from its Git upstream...\n'
    if ! git pull --no-rebase --ff --no-edit --no-autostash; then
        if git rev-parse --verify -q MERGE_HEAD >/dev/null; then
            if git merge --abort; then
                printf 'Git merge stopped and was aborted. Merge the upstream branch manually, then rerun the updater.\n' >&2
            else
                printf 'Git could not abort the merge. Check git status before rerunning the updater.\n' >&2
            fi
        fi
        return 1
    fi

    printf 'Installing host files and restarting topcec.service...\n'
    bash packaging/install-user.sh
    systemctl --user restart topcec.service
    systemctl --user is-active --quiet topcec.service

    printf 'Building and installing the user Flatpak...\n'
    "${builder[@]}" net.local.topcec.yml
    # Install outside the Builder sandbox into the desktop user's installation.
    flatpak install --user --reinstall --noninteractive "$SOURCE_DIR/repo" net.local.topcec

    # Close an old instance only after a successful build/install.
    if [[ -n "$(flatpak ps --columns=application | sed -n '/^net\.local\.topcec$/p')" ]]; then
        flatpak kill net.local.topcec
    fi
    printf 'Starting topCEC Flatpak...\n'
    exec flatpak run net.local.topcec
}

# Read the whole function before git pull can replace this script.
main "$@"
