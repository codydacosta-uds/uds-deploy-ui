"""Real OS-pipe tests for the output-only hook. No cluster or UDS invocation."""
# Standalone adaptation of Apache-2.0 regression tests; see NOTICE.
import json
import os
from pathlib import Path
import signal
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from uds_deploy.output import active_capture, capture_homes, output_home
from uds_deploy.native import open_files

RAW=b'stdout exact CRLF\r\n\xff\x00stderr exact CRLF\r\n'

class OutputTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.runtime=self.root/'runtime';self.jobs=[]
        self.addCleanup(self.finish)
    def finish(self):
        for proc,work in self.jobs:
            (work/'release').touch()
            try:proc.communicate(timeout=3)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid,signal.SIGKILL);proc.communicate()
    def start(self,code=0,helper=None,shell='/bin/bash',default_home=False):
        work=self.root/('job-'+str(len(self.jobs)));work.mkdir()
        fixture=work/'fixture-command'
        fixture.write_text('''#!{python}
import json,os,pathlib,signal,sys,time
root=pathlib.Path({work!r})
def interrupted(sig,frame):
 os.write(2,b'CLI interrupt cleanup\\n');sys.exit(128+sig)
signal.signal(signal.SIGINT,interrupted);signal.signal(signal.SIGTERM,interrupted)
(root/'identity.tmp').write_text(json.dumps(dict(pid=os.getpid(),args=sys.argv[1:],env=os.environ.get('OUTPUT_TEST_SENTINEL'))))
(root/'identity.tmp').replace(root/'identity.json')
os.write(1,b'stdout exact CRLF\\r\\n\\xff\\x00');os.write(2,b'stderr exact CRLF\\r\\n')
while not (root/'release').exists():time.sleep(.01)
sys.exit(int(sys.argv[1]))
'''.format(python=sys.executable,work=str(work)));fixture.chmod(0o700)
        env=dict(os.environ,UDS_DEPLOY_RUNTIME_DIR=str(self.runtime),OUTPUT_TEST_SENTINEL='unchanged-value')
        if default_home:
            env.pop('UDS_DEPLOY_RUNTIME_DIR',None);(work/'tmp').mkdir();env['TMPDIR']=str(work/'tmp')
        # This is the exact shell pattern used by the normal task. The helper
        # consumes stdin only; it never launches or owns the fixture command.
        status='${pipestatus[1]}' if Path(shell).name=='zsh' else '${PIPESTATUS[0]}'
        command='"$1" "$2" "arg with space" 2>&1 | ("$3" "$4" || cat); exit "'+status+'"'
        proc=subprocess.Popen([shell,'-c',command,'output-test',str(fixture),str(code),sys.executable,str(helper or ROOT/'src/uds_deploy/capture.py')],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
        self.jobs.append((proc,work))
        deadline=time.monotonic()+5
        while not (work/'identity.json').exists():
            if time.monotonic()>deadline:self.fail('Fixture did not start')
            time.sleep(.01)
        identity=json.loads((work/'identity.json').read_text())
        return proc,work,identity
    def capture(self,pid):
        deadline=time.monotonic()+5
        with patch.dict(os.environ,{'UDS_DEPLOY_RUNTIME_DIR':str(self.runtime)}):
            while time.monotonic()<deadline:
                found=active_capture(pid,open_files)
                if found and not found.get('pending'):return found
                time.sleep(.02)
        self.fail('Reader could not discover the live output-only tee')
    def test_generic_default_namespace(self):
        with patch.dict(os.environ,{'UDS_DEPLOY_RUNTIME_DIR':''}),patch('uds_deploy.output.tempfile.gettempdir',return_value=str(self.root)):
            current=self.root/('uds-watch-output-'+str(os.getuid()))
            self.assertEqual(output_home(),current)
            self.assertEqual(capture_homes(),[current])

    def test_explicit_helpers_default_namespace(self):
        # Isolated fixtures use real OS pipes; no SDK/deployment.
        for name in ('task/scripts/deploy-output.py','standalone/uds_deploy/capture.py'):
            helper=self.root/name
            helper.parent.mkdir(parents=True,exist_ok=True)
            helper.write_text('import signal,sys\nsys.path.insert(0,'+repr(str(ROOT/'src'))+')\nfrom uds_deploy import output\nsignal.signal(signal.SIGINT,signal.SIG_IGN)\nsignal.signal(signal.SIGTERM,signal.SIG_IGN)\nraise SystemExit(output.copy_output(sys.stdin.buffer,sys.stdout.buffer))\n')
            for shell in ('bash','zsh'):
                binary=shutil.which(shell)
                if not binary:continue
                with self.subTest(helper=name,shell=shell):
                    proc,work,identity=self.start(7,helper,binary,default_home=True)
                    deadline=time.monotonic()+5;capture=None
                    with patch.dict(os.environ,{'UDS_DEPLOY_RUNTIME_DIR':''}),patch('uds_deploy.output.tempfile.gettempdir',return_value=str(work/'tmp')):
                        while time.monotonic()<deadline:
                            capture=active_capture(identity['pid'],open_files)
                            if capture and not capture.get('pending'):break
                            time.sleep(.02)
                    self.assertTrue(capture and not capture.get('pending'),'The configured capture namespace must be discoverable')
                    held=capture['path'].open('rb')
                    try:
                        (work/'release').touch();out,_=proc.communicate(timeout=5)
                        self.assertEqual(proc.returncode,7);self.assertEqual(out,RAW);self.assertEqual(held.read(),RAW)
                        self.assertFalse(capture['record'].exists())
                    finally:held.close()

    def test_insecure_capture_home_is_not_read(self):
        proc,work,identity=self.start();self.capture(identity['pid']);(self.runtime/'output').chmod(0o755)
        with patch.dict(os.environ,{'UDS_DEPLOY_RUNTIME_DIR':str(self.runtime)}):
            found=active_capture(identity['pid'],open_files)
        self.assertTrue(found is None or found.get('pending'),'An insecure directory must never yield a readable capture')
        (work/'release').touch();proc.communicate(timeout=5)

    def test_unrelated_helper_pipe_is_not_read(self):
        proc,work,identity=self.start();self.capture(identity['pid'])
        def wrong_pipe(pid):
            files=open_files(pid)
            if pid!=identity['pid']:
                files=[dict(row,inode='999999999999999999999',device='0x111',path='->0x222') if row.get('fd')=='0' else row for row in files]
            return files
        with patch.dict(os.environ,{'UDS_DEPLOY_RUNTIME_DIR':str(self.runtime)}):
            found=active_capture(identity['pid'],wrong_pipe)
        self.assertTrue(found is None or found.get('pending'),'A sibling helper must actually share the deployment output pipe')
        (work/'release').touch();proc.communicate(timeout=5)

    def test_explicit_runtime_does_not_search_other_namespaces(self):
        from uds_deploy.output import capture_homes
        with patch.dict(os.environ,{'UDS_DEPLOY_RUNTIME_DIR':str(self.runtime)}):
            self.assertEqual(capture_homes(),[self.runtime/'output'])

    def test_exact_bytes_environment_arguments_and_cli_exit(self):
        proc,work,identity=self.start(7);capture=self.capture(identity['pid'])
        self.assertEqual(identity['args'],['7','arg with space']);self.assertEqual(identity['env'],'unchanged-value')
        self.assertEqual(stat.S_IMODE(self.runtime.stat().st_mode),0o700,'The first tee must create a runtime directory the viewer accepts')
        self.assertEqual(stat.S_IMODE(capture['path'].stat().st_mode),0o600)
        self.assertEqual(stat.S_IMODE(capture['path'].parent.stat().st_mode),0o700)
        held=capture['path'].open('rb')
        try:
            (work/'release').touch();out,err=proc.communicate(timeout=5)
            self.assertEqual(proc.returncode,7);self.assertEqual(out,RAW)
            self.assertNotIn(b'capture unavailable',err)
            self.assertEqual(held.read(),RAW,'An attached reader retains exact output through task cleanup')
            self.assertFalse(capture['record'].exists());self.assertFalse(capture['path'].exists())
        finally:held.close()
    def test_closing_reader_does_not_stop_command(self):
        proc,work,identity=self.start();capture=self.capture(identity['pid'])
        with capture['path'].open('rb') as reader:reader.read(1)
        time.sleep(.1);self.assertIsNone(proc.poll())
        (work/'release').touch();out,_=proc.communicate(timeout=5)
        self.assertEqual(proc.returncode,0);self.assertEqual(out,RAW)
    def test_capture_failure_preserves_console_and_exit(self):
        (self.runtime/'output').mkdir(parents=True,mode=0o755)
        (self.runtime/'output').chmod(0o755)
        proc,work,_=self.start(7);(work/'release').touch();out,err=proc.communicate(timeout=5)
        self.assertEqual(proc.returncode,7);self.assertEqual(out,RAW);self.assertIn(b'capture unavailable',err)
    def test_missing_helper_falls_back_to_console_without_changing_exit(self):
        proc,work,_=self.start(7,self.root/'missing-helper.py');(work/'release').touch();out,_=proc.communicate(timeout=5)
        self.assertEqual(proc.returncode,7);self.assertEqual(out,RAW)
    def test_ctrl_c_preserves_cli_interrupt_cleanup_and_status(self):
        proc,work,identity=self.start();capture=self.capture(identity['pid'])
        os.killpg(proc.pid,signal.SIGINT);out,_=proc.communicate(timeout=5)
        self.assertEqual(proc.returncode,130);self.assertEqual(out,RAW+b'CLI interrupt cleanup\n')
        self.assertFalse(capture['record'].exists())

if __name__=='__main__':unittest.main()
