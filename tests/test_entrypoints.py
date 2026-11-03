"""Isolated native C fixture conformance. No application or cluster deployment."""
import hashlib
import os
from pathlib import Path
import pty
import select
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from uds_deploy import entrypoints
from uds_deploy.native import open_files
from uds_deploy.output import active_capture

C=r'''
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <signal.h>
#include <limits.h>
#include <sys/ioctl.h>
extern char **environ;
void interrupted(int sig){write(2,"native interrupt cleanup\n",25);_exit(128+sig);}
int main(int argc,char **argv){
 signal(SIGINT,interrupted);signal(SIGQUIT,interrupted);
 int code=0,probe=0,input=0,tty=0,bulk=0,window=0;char *wait=NULL;
 for(int i=1;i<argc;i++){
  if(!strcmp(argv[i],"--fail"))code=7;
  if(!strcmp(argv[i],"--probe"))probe=1;
  if(!strcmp(argv[i],"--input"))input=1;
  if(!strcmp(argv[i],"--tty"))tty=1;
  if(!strcmp(argv[i],"--bulk"))bulk=1;
  if(!strcmp(argv[i],"--window"))window=1;
  if(!strcmp(argv[i],"--wait")&&i+1<argc)wait=argv[++i];
 }
 if(probe){char cwd[PATH_MAX];getcwd(cwd,sizeof(cwd));write(1,cwd,strlen(cwd)+1);
  for(int i=0;i<argc;i++)write(1,argv[i],strlen(argv[i])+1);
  for(char **e=environ;*e;e++)write(1,*e,strlen(*e)+1);
 }
 if(tty)dprintf(1,"tty=%d%d%d\n",isatty(0),isatty(1),isatty(2));
 if(window){struct winsize w;if(!ioctl(1,TIOCGWINSZ,&w))dprintf(1,"window=%dx%d\n",w.ws_row,w.ws_col);}
 write(1,"stdout\r\n\xff\x00",10);write(2,"stderr\r\n",8);
 if(input){char data[128];ssize_t n;while((n=read(0,data,sizeof(data)))>0)write(1,data,n);}
 if(wait){char ready[PATH_MAX];snprintf(ready,sizeof(ready),"%s.tmp",wait);FILE *f=fopen(ready,"w");fprintf(f,"%ld",(long)getpid());fclose(f);rename(ready,wait);char release[PATH_MAX];snprintf(release,sizeof(release),"%s.release",wait);while(access(release,F_OK))usleep(10000);if(bulk){char block[4096];memset(block,'x',sizeof(block));for(int i=0;i<256;i++)write(1,block,sizeof(block));}write(1,"native finished\\n",16);}
 return code;
}
'''


