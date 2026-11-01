import importlib.util
import json
from unittest.mock import patch
from pathlib import Path

def module(name,path):
 s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
base=Path('outputs/cec-tv')
k=module('settings',base/'cec-kde-settings.py')
m=module('monitor',base/'monitor.py')
assert k.parse('true','600')==600
assert k.parse('false','600') is None
assert k.parse('true','-1') is None
try:k.parse('oops','600');raise AssertionError()
except ValueError:pass
class Child:
 returncode=0
 def __init__(self,value): self.value=value
 def poll(self):return 0
 def communicate(self):return json.dumps({'ok':True,'timeout':self.value}),''
c=m.KdeTimeout();t=m.Timer(0)
c.process=Child(600)
with patch.object(m.subprocess,'Popen',side_effect=AssertionError('unexpected spawn')):
 assert c.poll(t,10) is None and t.timeout==600 and t.last==10
 c.process=Child(None)
 assert c.poll(t,11) is None and t.timeout is None
 assert t.tick(10000) is None
 c.process=Child(300)
 assert c.poll(t,12) is None and t.timeout==300 and t.last==12
print('KDE settings checks passed: defaults, disabled, change while running')
for p in base.glob('*.py'):compile(p.read_text(),str(p),'exec')
