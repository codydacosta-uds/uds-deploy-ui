"""Only newly allocated test PTYs and explicitly owned fixture processes."""
import errno
import fcntl
import os
import pty
import select
import shutil
import signal
import struct
import subprocess
import sys
import termios
import time
import unittest

import test_entrypoints as fixtures
from uds_deploy import entrypoints


@unittest.skipUnless(shutil.which('cc') and shutil.which('lsof'),'Native terminal fixture prerequisites')
class TerminalRegistrationTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.EntrypointTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.root=self.fixture.root;self.native=self.fixture.native;self.env=self.fixture.env

    def test_prompt_input_terminal_size_bytes_and_native_failure_match(self):
        def run():
            master,slave=pty.openpty();process=None;output=bytearray();answered=False
            fcntl.ioctl(slave,termios.TIOCSWINSZ,struct.pack('HHHH',32,100,0,0))
            try:
                process=subprocess.Popen([str(self.native),'deploy','fixture','--tty','--window','--input','--fail'],stdin=slave,stdout=slave,stderr=slave,cwd=self.root,env=self.env,start_new_session=True)
                os.close(slave);slave=None;deadline=time.monotonic()+5
                while True:
                    self.assertLess(time.monotonic(),deadline)
                    if not select.select([master],[],[],.1)[0]:continue
                    try:data=os.read(master,4096)
                    except OSError as error:
                        if error.errno==errno.EIO:break
                        raise
                    if not data:break
                    output.extend(data)
                    if not answered and b'stderr' in output:os.write(master,b'answer from owned terminal\n\x04');answered=True
                self.assertEqual(process.wait(timeout=3),7)
                self.assertIn(b'tty=111',output);self.assertIn(b'window=32x100',output)
                self.assertIn(b'answer from owned terminal',output)
                return output
            finally:
                if process is not None and process.poll() is None:os.killpg(process.pid,signal.SIGKILL);process.wait(timeout=3)
                if slave is not None:os.close(slave)
                os.close(master)
        original=run();entrypoints.register(self.native);self.assertEqual(run(),original)

    def test_bash_and_zsh_foreground_stop_resume_and_exit_status(self):
        if os.environ.get('UDS_OWNED_TERMINAL_CHILD')!='1':
            # forkpty must run from a single-threaded interpreter, including
            # when HTTP-server tests left cleanup threads in the suite runner.
            result=subprocess.run([sys.executable,__file__,'TerminalRegistrationTests.test_bash_and_zsh_foreground_stop_resume_and_exit_status'],capture_output=True,text=True,timeout=35,env=dict(os.environ,UDS_OWNED_TERMINAL_CHILD='1'))
            self.assertEqual(result.returncode,0,result.stdout+result.stderr);return
        entrypoints.register(self.native)
        for shell in ('bash','zsh'):
            binary=shutil.which(shell)
            if not binary:continue
            with self.subTest(shell=shell):
                marker=self.root/('job-'+shell);pid,master=pty.fork();native_pid=None
                if pid==0:
                    os.chdir(self.root)
                    args=[binary,'--noprofile','--norc','-i'] if shell=='bash' else [binary,'-f','-i']
                    os.execve(binary,args,dict(self.env,PS1='OWNED_PROMPT> ',PROMPT='OWNED_PROMPT> '))
                output=bytearray()
                def until(needle):
                    deadline=time.monotonic()+8
                    while needle not in output:
                        self.assertLess(time.monotonic(),deadline,bytes(output))
                        if select.select([master],[],[],.1)[0]:output.extend(os.read(master,4096))
                try:
                    until(b'OWNED_PROMPT> ')
                    command='"'+str(self.native)+'" deploy fixture --wait "'+str(marker)+'"\n'
                    os.write(master,command.encode());deadline=time.monotonic()+5
                    while not marker.exists():
                        if select.select([master],[],[],.02)[0]:output.extend(os.read(master,4096))
                        self.assertLess(time.monotonic(),deadline,bytes(output))
                    native_pid=int(marker.read_text());self.assertEqual(os.getpgid(native_pid),native_pid)
                    output.clear();os.write(master,b'\x1a')
                    deadline=time.monotonic()+5
                    while True:
                        state=subprocess.check_output(['ps','-p',str(native_pid),'-o','stat=']).decode().strip()
                        if 'T' in state:break
                        self.assertLess(time.monotonic(),deadline);time.sleep(.02)
                    until(b'OWNED_PROMPT> ');output.clear();os.write(master,b'fg; printf "NATIVE_RESULT=%s\\n" "$?"\n')
                    # Resuming the shell job must resume native and its output
                    # forwarder together, without sending duplicate interrupts.
                    time.sleep(.1);marker.with_name(marker.name+'.release').touch()
                    until(b'NATIVE_RESULT=0');os.write(master,b'exit\n')
                    deadline=time.monotonic()+2
                    while time.monotonic()<deadline:
                        if os.waitpid(pid,os.WNOHANG)[0]:pid=None;break
                        if select.select([master],[],[],.05)[0]:
                            try:os.read(master,4096)
                            except OSError:pass
                finally:
                    marker.with_name(marker.name+'.release').touch()
                    if native_pid is not None:
                        try:os.killpg(native_pid,signal.SIGCONT)
                        except ProcessLookupError:pass
                    if pid is not None:
                        try:os.kill(pid,signal.SIGKILL)
                        except ProcessLookupError:pass
                        os.waitpid(pid,0)
                    os.close(master)


if __name__=='__main__':unittest.main()
