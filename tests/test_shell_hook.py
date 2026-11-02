"""Isolated shell/argv/byte regressions using a clearly synthetic CLI fixture."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]


class ShellHookTests(unittest.TestCase):
    def test_native_arguments_bytes_input_and_status_in_both_shells(self):
        for shell in ('bash','zsh'):
            executable=shutil.which(shell)
            if not executable:continue
            with self.subTest(shell=shell),tempfile.TemporaryDirectory(prefix='uds watch shell ') as directory:
                root=Path(directory);binary=root/'uds'
                binary.write_text('#!'+sys.executable+'\nimport sys,json\nsys.stdout.buffer.write(json.dumps(sys.argv[1:]).encode()+b"\\n\\xffstdout\\r\\n");sys.stdout.flush()\nsys.stderr.buffer.write(b"stderr\\r\\n");sys.stderr.flush()\nif "--input" in sys.argv:print(sys.stdin.readline().strip(),flush=True)\nsys.exit(7 if "--fail" in sys.argv else 0)\n');binary.chmod(0o755)
                env={key:value for key,value in os.environ.items() if key in ('PATH','HOME','TMPDIR','LANG')}
                env.update(PATH=str(root)+os.pathsep+env['PATH'],UDS_DEPLOY_RUNTIME_DIR=str(root/'runtime'))
                for arguments in (['deploy','bundle with spaces.tar.zst','--input'],['--log-level','info','deploy','bundle.tar.zst','--fail'],['version'],['--unknown-global','value','deploy','untouched']):
                    direct=subprocess.run([str(binary)]+arguments,input=b'interactive input\n',stdout=subprocess.PIPE,stderr=subprocess.STDOUT,env=env)
                    script='set -eu; '+('set -o pipefail; ' if shell=='bash' else 'setopt pipefail; ')
                    script+='eval "$("$1" shell-init --shell "$2")"; shift 2; uds "$@"'
                    hooked=subprocess.run([executable,'-c',script,'fixture',str(ROOT/'uds-watch'),shell]+arguments,input=b'interactive input\n',stdout=subprocess.PIPE,stderr=subprocess.STDOUT,env=env,timeout=10)
                    self.assertEqual(hooked.returncode,direct.returncode)
                    self.assertEqual(hooked.stdout,direct.stdout,'Preserve native argv, input, stdout/stderr bytes, CRLF and invalid UTF-8')
                    self.assertEqual(list((root/'runtime').rglob('capture.json')),[])
    def test_existing_functions_are_not_overwritten(self):
        for shell in ('bash','zsh'):
            executable=shutil.which(shell)
            if not executable:continue
            script='function uds(){ printf original; }; eval "$("$1" shell-init --shell "$2")"; uds'
            with tempfile.TemporaryDirectory() as directory:
                binary=Path(directory)/'uds';binary.write_text('#!/bin/sh\nexit 0\n');binary.chmod(0o755)
                env=dict(os.environ,PATH=directory+os.pathsep+os.environ['PATH'])
                result=subprocess.run([executable,'-c',script,'fixture',str(ROOT/'uds-watch'),shell],env=env,capture_output=True,timeout=10)
                self.assertEqual(result.returncode,0);self.assertEqual(result.stdout,b'original');self.assertIn(b'already an alias/function',result.stderr)
    def test_shell_detection_uses_the_actual_shell_not_login_shell(self):
        for shell in ('bash','zsh'):
            executable=shutil.which(shell)
            if not executable:continue
            with tempfile.TemporaryDirectory() as directory:
                binary=Path(directory)/'uds';binary.write_text('#!/bin/sh\nprintf detected\nexit 7\n');binary.chmod(0o755)
                env=dict(os.environ,PATH=directory+os.pathsep+os.environ['PATH'],SHELL='/bin/zsh' if shell=='bash' else '/bin/bash',UDS_DEPLOY_RUNTIME_DIR=str(Path(directory)/'runtime'))
                script='eval "$("$1" shell-init)"; uds deploy fixture.tar.zst'
                result=subprocess.run([executable,'-c',script,'fixture',str(ROOT/'uds-watch')],env=env,capture_output=True,timeout=10)
                self.assertEqual(result.returncode,7);self.assertEqual(result.stdout,b'detected')
    def test_help_and_no_config_rewrites(self):
        result=subprocess.run([str(ROOT/'uds-watch'),'--help'],capture_output=True,timeout=10)
        self.assertEqual(result.returncode,0);self.assertIn(b'shell-init',result.stdout)


if __name__=='__main__':unittest.main()
