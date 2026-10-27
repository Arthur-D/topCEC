import importlib.util
from unittest.mock import patch
from types import SimpleNamespace
spec=importlib.util.spec_from_file_location('live','/tmp/cec-activity-monitor-live.py')
m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
class Child:
 def __init__(self): self.done=False; self.returncode=0; self.result='{"ok":true,"state":"standby"}'
 def poll(self): return 0 if self.done else None
 def communicate(self): return self.result,''
children=[]
def spawn(*args,**kwargs):
 c=Child(); children.append(c); return c
with patch.object(m.subprocess,'Popen',spawn):
 p=m.CecPower('/dev/test'); p.request('off'); p.poll()
 assert len(children)==1 and p.sent=='off'
 p.request('on'); p.poll(); assert len(children)==1
 children[0].done=True; p.poll(); assert len(children)==2 and p.sent=='on'
 children[1].done=True; children[1].result='{"ok":true,"state":"on"}'; p.poll()
 assert not p.may_be_off
 p.request('off'); p.poll(); children[2].done=True; children[2].returncode=1
 children[2].result='{"ok":false,"error":"adapter failure"}'; p.poll()
 assert len(children)==4 and p.sent=='on' and p.fault
 p.request('off'); assert p.pending is None
print('CEC queue/error recovery checks passed without hardware commands')
