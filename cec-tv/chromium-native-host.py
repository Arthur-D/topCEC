#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Relay Chromium-family native messages to the topCEC session service."""
import json
import struct
import subprocess
import sys
import uuid
from pathlib import Path

MAX_MESSAGE_SIZE = 1024 * 1024


def main():
    browser = Path(__file__).with_name('browser-id').read_text(encoding='utf-8').strip()
    if browser not in ('chromium', 'chrome', 'brave', 'edge', 'vivaldi'):
        raise ValueError('Invalid browser ID')
    instance = uuid.uuid4().hex
    while True:
        header = sys.stdin.buffer.read(4)
        if not header:
            return 0
        if len(header) != 4:
            raise EOFError('Truncated native message header')
        length = struct.unpack('<I', header)[0]
        if length == 0 or length > MAX_MESSAGE_SIZE:
            raise ValueError('Invalid native message length')
        raw = sys.stdin.buffer.read(length)
        if len(raw) != length:
            raise EOFError('Truncated native message')
        message = json.loads(raw)
        if not isinstance(message, dict):
            raise ValueError('Invalid native message')
        message['browser'] = browser
        message['instance'] = instance
        payload = json.dumps(message, ensure_ascii=False)
        result = subprocess.run(
            ['gdbus', 'call', '--session', '--dest', 'net.local.topcec.BrowserMedia',
             '--object-path', '/net/local/topcec/BrowserMedia', '--method',
             'net.local.topcec.BrowserMedia.Report', json.dumps(payload, ensure_ascii=False)],
            capture_output=True, text=True, timeout=5)
        if result.returncode:
            raise RuntimeError('Cannot send browser status to topCEC: ' + result.stderr.strip())
        response = b'{"accepted":true}'
        sys.stdout.buffer.write(struct.pack('<I', len(response)) + response)
        sys.stdout.buffer.flush()


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, EOFError, RuntimeError, subprocess.SubprocessError) as error:
        print('topCEC browser bridge failed: ' + str(error), file=sys.stderr)
        sys.exit(1)
