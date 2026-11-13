#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Prepare and register the optional Chromium-family native messaging bridge."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil

BROWSERS = {
    'chromium': ('org.chromium.Chromium', 'chromium'),
    'chrome': ('com.google.Chrome', 'google-chrome'),
    'brave': ('com.brave.Browser', 'BraveSoftware/Brave-Browser'),
    'edge': ('com.microsoft.Edge', 'microsoft-edge'),
    'vivaldi': ('com.vivaldi.Vivaldi', 'vivaldi'),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('browser', choices=BROWSERS)
    parser.add_argument('--flatpak', action='store_true')
    parser.add_argument('--extension-id', help='ID shown in the browser extensions page')
    args = parser.parse_args()
    if args.extension_id and not re.fullmatch('[a-p]{32}', args.extension_id):
        parser.error('extension ID must contain 32 letters from a to p')

    source = Path(__file__).resolve().parent.parent
    home = Path.home()
    app_id, browser_config = BROWSERS[args.browser]
    if args.flatpak:
        flatpak_home = home / '.var' / 'app' / app_id
        data = flatpak_home / 'data' / 'topcec'
        config = flatpak_home / 'config'
    else:
        data = Path(os.environ.get('XDG_DATA_HOME', home / '.local/share')) / 'topcec' / 'browsers' / args.browser
        config = Path(os.environ.get('XDG_CONFIG_HOME', home / '.config'))
    extension = data / 'extension'
    extension.mkdir(parents=True, exist_ok=True)
    for name in ('manifest.json', 'background.js'):
        shutil.copyfile(source / 'chromium-extension' / name, extension / name)
    host = data / 'chromium-native-host.py'
    shutil.copyfile(source / 'cec-tv' / 'chromium-native-host.py', host)
    host.chmod(0o755)
    (data / 'browser-id').write_text(args.browser + '\n', encoding='utf-8')
    print(f'Load unpacked extension from: {extension}')
    if not args.extension_id:
        print('Then rerun this command with --extension-id and the ID shown by the browser.')
        return
    manifest_dir = config / browser_config / 'NativeMessagingHosts'
    manifest_dir.mkdir(parents=True, exist_ok=True)
    target = manifest_dir / 'net.local.topcec.media.json'
    manifest = {
        'name': 'net.local.topcec.media',
        'description': 'topCEC browser media status',
        'path': str(host),
        'type': 'stdio',
        'allowed_origins': ['chrome-extension://' + args.extension_id + '/'],
    }
    if target.exists():
        existing = json.loads(target.read_text(encoding='utf-8'))
        if existing.get('name') != manifest['name'] or existing.get('path') != manifest['path']:
            raise ValueError(f'Refusing to overwrite an unrelated native host: {target}')
    temporary = target.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    temporary.chmod(0o600)
    temporary.replace(target)
    print(f'Registered native host: {target}')
    if args.flatpak:
        print(f'Grant the browser access with: flatpak override --user '
              f'--talk-name=net.local.topcec.BrowserMedia {app_id}')
        print('Fully quit and restart the browser after changing permissions.')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError) as error:
        raise SystemExit('Browser extension setup failed: ' + str(error))
