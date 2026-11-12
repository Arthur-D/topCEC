# SPDX-License-Identifier: GPL-3.0-or-later
"""Read-only host equipment inventory; never opens devices or sends CEC commands."""
import json
from pathlib import Path
import re
import struct
import subprocess


def _entries(directory):
    try:
        return sorted(Path(directory).iterdir())
    except FileNotFoundError:
        return []

def _input_axes(target):
    from evdev import ecodes

    text = (Path('/sys/class/input') / target.name / 'device/capabilities/abs').read_text(
        encoding='ascii').strip()
    words = text.split()
    if not words:
        raise ValueError('Empty absolute-axis capability bitmap')
    bits = 0
    for word in words:
        if not re.fullmatch(r'[0-9a-fA-F]+', word):
            raise ValueError('Invalid absolute-axis capability bitmap')
        bits = (bits << (8 * struct.calcsize('L'))) | int(word, 16)
    axes = []
    for code in range(ecodes.ABS_MT_SLOT):
        if bits & (1 << code):
            name = ecodes.ABS.get(code, f'ABS_{code:02X}')
            if isinstance(name, list):
                name = name[0]
            axes.append({'code': code, 'name': name})
    return axes


def discover_equipment():
    result = {'outputs': [], 'adapters': [], 'inputs': [], 'errors': []}
    try:
        command = subprocess.run(
            ['kscreen-doctor', '-o'], capture_output=True, text=True, timeout=5)
        if command.returncode:
            raise OSError(command.stderr.strip() or 'kscreen-doctor failed')
        output = re.sub(r'\x1b\[[0-9;]*m', '', command.stdout)
        for block in re.split(r'(?=^Output:)', output, flags=re.MULTILINE):
            match = re.match(r'\s*Output:\s+\d+\s+([^\s]+)', block)
            if match and not re.search(r'\bdisconnected\b', block):
                name = match.group(1)
                result['outputs'].append({
                    'path': name,
                    'label': name + (' (disabled)' if re.search(r'\bdisabled\b', block) else ''),
                })
    except (OSError, subprocess.TimeoutExpired) as error:
        result['errors'].append('Display discovery: ' + str(error))

    try:
        for path in _entries('/dev/serial/by-id'):
            # Only identify CEC-named serial adapters, not unrelated serial devices.
            if 'cec' in path.name.lower() and path.exists():
                result['adapters'].append({'path': str(path), 'label': path.name})
    except OSError as error:
        result['errors'].append('CEC adapter discovery: ' + str(error))

    try:
        devices = {}
        for directory in ('/dev/input/by-id', '/dev/input/by-path'):
            for path in _entries(directory):
                if 'event' in path.name and path.exists():
                    devices.setdefault(path.resolve(), []).append(path)
        for path in _entries('/dev/input'):
            if re.fullmatch(r'event\d+', path.name):
                if path.exists():
                    devices.setdefault(path.resolve(), []).append(path)
        for target, paths in devices.items():
            path = paths[0]
            name_file = Path('/sys/class/input') / target.name / 'device/name'
            try:
                name = name_file.read_text(encoding='utf-8', errors='replace').strip()
            except OSError as error:
                name = target.name
                result['errors'].append('Input name discovery: ' + str(error))
            try:
                axes = _input_axes(target)
            except (OSError, ValueError, ImportError) as error:
                axes = None
                result['errors'].append(f'Input axis discovery ({target.name}): {error}')
            result['inputs'].append({
                'path': str(path), 'label': f'{name} - {path}',
                'aliases': list(dict.fromkeys(
                    str(alias) for alias in [*paths[1:], target] if alias != path)),
                'axes': axes,
            })
    except OSError as error:
        result['errors'].append('Input device discovery: ' + str(error))
    return result


if __name__ == '__main__':
    print(json.dumps(discover_equipment(), sort_keys=True))
