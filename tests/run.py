"""Run preserved tests against this snapshot, with hardware/process access blocked."""
# SPDX-License-Identifier: GPL-3.0-or-later
import pathlib
import runpy
import sys
import unittest.mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / 'cec-tv'))
mode = sys.argv[1] if len(sys.argv) > 1 else 'self-test'

def guard(event, args):
    if event in ('subprocess.Popen', 'os.system', 'os.posix_spawn', 'os.exec', 'os.fork', 'socket.connect', 'os.kill', 'os.killpg'):
        raise RuntimeError('Hardware-free test blocked: ' + event)
    if event == 'open' and isinstance(args[0], (str, bytes)):
        path = str(args[0])
        if path.startswith(('/dev/', '/sys/', '/proc/')):
            raise RuntimeError('Hardware-free test blocked file access: ' + path)

if mode not in ('packaging', 'firefox-media'):
    sys.addaudithook(guard)
sys.argv = [str(ROOT / 'cec-tv/monitor.py'), '--self-test']
if mode == 'self-test':
    runpy.run_path(str(ROOT / 'cec-tv/monitor.py'), run_name='__main__')
elif mode == 'cec-power':
    path = ROOT / 'tests/test_cec_power.py'
    sys.argv = [str(path)]
    runpy.run_path(str(path), run_name='__main__')
elif mode == 'activity-policy':
    path = ROOT / 'tests/test_activity_policy.py'
    sys.argv = [str(path)]
    runpy.run_path(str(path), run_name='__main__')
elif mode == 'cec-power-state':
    path = ROOT / 'tests/test_cec_power_state.py'
    sys.argv = [str(path)]
    runpy.run_path(str(path), run_name='__main__')
elif mode == 'providers':
    path = ROOT / 'tests/test_providers.py'
    sys.argv = [str(path)]
    runpy.run_path(str(path), run_name='__main__')
elif mode == 'firefox-media':
    path = ROOT / 'tests/test_firefox_media.py'
    sys.argv = [str(path)]
    runpy.run_path(str(path), run_name='__main__')
elif mode == 'configuration':
    path = ROOT / 'tests/test_configuration.py'
    sys.argv = [str(path)]
    runpy.run_path(str(path), run_name='__main__')
elif mode == 'gui':
    path = ROOT / 'tests/test_gui.py'
    sys.argv = [str(path)]
    runpy.run_path(str(path), run_name='__main__')
elif mode == 'license':
    path = ROOT / 'tests/test_licensing.py'
    sys.argv = [str(path)]
    runpy.run_path(str(path), run_name='__main__')
elif mode == 'packaging':
    path = ROOT / 'tests/test_packaging.py'
    sys.argv = [str(path)]
    runpy.run_path(str(path), run_name='__main__')
else:
    path = ROOT / 'tests/original' / mode
    source = path.read_text()
    for old in ('/tmp/cec-activity-monitor-live.py', '/home/arthur/.local/share/cec-tv/monitor.py', 'work/monitor.fixed.py'):
        source = source.replace(old, str(ROOT / 'cec-tv/monitor.py'))
    legacy_wake_scenarios = {
        'test_cec_live.py': (
            "p.request('off'); p.poll(); children[2].done=True",
            "p.request('off'); p.poll(); p.activity(); children[2].done=True"),
        'check_fixed.py': (
            'self.off();self.jobs[0].finish(ok=False);self.power.poll()',
            'self.off();self.activity();self.jobs[0].finish(ok=False);self.power.poll()'),
        'check_cec.py': (
            'self.off();self.jobs[0].finish(ok=False);self.power.poll()',
            'self.off();self.activity();self.jobs[0].finish(ok=False);self.power.poll()'),
    }
    if mode in legacy_wake_scenarios:
        old, new = legacy_wake_scenarios[mode]
        if old not in source:
            raise RuntimeError('Expected legacy CEC wake scenario was not found')
        source = source.replace(old, new)
    if mode in ('check_fixed.py', 'check_cec.py'):
        source = source.replace(
            "ns={'__file__':",
            "from activity_policy import ActivityPolicy\n"
            "from cec_power_state import CecPowerStateMachine\n"
            "ns={'ActivityPolicy':ActivityPolicy,"
            "'CecPowerStateMachine':CecPowerStateMachine,'__file__':")
    source = source.replace("Path('outputs/cec-tv')", 'Path(' + repr(str(ROOT / 'cec-tv')) + ')')
    sys.argv = [str(path)]
    import types
    module = types.ModuleType('__main__')
    module.__file__ = str(path)
    sys.modules['__main__'] = module
    exec(compile(source, str(path), 'exec'), module.__dict__)
