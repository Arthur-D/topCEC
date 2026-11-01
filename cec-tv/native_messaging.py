# SPDX-License-Identifier: GPL-3.0-or-later
"""Firefox native-messaging framing and payload validation."""
import json
import struct

MAX_MESSAGE_SIZE = 1024 * 1024


def read_exact(stream, length, allow_eof=False):
    chunks = []
    remaining = length
    while remaining:
        chunk = stream.read(remaining)
        if not chunk:
            if allow_eof and not chunks:
                return None
            raise EOFError('Truncated Firefox native-messaging frame')
        chunks.append(chunk)
        remaining -= len(chunk)
    return b''.join(chunks)


def read_message(stream):
    header = read_exact(stream, 4, allow_eof=True)
    if header is None:
        return None
    length = struct.unpack('<I', header)[0]
    if length == 0 or length > MAX_MESSAGE_SIZE:
        raise ValueError('Invalid Firefox native-messaging message length')
    return json.loads(read_exact(stream, length).decode('utf-8'))


def write_message(stream, value):
    payload = json.dumps(value, separators=(',', ':')).encode('utf-8')
    if not payload or len(payload) > MAX_MESSAGE_SIZE:
        raise ValueError('Firefox native-messaging response is too large')
    stream.write(struct.pack('<I', len(payload)))
    stream.write(payload)
    stream.flush()