@unittest.skipUnless(shutil.which('cc'),'Native fixture requires a development C compiler')
class EntrypointTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='uds entrypoint ');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.native=self.root/'uds';source=self.root/'fixture.c';source.write_text(C)
        if os.environ.get('UDS_BOOTSTRAP_TEST_BINARY'):
            override=patch.object(entrypoints,'bootstrap_binary',return_value=Path(os.environ['UDS_BOOTSTRAP_TEST_BINARY']))
            override.start();self.addCleanup(override.stop)
        subprocess.run(['cc',str(source),'-o',str(self.native)],check=True,capture_output=True)
        self.env={'PATH':os.environ['PATH'],'HOME':str(self.root),'LANG':'C','BASH_ENV':'/not-executed-fixture','SHELLOPTS':'braceexpand:hashall:interactive-comments','BASH_FUNC_fixture%%':'() { printf fixture; }','UDS_DEPLOY_RUNTIME_DIR':str(self.root/'runtime'),'BUSINESS_CANARY':'unchanged fixture'}
    def test_exact_native_arguments_environment_cwd_input_streams_and_status(self):
        for arguments in (['version','--probe'],['deploy','bundle with spaces.tar.zst','--probe','--input','--fail']):
            before=subprocess.run([str(self.native)]+arguments,cwd=self.root,env=self.env,input=b'input\x00\xff\r\n',capture_output=True)
            original=self.native.read_bytes();registration=entrypoints.register(self.native)
            try:
                after=subprocess.run([str(self.native)]+arguments,cwd=self.root,env=self.env,input=b'input\x00\xff\r\n',capture_output=True,timeout=10)
                self.assertEqual(after.returncode,before.returncode)
                self.assertEqual(after.stdout,before.stdout,'Native argv/environment/stdin/cwd/output must be unchanged')
                self.assertEqual(after.stderr,before.stderr)
                self.assertEqual(Path(registration['native']).read_bytes(),original)
            finally:entrypoints.unregister(self.native)
            self.assertEqual(self.native.read_bytes(),original)
    def test_live_registered_capture_and_ctrl_c(self):
        entrypoints.register(self.native);marker=self.root/'ready'
        process=subprocess.Popen([str(self.native),'deploy','fixture.tar.zst','--wait',str(marker)],cwd=self.root,env=self.env,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,start_new_session=True)
        try:
            deadline=time.monotonic()+5
            while not marker.exists():
                self.assertIsNone(process.poll());self.assertLess(time.monotonic(),deadline);time.sleep(.02)
            pid=int(marker.read_text());self.assertEqual(pid,process.pid,'The original command PID must exec native UDS, not supervise a child')
            with patch.dict(os.environ,self.env,clear=True):
                capture=active_capture(pid,open_files)
                self.assertTrue(capture and capture.get('registered_stdio'))
            held=capture['path'].open('rb')
            try:
                os.killpg(process.pid,signal.SIGINT);out,_=process.communicate(timeout=5)
                self.assertEqual(process.returncode,130);self.assertIn(b'native interrupt cleanup',out)
                self.assertEqual(held.read(),out);self.assertFalse(capture['record'].exists())
            finally:held.close()
        finally:
            Path(str(marker)+'.release').touch()
            if process.poll() is None:process.communicate(timeout=5)
    def test_capture_worker_failure_does_not_stop_or_change_native_result(self):
        entrypoints.register(self.native);marker=self.root/'ready'
        process=subprocess.Popen([str(self.native),'deploy','fixture.tar.zst','--fail','--wait',str(marker)],cwd=self.root,env=self.env,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,start_new_session=True)
        try:
            deadline=time.monotonic()+5
            while not marker.exists():self.assertIsNone(process.poll());self.assertLess(time.monotonic(),deadline);time.sleep(.02)
            with patch.dict(os.environ,self.env,clear=True):capture=active_capture(process.pid,open_files)
            self.assertTrue(capture and capture.get('registered_stdio'))
            os.kill(capture['pid'],signal.SIGKILL)  # Only this test-owned capture child.
            while capture['record'].exists():self.assertLess(time.monotonic(),deadline);time.sleep(.02)
            self.assertIsNone(process.poll(),'Capture failure must not cancel native execution')
            Path(str(marker)+'.release').touch();out,_=process.communicate(timeout=5)
            self.assertEqual(process.returncode,7);self.assertIn(b'native finished',out,'Native output must continue through the independent passthrough fallback')
        finally:
            Path(str(marker)+'.release').touch()
            if process.poll() is None:process.communicate(timeout=5)

    def test_capture_worker_failure_while_output_is_backpressured_preserves_every_byte(self):
        entrypoints.register(self.native);marker=self.root/'bulk-ready'
        process=subprocess.Popen([str(self.native),'deploy','fixture.tar.zst','--bulk','--wait',str(marker)],cwd=self.root,env=self.env,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,start_new_session=True)
        try:
            deadline=time.monotonic()+5
            while not marker.exists():self.assertLess(time.monotonic(),deadline);time.sleep(.02)
            with patch.dict(os.environ,self.env,clear=True):capture=active_capture(process.pid,open_files)
            self.assertTrue(capture and capture.get('registered_stdio'))
            Path(str(marker)+'.release').touch()
            # Intentionally leave this test-owned stdout pipe unread so the
            # relay holds a partially forwarded chunk. No existing TTY/pipe.
            import array,fcntl,termios
            available=array.array('i',[0])
            while available[0]<=18:
                fcntl.ioctl(process.stdout.fileno(),termios.FIONREAD,available,True)
                self.assertLess(time.monotonic(),deadline);time.sleep(.02)
            time.sleep(.1)
            self.assertIsNone(process.poll())
            os.kill(capture['pid'],signal.SIGKILL)
            output,_=process.communicate(timeout=5)
            self.assertEqual(process.returncode,0)
            self.assertEqual(output.count(b'x'),1048576,'Capture failure must not lose native output already consumed by the relay')
        finally:
            Path(str(marker)+'.release').touch()
            if process.poll() is None:process.communicate(timeout=5)

    def test_paused_capture_cannot_block_native_output_or_certify_completion(self):
        entrypoints.register(self.native);marker=self.root/'paused-ready'
        process=subprocess.Popen([str(self.native),'deploy','fixture.tar.zst','--bulk','--wait',str(marker)],cwd=self.root,env=self.env,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,start_new_session=True)
        try:
            deadline=time.monotonic()+5
            while not marker.exists():self.assertLess(time.monotonic(),deadline);time.sleep(.02)
            with patch.dict(os.environ,self.env,clear=True):capture=active_capture(process.pid,open_files)
            self.assertTrue(capture and capture.get('registered_stdio'))
            with capture['integrity'].open('rb',buffering=0) as integrity:
                os.kill(capture['pid'],signal.SIGSTOP)  # Only this fixture's capture child.
                Path(str(marker)+'.release').touch()
                output,_=process.communicate(timeout=5)
                self.assertEqual(process.returncode,0)
                self.assertEqual(output.count(b'x'),1048576)
                self.assertEqual(integrity.read(),b'!','An interrupted capture must never certify complete output')
        finally:
            Path(str(marker)+'.release').touch()
            if process.poll() is None:process.communicate(timeout=5)

    def test_native_targeted_termination_keeps_original_pid_and_status(self):
        entrypoints.register(self.native)
        for sig in (signal.SIGTERM,signal.SIGKILL):
            marker=self.root/('ready-'+str(sig))
            process=subprocess.Popen([str(self.native),'deploy','fixture.tar.zst','--wait',str(marker)],cwd=self.root,env=self.env,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,start_new_session=True)
            try:
                deadline=time.monotonic()+5
                while not marker.exists():self.assertIsNone(process.poll());self.assertLess(time.monotonic(),deadline);time.sleep(.02)
                self.assertEqual(int(marker.read_text()),process.pid)
                os.kill(process.pid,sig)  # This test's native fixture, never a deployment.
                process.communicate(timeout=5);self.assertEqual(process.returncode,-sig)
            finally:
                Path(str(marker)+'.release').touch()
                if process.poll() is None:process.communicate(timeout=5)

    def test_owned_test_terminal_flags_and_output(self):
        def run():
            master,slave=pty.openpty()
            try:
                process=subprocess.Popen([str(self.native),'deploy','fixture.tar.zst','--tty'],stdin=subprocess.DEVNULL,stdout=slave,stderr=slave,env=self.env,cwd=self.root);os.close(slave);slave=None;chunks=[]
                while True:
                    try:chunk=os.read(master,4096)
                    except OSError:break
                    if not chunk:break
                    chunks.append(chunk)
                self.assertEqual(process.wait(timeout=5),0);return b''.join(chunks)
            finally:
                os.close(master)
                if slave is not None:os.close(slave)
        before=run();entrypoints.register(self.native);self.assertEqual(run(),before,'Only test-owned PTYs: preserve native isatty flags and terminal bytes')
    def test_capture_failure_and_missing_package_fail_open(self):
        before=subprocess.run([str(self.native),'deploy','fixture','--fail'],env=self.env,capture_output=True)
        entrypoints.register(self.native)
        (self.root/'runtime/output').mkdir(parents=True);(self.root/'runtime/output').chmod(0o755)
        after=subprocess.run([str(self.native),'deploy','fixture','--fail'],env=self.env,capture_output=True,timeout=5)
        self.assertEqual((after.returncode,after.stdout,after.stderr),(before.returncode,before.stdout,before.stderr))
    def test_symlinks_hardlinks_scripts_and_edited_launchers_refused(self):
        alias=self.root/'alias';alias.symlink_to(self.native)
        with self.assertRaises(ValueError):entrypoints.register(alias)
        alias.unlink();os.link(self.native,alias)
        with self.assertRaises(ValueError):entrypoints.register(self.native)
        alias.unlink();entrypoints.register(self.native)
        with self.native.open('ab') as stream:stream.write(b'# user change\n')
        with self.assertRaises(ValueError):entrypoints.unregister(self.native)


if __name__=='__main__':unittest.main()
