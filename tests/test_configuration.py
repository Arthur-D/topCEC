"""Hardware-free tests for versioned monitor configuration."""
# SPDX-License-Identifier: GPL-3.0-or-later
import json
import io
import runpy
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from contextlib import redirect_stdout, redirect_stderr

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'cec-tv'))
from configuration import (
    DEFAULT_CONFIG, SCHEMA_VERSION, default_config_path, load_config, merge_cli,
    save_config, validate_config,
)
import monitor
import start


class ConfigurationChecks(unittest.TestCase):
    def test_monitor_help_and_validation_errors_are_english(self):
        output = io.StringIO()
        with patch('sys.argv', ['monitor.py', '--help']), \
                patch.object(monitor, 'run') as run, redirect_stdout(output):
            with self.assertRaises(SystemExit) as exit:
                monitor.main()
        self.assertEqual(exit.exception.code, 0)
        run.assert_not_called()
        for text in ('Display output controlling the TV',
                     'Follow KDE display timeout for AC power',
                     'Block standby without fresh Firefox live-bridge reports'):
            self.assertIn(text, ' '.join(output.getvalue().split()))
        output = io.StringIO()
        with patch('sys.argv', ['monitor.py', '--mapping-ttl', '0']), \
                patch.object(monitor, 'run') as run, redirect_stderr(output):
            with self.assertRaises(SystemExit) as exit:
                monitor.main()
        self.assertEqual(exit.exception.code, 2)
        self.assertIn('mapping_ttl_seconds must be a positive finite number',
                      output.getvalue())
        run.assert_not_called()

    def test_launcher_reports_existing_monitor_in_english(self):
        with patch('sys.argv', ['start.py']), \
                patch.object(start, 'qdbus', return_value='true'), \
                patch.object(start.os, 'execv') as execv:
            with self.assertRaisesRegex(
                    RuntimeError, 'Another activity monitor owns the D-Bus name'):
                start.main()
        execv.assert_not_called()

    def test_helper_errors_are_english_without_hardware_access(self):
        kde = runpy.run_path(str(ROOT / 'cec-tv' / 'cec-kde-settings.py'))
        with self.assertRaisesRegex(ValueError, 'Invalid TurnOffDisplayWhenIdle value'):
            kde['parse']('invalid', '600')
        command = runpy.run_path(str(ROOT / 'cec-tv' / 'cec-power-command.py'))
        main = command['main']
        with tempfile.TemporaryDirectory() as directory, \
                patch.dict('os.environ', {'XDG_RUNTIME_DIR': directory}), \
                patch('sys.argv', ['cec-power-command.py', 'off', '--port', 'MOCK']), \
                patch.dict(main.__globals__, {
                    'cec': lambda *args: 'power status: on',
                }), patch.object(command['time'], 'sleep'):
            with self.assertRaisesRegex(RuntimeError, 'TV reports on; expected standby'):
                main()

    def test_default_config_path_uses_xdg_config_home(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.dict('os.environ', {'XDG_CONFIG_HOME': directory}):
            self.assertEqual(default_config_path(),
                             Path(directory) / 'topcec' / 'config.json')

    def test_versioned_config_fills_defaults_and_accepts_overrides(self):
        config = validate_config({
            'schema_version': SCHEMA_VERSION,
            'target_output': 'DP-1',
            'timeout_seconds': None,
            'cec_enabled': True,
            'devices': ['/dev/input/event42'],
        })
        self.assertEqual(config['target_output'], 'DP-1')
        self.assertIsNone(config['timeout_seconds'])
        self.assertTrue(config['cec_enabled'])
        self.assertEqual(config['devices'], ['/dev/input/event42'])
        self.assertEqual(config['mute_labels'], DEFAULT_CONFIG['mute_labels'])

    def test_cli_values_override_config_only_when_explicit(self):
        config = validate_config({
            'schema_version': SCHEMA_VERSION,
            'target_output': 'DP-1',
            'cec_enabled': True,
        })
        args = SimpleNamespace(
            target=None, timeout_seconds=None, mapping_ttl=None, device=None,
            mute_label=None, cec=None, cec_port=None, kde_timeout=None,
            require_snapshot=None, axis_deadzone_percent=None,
            rz_deadzone_percent=None)
        self.assertEqual(merge_cli(config, args)['target_output'], 'DP-1')
        args.target = 'HDMI-A-1'
        args.cec = False
        merged = merge_cli(config, args)
        self.assertEqual(merged['target_output'], 'HDMI-A-1')
        self.assertFalse(merged['cec_enabled'])

    def test_load_config_reports_malformed_json(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            path.write_text('{', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'Cannot load configuration'):
                load_config(path)

    def test_rejects_unsupported_versions_unknown_keys_and_bad_values(self):
        invalid = (
            {'schema_version': 2},
            {'schema_version': SCHEMA_VERSION, 'unknown': True},
            {'schema_version': SCHEMA_VERSION, 'timeout_seconds': 0},
            {'schema_version': SCHEMA_VERSION, 'timeout_seconds': True},
            {'schema_version': SCHEMA_VERSION, 'mapping_ttl_seconds': float('nan')},
            {'schema_version': SCHEMA_VERSION, 'devices': ['/dev/input/event0', '']},
            {'schema_version': SCHEMA_VERSION, 'cec_enabled': 1},
            {'schema_version': SCHEMA_VERSION, 'axis_deadzone_percent': 26},
        )
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_config(value)

    def test_loads_config_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            path.write_text(json.dumps({
                'schema_version': SCHEMA_VERSION,
                'mute_labels': ['Mute tab', 'Mute audio'],
            }), encoding='utf-8')
            self.assertEqual(load_config(path)['mute_labels'],
                             ['Mute tab', 'Mute audio'])

    def test_save_config_validates_and_atomically_writes_private_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'nested' / 'config.json'
            config = save_config(path, {
                'schema_version': SCHEMA_VERSION,
                'target_output': 'DP-1',
            })
            self.assertEqual(load_config(path), config)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with self.assertRaisesRegex(ValueError, 'Unsupported configuration'):
                save_config(path, {'schema_version': 2})
            self.assertEqual(load_config(path), config)

    def test_monitor_cli_loads_config_and_applies_explicit_overrides(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            path.write_text(json.dumps({
                'schema_version': SCHEMA_VERSION,
                'target_output': 'DP-1',
                'cec_enabled': False,
                'timeout_seconds': None,
            }), encoding='utf-8')
            with patch('sys.argv', ['monitor.py', '--config', str(path),
                                    '--target', 'HDMI-A-1']), \
                    patch.object(monitor, 'run', side_effect=lambda args: (
                        self.assertEqual(args.target, 'HDMI-A-1'),
                        self.assertIsNone(args.timeout_seconds),
                        self.assertFalse(args.cec),
                        0)[-1]):
                self.assertEqual(monitor.main(), 0)

    def test_service_launcher_forwards_config_and_preserves_live_cec_guards(self):
        def qdbus(*args, **kwargs):
            if args[0] == 'org.freedesktop.DBus':
                return 'false'
            if any('loadScript' in arg for arg in args):
                return '1'
            return ''

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            path.write_text('{"schema_version": 1}', encoding='utf-8')
            with patch('sys.argv', ['start.py', '--config', str(path)]), \
                    patch.object(start, 'qdbus', side_effect=qdbus), \
                    patch.object(start.os, 'execv') as execv:
                start.main()
            command = execv.call_args.args[1]
            self.assertIn('--config', command)
            self.assertIn(str(path), command)
            self.assertIn('--cec', command)
            self.assertIn('--require-snapshot', command)
            self.assertNotIn('--kde-timeout', command)
            self.assertNotIn('--device', command)

    def test_service_launcher_validates_config_before_loading_bridges(self):
        with patch('sys.argv', ['start.py', '--config', '/missing/topcec.json']), \
                patch.object(start, 'qdbus') as qdbus:
            with self.assertRaisesRegex(ValueError, 'Cannot load configuration'):
                start.main()
        qdbus.assert_not_called()

    def test_service_launcher_uses_existing_default_config(self):
        with tempfile.TemporaryDirectory() as directory:
            config_dir = Path(directory) / 'topcec'
            config_dir.mkdir()
            path = config_dir / 'config.json'
            path.write_text('{"schema_version": 1}', encoding='utf-8')
            def qdbus(*args, **kwargs):
                if args[0] == 'org.freedesktop.DBus':
                    return 'false'
                if any('loadScript' in arg for arg in args):
                    return '1'
                return ''

            with patch.dict('os.environ', {'XDG_CONFIG_HOME': directory}), \
                    patch('sys.argv', ['start.py']), \
                    patch.object(start, 'qdbus', side_effect=qdbus), \
                    patch.object(start.os, 'execv') as execv:
                start.main()
            command = execv.call_args.args[1]
            self.assertIn('--config', command)
            self.assertIn(str(path), command)

    def test_service_launcher_uses_portable_monitor_device_defaults(self):
        def qdbus(*args, **kwargs):
            if args[0] == 'org.freedesktop.DBus':
                return 'false'
            if any('loadScript' in arg for arg in args):
                return '1'
            return ''

        with patch('sys.argv', ['start.py']), \
                patch.object(start, 'qdbus', side_effect=qdbus), \
                patch.object(start.os, 'execv') as execv:
            start.main()
        command = execv.call_args.args[1]
        self.assertIn('--kde-timeout', command)
        self.assertNotIn('--device', command)
        self.assertFalse(any('/dev/input/by-id/' in value for value in command))


if __name__ == '__main__':
    unittest.main(verbosity=2)
