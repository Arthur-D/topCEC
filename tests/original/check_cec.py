import ast, pathlib, unittest, json
from unittest.mock import Mock
p=pathlib.Path('/home/arthur/.local/share/cec-tv/monitor.py')
tree=ast.parse(p.read_text())
ns={'__file__':str(p),'Path':pathlib.Path,'json':json,'sys':Mock(executable='python'),'time':Mock(),'subprocess':Mock(),'log':lambda x:None}
ns['time'].monotonic.return_value=1
exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n,ast.ClassDef) and n.name in ('CecPower','Timer')],type_ignores=[]),str(p),'exec'),dict(ns,TIMEOUT=60),ns)
class Process:
    def __init__(self): self.returncode=None
    def poll(self): return self.returncode
    def communicate(self): return self.output,''
    def finish(self,state='standby',ok=True):
        self.returncode=0 if ok else 1
        self.output=json.dumps({'ok':ok,'state':state,'error':'mock failure'})
class Checks(unittest.TestCase):
    def setUp(self):
        self.sent=[]; self.jobs=[]
        def spawn(args,**kw):
            self.sent.append(args[2]); job=Process();self.jobs.append(job);return job
        ns['subprocess'].Popen.side_effect=spawn
        self.power=ns['CecPower']('MOCK'); self.timer=ns['Timer'](0,600)
    def off(self):
        assert self.timer.tick(600)
        self.power.request('off');self.power.poll()
    def activity(self,t=601):
        if self.timer.activity(t): self.power.request('on')
    def test_off_activity_delayed_confirmation(self):
        self.off();self.activity()
        for t in range(602,620):
            self.power.poll();self.timer.tick(t,True)
        self.assertEqual(self.sent,['off']);self.assertEqual(self.power.pending,'on')
        self.jobs[0].finish();self.power.poll()
        self.assertEqual(self.sent,['off','on'])
    def test_failed_off_recovers_on(self):
        self.off();self.jobs[0].finish(ok=False);self.power.poll()
        self.assertEqual(self.sent,['off','on'])
    def test_fault_blocks_only_off(self):
        self.power.fault='fault';self.power.request('off');self.power.poll()
        self.assertEqual(self.sent,[])
        self.power.request('on');self.power.poll();self.assertEqual(self.sent,['on'])
    def test_rapid_activity_no_duplicate(self):
        self.off()
        for t in range(601,610):self.activity(t);self.power.poll()
        self.jobs[0].finish();self.power.poll()
        self.assertEqual(self.sent,['off','on'])
    def test_single_slot_last_request_wins(self):
        self.off()
        for action in ('on','off','on'): self.power.request(action)
        self.jobs[0].finish();self.power.poll();self.assertEqual(self.sent,['off','on'])
    def test_failed_on_following_activity_does_not_retry(self):
        self.off();self.activity();self.jobs[0].finish();self.power.poll()
        self.jobs[1].finish(ok=False);self.power.poll()
        for t in range(602,610):self.activity(t);self.power.poll();self.timer.tick(t,True)
        self.assertEqual(self.sent,['off','on']);self.assertIsNone(self.power.pending)
        self.assertFalse(self.timer.expired);self.assertTrue(self.power.may_be_off)
    def test_activity_before_off_dispatched_replaces_off(self):
        self.timer.tick(600);self.power.request('off');self.activity();self.power.poll()
        self.assertEqual(self.sent,['on'])
unittest.main(verbosity=2)
