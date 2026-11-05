"""Staged tests for the user-level installer and uninstaller."""
# SPDX-License-Identifier: GPL-3.0-or-later
import os
import ast
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class UserPackagingChecks(unittest.TestCase):
    def test_copyable_host_update_command_is_guarded_and_fail_fast(self):
        source = ast.parse((ROOT / 'cec-tv/topcec_gui.py').read_text())
        command = next(ast.literal_eval(node.value) for node in source.body
                       if isinstance(node, ast.Assign)
                       and any(isinstance(target, ast.Name) and target.id == 'HOST_UPDATE_COMMAND'
                               for target in node.targets))
        self.assertEqual(len(command.splitlines()), 1)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checkout = root / 'checkout with spaces and a quote " $literal'
            checkout.mkdir()
            starting_directory = root / 'unrelated starting directory'
            starting_directory.mkdir()
            tools = root / 'tools'
            tools.mkdir()
            (checkout / 'packaging').mkdir()
            (checkout / 'packaging/install-user.sh').touch()
            log = root / 'calls'
            scripts = {
                'git': (
                    'test "$PWD" = "$EXPECTED_CHECKOUT" || exit 98\n'
                    'case "$1" in\n'
                    'rev-parse) printf "%s" "$PREFIX"; exit "$ROOT_EXIT" ;;\n'
                    'branch) printf "%s" "$BRANCH" ;;\n'
                    'remote) printf "%s" "$ORIGIN" ;;\n'
                    'pull) echo "pull $*" >> "$CALL_LOG"; exit "$PULL_EXIT" ;;\n'
                    '*) exit 99 ;; esac\n'),
                'bash': (
                    'test "$PWD" = "$EXPECTED_CHECKOUT" || exit 98\n'
                    'echo "install $*" >> "$CALL_LOG"; exit "$INSTALL_EXIT"\n'),
                'systemctl': 'echo "restart $*" >> "$CALL_LOG"; exit "$RESTART_EXIT"\n',
            }
            for name, script in scripts.items():
                path = tools / name
                path.write_text('#!/bin/sh\n' + script)
                path.chmod(0o755)
            environment = {
                **os.environ, 'PATH': str(tools) + os.pathsep + os.environ['PATH'],
                'CALL_LOG': str(log), 'PREFIX': '', 'ROOT_EXIT': '0',
                'EXPECTED_CHECKOUT': str(checkout),
                'BRANCH': 'main', 'ORIGIN': 'https://github.com/Arthur-D/topCEC.git',
                'PULL_EXIT': '0', 'INSTALL_EXIT': '0', 'RESTART_EXIT': '0',
            }
            # Run the literal copied one-liner, with only its tools replaced.
            for changed, expected in (
                    ({}, ['pull', 'install', 'restart']),
                    ({'PULL_EXIT': '1'}, ['pull']),
                    ({'INSTALL_EXIT': '1'}, ['pull', 'install']),
                    ({'RESTART_EXIT': '1'}, ['pull', 'install', 'restart']),
                    ({'PREFIX': 'cec-tv/'}, []),
                    ({'ROOT_EXIT': '1'}, []),
                    ({'BRANCH': 'feature'}, []),
                    ({'ORIGIN': 'https://github.com/someone/another.git'}, [])):
                with self.subTest(changed=changed):
                    if log.exists():
                        log.unlink()
                    # Preserve the copied shell quoting; only the outer bash is real.
                    result = subprocess.run(
                        ['/bin/sh', '-c', command.replace('bash -c ', '/usr/bin/bash -c ', 1)],
                        cwd=starting_directory, env={**environment, **changed},
                        input=str(checkout) + '\n', capture_output=True, text=True)
                    self.assertEqual(result.returncode == 0, not changed)
                    calls = log.read_text().splitlines() if log.exists() else []
                    self.assertEqual([line.split()[0] for line in calls], expected)
                    if calls:
                        self.assertEqual(calls[0], 'pull pull --ff-only origin main')
            for supplied in ('', '\n', 'relative/checkout\n', str(root / 'moved checkout') + '\n'):
                with self.subTest(path=supplied):
                    if log.exists():
                        log.unlink()
                    result = subprocess.run(
                        ['/bin/sh', '-c', command.replace('bash -c ', '/usr/bin/bash -c ', 1)],
                        cwd=starting_directory, env=environment, input=supplied,
                        capture_output=True, text=True)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertFalse(log.exists())
            fish = shutil.which('fish')
            if fish:
                subprocess.run([fish, '--no-execute', '-c', command], check=True,
                               capture_output=True, text=True)
                log.unlink(missing_ok=True)
                subprocess.run(
                    [fish, '-c', command.replace('bash -c ', '/usr/bin/bash -c ', 1)],
                    cwd=starting_directory, env=environment,
                    input=str(checkout) + '\n', capture_output=True, text=True, check=True)
                self.assertEqual([line.split()[0] for line in log.read_text().splitlines()],
                                 ['pull', 'install', 'restart'])

    def test_publication_metadata_and_scoped_build_ignores(self):
        ignores = (ROOT / '.gitignore').read_text().splitlines()
        for pattern in (
                '/repo/', '/repo-local/', '/dist/', '/builddir/',
                '/build-dir/', '/.flatpak-builder/', '/topcec-local.yml'):
            self.assertIn(pattern, ignores)
        snapshot = json.loads((ROOT / 'SNAPSHOT.json').read_text())
        self.assertEqual(len(snapshot['files']), 17)
        for record in snapshot['files']:
            self.assertFalse(record['source'].startswith('/home/'))
            self.assertRegex(record['sha256'], r'^[0-9a-f]{64}$')
        provenance = (ROOT / 'PROVENANCE.md').read_text()
        self.assertIn('Owner-provided origin statement', provenance)
        self.assertIn('no\nindependent authorship', provenance)
        self.assertIn('does not redact', provenance)

    def test_install_and_uninstall_are_scoped_and_preserve_config(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home = root / 'home'
            config_home = root / 'config'
            data_home = root / 'data'
            app_dir = home / '.local/share/topcec'
            bin_dir = home / '.local/bin'
            unit_dir = config_home / 'systemd/user'
            config_path = config_home / 'topcec/config.json'
            config_path.parent.mkdir(parents=True)
            config_path.write_text('user config\n', encoding='utf-8')
            unrelated_app = home / '.local/share/other-app'
            unrelated_app.mkdir(parents=True)
            (unrelated_app / 'keep').write_text('keep', encoding='utf-8')
            unrelated_bin = bin_dir / 'other-tool'
            unrelated_bin.parent.mkdir(parents=True)
            unrelated_bin.write_text('keep', encoding='utf-8')
            unrelated_unit = unit_dir / 'other.service'
            unrelated_unit.parent.mkdir(parents=True)
            unrelated_unit.write_text('[Unit]\n', encoding='utf-8')
            tools = root / 'tools'
            tools.mkdir()
            systemctl = tools / 'systemctl'
            systemctl.write_text(
                '#!/bin/sh\nprintf "%s\\n" "$*" >> "$TOPCEC_TEST_SYSTEMCTL_LOG"\n')
            systemctl.chmod(0o755)
            systemctl_log = root / 'systemctl.log'

            environment = {
                **os.environ,
                'HOME': str(home),
                'TOPCEC_HOME': str(home),
                'XDG_CONFIG_HOME': str(config_home),
                'XDG_DATA_HOME': str(data_home),
                'TOPCEC_SKIP_SYSTEMCTL': '0',
                'PATH': str(tools) + os.pathsep + os.environ['PATH'],
                'TOPCEC_TEST_SYSTEMCTL_LOG': str(systemctl_log),
                'TOPCEC_FIREFOX_NATIVE_DIR': str(root / 'mozilla/native-messaging-hosts'),
            }
            installation = subprocess.run(
                ['bash', str(ROOT / 'packaging/install-user.sh')],
                check=True, env=environment, capture_output=True, text=True)
            self.assertIn('daemon-reload does not reload its code', installation.stdout)
            self.assertIn('systemctl --user restart topcec.service', installation.stdout)
            self.assertEqual(systemctl_log.read_text(), '--user daemon-reload\n')

            for name in ('monitor.py', 'start.py', 'topcec_gui.py',
                         'activity.js', 'firefox.js', 'topcec.qml', 'equipment.py'):
                self.assertTrue((app_dir / 'cec-tv' / name).is_file())
            self.assertTrue(os.access(app_dir / 'cec-tv/start.py', os.X_OK))
            self.assertIn('%h/.local/share/topcec/cec-tv/start.py',
                          (unit_dir / 'topcec.service').read_text(encoding='utf-8'))
            self.assertTrue(os.access(bin_dir / 'topcec-gui', os.X_OK))
            icon_path = data_home / 'icons/hicolor/scalable/apps/net.local.topcec.svg'
            desktop_path = data_home / 'applications/net.local.topcec.desktop'
            self.assertEqual(icon_path.read_bytes(),
                             (ROOT / 'cec-tv/net.local.topcec.svg').read_bytes())
            self.assertIn('Icon=net.local.topcec', desktop_path.read_text())
            native_manifest = root / 'mozilla/native-messaging-hosts/net.local.topcec.media.json'
            self.assertTrue(native_manifest.is_file())
            self.assertTrue((app_dir / 'firefox-extension/background.js').is_file())
            self.assertTrue((config_path).is_file())
            custom_file = app_dir / 'keep-user-file'
            custom_file.write_text('keep', encoding='utf-8')

            environment['TOPCEC_SKIP_SYSTEMCTL'] = '1'
            subprocess.run(
                ['bash', str(ROOT / 'packaging/uninstall-user.sh')],
                check=True, env=environment, capture_output=True, text=True)

            self.assertEqual(custom_file.read_text(encoding='utf-8'), 'keep')
            self.assertFalse((bin_dir / 'topcec-gui').exists())
            self.assertFalse((unit_dir / 'topcec.service').exists())
            self.assertFalse((app_dir / 'cec-tv/equipment.py').exists())
            self.assertFalse(icon_path.exists())
            self.assertFalse(desktop_path.exists())
            self.assertFalse(native_manifest.exists())
            self.assertEqual(config_path.read_text(encoding='utf-8'), 'user config\n')
            self.assertEqual((unrelated_app / 'keep').read_text(encoding='utf-8'), 'keep')
            self.assertEqual(unrelated_bin.read_text(encoding='utf-8'), 'keep')
            self.assertTrue(unrelated_unit.exists())

    def test_rpm_spec_limits_payload_to_gpl_topcec_files(self):
        spec = (ROOT / 'packaging/topcec.spec').read_text(encoding='utf-8')
        builder = (ROOT / 'packaging/build-rpm.sh').read_text(encoding='utf-8')
        self.assertIn('License:        GPL-3.0-or-later', spec)
        self.assertIn('%{_userunitdir}/topcec.service', spec)
        self.assertIn('%{_topcec_appdir}/cec-tv/monitor.py', spec)
        self.assertIn('%{_topcec_appdir}/cec-tv/equipment.py', spec)
        self.assertIn('equipment.py', builder)
        self.assertIn('%files gui', spec)
        self.assertIn('%{_datadir}/icons/hicolor/scalable/apps/net.local.topcec.svg', spec)
        self.assertIn('%{_datadir}/applications/net.local.topcec.desktop', spec)
        self.assertIn('net.local.topcec.svg', builder)
        self.assertIn('topcec.service', builder)
        self.assertNotIn('tests/original', builder)
        self.assertNotIn('legacy/', builder)
        self.assertNotIn('pip install', spec + builder)
        self.assertNotIn('Source1:', spec)
        self.assertIn('%license LICENSE', spec)
        self.assertIn('%{_topcec_appdir}/cec-tv/firefox-native-host.py', spec)
        self.assertIn('net.local.topcec.media.json', spec)
        self.assertIn('%{_prefix}/lib/mozilla/native-messaging-hosts', spec)
        self.assertNotIn('%{_datadir}/mozilla/native-messaging-hosts', spec)
        self.assertIn('topcec-%{version}.tar.gz', spec)
        self.assertIn('topcec-$VERSION.tar.gz', builder)
        self.assertIn('_sourcedir $WORK_DIR/SOURCES', builder)
        self.assertIn('completed without producing an RPM artifact', builder)
        for third_party_material in ('legacy/', 'tests/original/', 'site-packages'):
            self.assertNotIn(third_party_material, spec + builder)

    @unittest.skipIf(shutil.which('rpmbuild'), 'rpmbuild available; build path required')
    def test_rpm_builder_reports_missing_tool_without_installing(self):
        result = subprocess.run(
            ['bash', str(ROOT / 'packaging/build-rpm.sh')],
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 127)
        self.assertIn('rpmbuild is required', result.stderr)


if __name__ == '__main__':
    unittest.main(verbosity=2)
