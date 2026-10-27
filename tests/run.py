"""Run preserved tests against this snapshot, with hardware/process access blocked."""
import pathlib
import runpy
import sys
import unittest.mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True

def guard(event, args):
    if event in ('subprocess.Popen', 'os.system', 'os.posix_spawn', 'os.exec', 'os.fork', 'socket.connect', 'os.kill', 'os.killpg'):
        raise RuntimeError('Hardware-free test blocked: ' + event)
    if event == 'open' and isinstance(args[0], (str, bytes)):
        path = str(args[0])
        if path.startswith(('/dev/', '/sys/', '/proc/')):
            raise RuntimeError('Hardware-free test blocked file access: ' + path)

sys.addaudithook(guard)
mode = sys.argv[1] if len(sys.argv) > 1 else 'self-test'
sys.argv = [str(ROOT / 'cec-tv/monitor.py'), '--self-test']
if mode == 'self-test':
    runpy.run_path(str(ROOT / 'cec-tv/monitor.py'), run_name='__main__')
else:
    path = ROOT / 'tests/original' / mode
    source = path.read_text()
    for old in ('/tmp/cec-activity-monitor-live.py', '/home/arthur/.local/share/cec-tv/monitor.py', 'work/monitor.fixed.py'):
        source = source.replace(old, str(ROOT / 'cec-tv/monitor.py'))
    source = source.replace("Path('outputs/cec-tv')", 'Path(' + repr(str(ROOT / 'cec-tv')) + ')')
    sys.argv = [str(path)]
    import types
    module = types.ModuleType('__main__')
    module.__file__ = str(path)
    sys.modules['__main__'] = module
    exec(compile(source, str(path), 'exec'), module.__dict__)
