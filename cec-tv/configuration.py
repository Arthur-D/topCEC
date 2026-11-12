# SPDX-License-Identifier: GPL-3.0-or-later
"""Versioned JSON configuration for the topCEC monitor."""
import json
import math
import os
from pathlib import Path
import tempfile

SCHEMA_VERSION = 1
DEFAULT_CONFIG = {
    'target_output': 'HDMI-A-2',
    'timeout_seconds': 60,
    'mapping_ttl_seconds': 15.0,
    'devices': ['/dev/input/event10', '/dev/input/event14'],
    'mute_labels': ['Mute tab'],
    'cec_enabled': False,
    'cec_port': '/dev/serial/by-id/usb-Pulse-Eight_CEC_Adapter_v12-if00',
    'kde_timeout': False,
    'require_snapshot': False,
    'axis_deadzone_percent': 2.0,
    'rz_deadzone_percent': 5.0,
    'device_axis_deadzones': {},
}


def default_config_path():
    config_home = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config'))
    return config_home / 'topcec' / 'config.json'


def validate_config(value):
    if not isinstance(value, dict):
        raise ValueError('Configuration root must be a JSON object')
    version = value.get('schema_version')
    if type(version) is not int or version != SCHEMA_VERSION:
        raise ValueError(f'Unsupported configuration schema_version: {version!r}')
    unknown = set(value) - {'schema_version', *DEFAULT_CONFIG}
    if unknown:
        raise ValueError('Unknown configuration keys: ' + ', '.join(sorted(unknown)))

    config = DEFAULT_CONFIG.copy()
    config.update({key: item for key, item in value.items() if key != 'schema_version'})
    if not isinstance(config['target_output'], str) or not config['target_output'].strip():
        raise ValueError('target_output must be a non-empty string')
    if config['timeout_seconds'] is not None and (
        type(config['timeout_seconds']) is not int or config['timeout_seconds'] <= 0
    ):
        raise ValueError('timeout_seconds must be a positive integer or null')
    ttl = config['mapping_ttl_seconds']
    if type(ttl) not in (int, float) or not math.isfinite(ttl) or ttl <= 0:
        raise ValueError('mapping_ttl_seconds must be a positive finite number')
    config['mapping_ttl_seconds'] = float(ttl)
    for key in ('devices', 'mute_labels'):
        values = config[key]
        if (not isinstance(values, list) or (key == 'mute_labels' and not values)
                or any(not isinstance(item, str) or not item.strip() for item in values)):
            raise ValueError(f'{key} must be a non-empty array of non-empty strings')
    for key in ('cec_enabled', 'kde_timeout', 'require_snapshot'):
        if type(config[key]) is not bool:
            raise ValueError(f'{key} must be a boolean')
    for key in ('cec_port',):
        if not isinstance(config[key], str) or not config[key].strip():
            raise ValueError(f'{key} must be a non-empty string')
    for key in ('axis_deadzone_percent', 'rz_deadzone_percent'):
        number = config[key]
        if (type(number) not in (int, float) or not math.isfinite(number)
                or not 0 < number <= 25):
            raise ValueError(f'{key} must be a finite number greater than 0 and at most 25')
        config[key] = float(number)
    overrides = config['device_axis_deadzones']
    if not isinstance(overrides, dict):
        raise ValueError('device_axis_deadzones must be an object')
    for path, axes in overrides.items():
        if not isinstance(path, str) or not path.strip() or not isinstance(axes, dict):
            raise ValueError('device_axis_deadzones must map device paths to axis objects')
        for code, number in axes.items():
            if (not isinstance(code, str) or not code.isascii() or not code.isdecimal()
                    or str(int(code)) != code or not 0 <= int(code) < 47
                    or type(number) not in (int, float) or not math.isfinite(number)
                    or not 0 < number <= 25):
                raise ValueError('Invalid device axis deadzone')
    return config


def load_config(path):
    try:
        value = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f'Cannot load configuration {path}: {error}') from error
    return validate_config(value)


def save_config(path, value):
    config = validate_config(value)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_path = tempfile.mkstemp(
        prefix=target.name + '.', suffix='.tmp', dir=target.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump({'schema_version': SCHEMA_VERSION, **config}, stream, indent=2)
            stream.write('\n')
        os.chmod(temporary_path, 0o600)
        os.replace(temporary_path, target)
    except Exception:
        try:
            os.unlink(temporary_path)
        except FileNotFoundError:
            pass
        raise
    return config


def merge_cli(config, args):
    for key, value in (
        ('target_output', args.target),
        ('timeout_seconds', args.timeout_seconds),
        ('mapping_ttl_seconds', args.mapping_ttl),
        ('devices', args.device),
        ('mute_labels', args.mute_label),
        ('cec_enabled', args.cec),
        ('cec_port', args.cec_port),
        ('kde_timeout', args.kde_timeout),
        ('require_snapshot', args.require_snapshot),
        ('axis_deadzone_percent', args.axis_deadzone_percent),
        ('rz_deadzone_percent', args.rz_deadzone_percent),
    ):
        if value is not None:
            config[key] = value
    return validate_config({'schema_version': SCHEMA_VERSION, **config})
