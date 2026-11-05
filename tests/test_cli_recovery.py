"""Exercise the actual script entry point, not just imported scout classes."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]

class CLIRecoveryTests(unittest.TestCase):
    def run_cli(self,scenario,once=False,saved=False):
        with tempfile.TemporaryDirectory() as tmp:
            c=json.loads((ROOT/'config.json').read_text())
            c.update(email_enabled=False,paper_requests_per_cycle=2)
            Path(tmp,'config.json').write_text(json.dumps(c))
            if saved:
                Path(tmp,'request-state.json').write_text(json.dumps(dict(next_allowed=4600,blocked_until=4600,interval=60)))
            script=r'''
import io,json,os,runpy,sys,time,urllib.error,urllib.request
from pathlib import Path
sys.path.insert(0,sys.argv[1])
root,scenario,once=sys.argv[1:]
import request_policy
clock=[1000.0]
time.time=lambda:clock[0]
time.monotonic=lambda:clock[0]
def sleep(seconds):clock[0]+=seconds
time.sleep=sleep
calls=[]
class Opener:
    def open(self,req,timeout=None):
        calls.append(clock[0])
        if scenario in ('429','401','403','once429') and len(calls)==1:
            code=429 if '429' in scenario else int(scenario)
            raise urllib.error.HTTPError(req.full_url,code,'mock',{'Retry-After':'7200'},None)
        if scenario!='budget':raise KeyboardInterrupt()
        row=dict(id='1',price=1,item={})
        return io.StringIO(json.dumps(dict(data=[dict(row,id=str(i)) for i in range(50)],cursor='next')))
urllib.request.build_opener=lambda *args:Opener()
os.environ['CSFLOAT_API_KEY']='offline-placeholder'
sys.argv=[str(Path(root,'scout.py'))]+(['--once'] if once=='yes' else [])
try:runpy.run_path(sys.argv[0],run_name='__main__')
except SystemExit:pass
finally:Path('calls.json').write_text(json.dumps(calls))
'''
            run=subprocess.run([sys.executable,'-c',script,str(ROOT),scenario,'yes' if once else 'no'],cwd=tmp,text=True,capture_output=True,timeout=15)
            self.assertEqual(run.returncode,0,run.stderr)
            calls=json.loads(Path(tmp,'calls.json').read_text())
            status=json.loads(Path(tmp,'status.json').read_text()) if Path(tmp,'status.json').exists() else {}
            return run.stdout,calls,status

    def test_script_entry_point_enforces_budget_and_catches_shared_exception(self):
        output,calls,status=self.run_cli('budget',once=True)
        self.assertEqual(len(calls),2)
        self.assertEqual(status['api_requests'],2)
        self.assertEqual(status['request_budget_reached'],1)
        self.assertIn('API requests: 2/2',output)

    def test_continuous_paper_resumes_only_after_retry_after(self):
        output,calls,status=self.run_cli('429')
        self.assertEqual(len(calls),2)
        self.assertGreaterEqual(calls[1]-calls[0],7200)
        self.assertIn('Cooldown complete',output)
        self.assertEqual(status['process_state'],'waiting_rate_limit')

    def test_restart_honors_saved_cooldown_before_first_request(self):
        output,calls,status=self.run_cli('saved',saved=True)
        self.assertEqual(calls,[4600])
        self.assertIn('No API requests',output)

    def test_once_does_not_automatically_retry(self):
        _,calls,status=self.run_cli('once429',once=True)
        self.assertEqual(len(calls),1)
        self.assertEqual(status['process_state'],'stopped_access_or_rate_limit')

    def test_authentication_errors_do_not_resume(self):
        for code in ('401','403'):
            with self.subTest(code=code):
                _,calls,status=self.run_cli(code)
                self.assertEqual(len(calls),1)
                self.assertEqual(status['process_state'],'stopped_access_or_rate_limit')

    def test_stop_file_interrupts_saved_cooldown(self):
        from unittest.mock import patch
        from request_policy import Policy
        from scout import Stop
        policy=Policy(None,30);policy.state['blocked_until']=10**15
        with patch('request_policy.Path.exists',return_value=True):
            with self.assertRaisesRegex(Stop,'STOP file'):policy.await_cooldown(Stop)
