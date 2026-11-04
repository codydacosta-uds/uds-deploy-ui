"""Path-free shell setup tests: temporary homes and fake commands only."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.home=self.root/'home';self.home.mkdir()
        self.checkout=self.root/'checkout with spaces';self.checkout.mkdir()
        self.bin=self.root/'bin';self.bin.mkdir();self.cwd=self.root/'elsewhere';self.cwd.mkdir()
        self.zdot=self.home/'zsh';self.zdot.mkdir()
        self.files=[self.home/'.bashrc',self.home/'.profile',self.zdot/'.zshrc']
        for file in self.files:file.write_text('# existing configuration\n')
        for name in ('install.sh','uninstall.sh'):shutil.copy2(ROOT/name,self.checkout/name)
        watcher='''import json,os,sys
if sys.argv[1:]==['capture']:
    if os.environ.get('UDS_CAPTURE_FAIL'):sys.exit(1)
    with open(os.environ['CAPTURE_TRACE'],'a') as stream:stream.write('capture\\n')
    sys.stdout.buffer.write(sys.stdin.buffer.read());sys.exit(0)
print(json.dumps({'command':'watcher','args':sys.argv[1:]}))
sys.exit(int(os.environ.get('UDS_TEST_EXIT','0')))
'''
        native='''import json,os,signal,sys
print(json.dumps({'command':'native','args':sys.argv[1:]}),flush=True)
if os.environ.get('UDS_TEST_STDERR'):print('native stderr',file=sys.stderr,flush=True)
if os.environ.get('UDS_TEST_SIGNAL'):
    signal.signal(signal.SIGINT,signal.SIG_DFL);os.kill(os.getpid(),signal.SIGINT)
sys.exit(int(os.environ.get('UDS_TEST_EXIT','0')))
'''
        for path,body in [(self.checkout/'uds-watch',watcher),(self.bin/'uds',native)]:
            path.write_text('#!'+sys.executable+'\n'+body);path.chmod(0o755)
        self.env={key:value for key,value in os.environ.items() if key in ('PATH','TMPDIR','LANG','LC_ALL')}
        self.env.update(HOME=str(self.home),ZDOTDIR=str(self.zdot),PATH=str(self.bin)+os.pathsep+self.env.get('PATH',os.defpath),UDS_DEPLOY_RUNTIME_DIR=str(self.root/'runtime'),CAPTURE_TRACE=str(self.root/'capture-calls'))

    def setup_command(self,name,*args):
        return subprocess.run(['bash',str(self.checkout/name),*args],cwd=self.cwd,env=self.env,capture_output=True,text=True,timeout=10)

    def invoke(self,shell,args,code=0,**extra):
        env=dict(self.env,UDS_TEST_EXIT=str(code),**extra)
        if shell=='bash':command=[shutil.which(shell),'--noprofile','--norc','-c','. "$HOME/.bashrc"; uds "$@"','probe']
        else:command=[shutil.which(shell),'-dfc','. "$ZDOTDIR/.zshrc"; uds "$@"','probe']
        return subprocess.run(command+args,cwd=self.cwd,env=env,capture_output=True,text=True,timeout=10)

    def shells(self):return [shell for shell in ('bash','zsh') if shutil.which(shell)]

    def real_launcher(self):
        shutil.copy2(ROOT/'uds-watch',self.checkout/'uds-watch')
        (self.checkout/'src').symlink_to(ROOT/'src',target_is_directory=True)

    def test_install_is_path_free_idempotent_and_leaves_tasks_and_binary_alone(self):
        task=self.cwd/'tasks.yaml';task.write_text('tasks: []\n')
        before=hashlib.sha256((self.bin/'uds').read_bytes()).digest()
        result=self.setup_command('install.sh');self.assertEqual(result.returncode,0,result.stderr)
        launcher=self.home/'.local/bin/uds-watch';self.assertTrue(launcher.is_symlink())
        self.assertEqual(launcher.resolve(),(self.checkout/'uds-watch').resolve())
        installed={file:file.read_bytes() for file in self.files}
        self.assertEqual(self.setup_command('install.sh').returncode,0)
        for file,data in installed.items():
            self.assertEqual(file.read_bytes(),data);self.assertTrue(data.startswith(b'# existing configuration\n'))
            self.assertEqual(data.count(b'# >>> uds-watch shortcut >>>'),1)
        self.assertFalse((self.home/'.bash_profile').exists());self.assertEqual(task.read_text(),'tasks: []\n')
        self.assertEqual(hashlib.sha256((self.bin/'uds').read_bytes()).digest(),before)

    def test_bash_zsh_route_arguments_capture_deploy_and_preserve_exit_status(self):
        self.assertEqual(self.setup_command('install.sh').returncode,0)
        cases=[([],('native',[])),(['version'],('native',['version'])),(['deploy','a path',''],('native',['deploy','a path',''])),(['d','a path'],('native',['d','a path'])),(['watch'],('watcher',[])),(['watch','--port','0','a path',''],('watcher',['--port','0','a path','']))]
        for shell in self.shells():
            for args,expected in cases:
                for code in (0,7):
                    with self.subTest(shell=shell,args=args,code=code):
                        result=self.invoke(shell,args,code);self.assertEqual(result.returncode,code,result.stderr)
                        self.assertEqual(json.loads(result.stdout),dict(command=expected[0],args=expected[1]))
        self.assertEqual((self.root/'capture-calls').read_text().count('capture\n'),len(self.shells())*4)

    def test_real_launcher_and_capture_work_outside_the_checkout(self):
        self.real_launcher();self.assertEqual(self.setup_command('install.sh').returncode,0)
        for shell in self.shells():
            help_result=self.invoke(shell,['watch','--help']);self.assertEqual(help_result.returncode,0,help_result.stderr)
            self.assertIn('read-only UDS/Zarf deployment viewer',help_result.stdout)
            for code in (0,7):
                env=dict(self.env,UDS_TEST_EXIT=str(code),UDS_TEST_STDERR='1')
                expected=subprocess.run([str(self.bin/'uds'),'deploy','a path',''],env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
                result=self.invoke(shell,['deploy','a path',''],code,UDS_TEST_STDERR='1')
                self.assertEqual(result.returncode,code,result.stderr);self.assertEqual(result.stdout,expected.stdout)

    def test_capture_fallback_and_interrupt_preserve_native_result(self):
        self.assertEqual(self.setup_command('install.sh').returncode,0)
        for shell in self.shells():
            failed=self.invoke(shell,['deploy','a path'],7,UDS_CAPTURE_FAIL='1')
            self.assertEqual(failed.returncode,7);self.assertEqual(json.loads(failed.stdout)['command'],'native')
            interrupted=self.invoke(shell,['deploy','a path'],UDS_TEST_SIGNAL='1')
            self.assertEqual(interrupted.returncode,130,interrupted.stderr)

    def test_install_updates_its_old_shortcut_block_without_duplicates(self):
        self.assertEqual(self.setup_command('install.sh').returncode,0)
        rc=self.files[0];data=rc.read_text();start=data.index('# >>> uds-watch shortcut >>>');end=data.index('# <<< uds-watch shortcut <<<')
        rc.write_text(data[:start]+'# >>> uds-watch shortcut >>>\nuds() { command uds "$@"; }\n'+data[end:]+'# later user setting\n')
        self.assertEqual(self.setup_command('install.sh').returncode,0)
        updated=rc.read_text();self.assertEqual(updated.count('# >>> uds-watch shortcut >>>'),1)
        self.assertIn('"$HOME/.local/bin/uds-watch" capture',updated);self.assertTrue(updated.endswith('# later user setting\n'))

    def test_uninstall_restores_existing_files_and_is_idempotent(self):
        original={file:file.read_bytes() for file in self.files}
        self.assertEqual(self.setup_command('install.sh').returncode,0)
        self.assertEqual(self.setup_command('uninstall.sh').returncode,0)
        self.assertFalse((self.home/'.local/bin/uds-watch').is_symlink())
        self.assertEqual({file:file.read_bytes() for file in self.files},original)
        self.assertEqual(self.setup_command('uninstall.sh').returncode,0)
        self.assertEqual({file:file.read_bytes() for file in self.files},original)

    def test_uninstall_preserves_later_settings_and_replaced_launcher(self):
        self.assertEqual(self.setup_command('install.sh').returncode,0)
        with self.files[0].open('ab') as stream:stream.write(b'export KEEP_THIS=1\n')
        launcher=self.home/'.local/bin/uds-watch';launcher.unlink();launcher.write_bytes(b'user replacement\n')
        self.assertEqual(self.setup_command('uninstall.sh').returncode,0)
        self.assertEqual(self.files[0].read_bytes(),b'# existing configuration\nexport KEEP_THIS=1\n')
        self.assertEqual(launcher.read_bytes(),b'user replacement\n')

    def test_unrelated_launcher_and_path_arguments_are_rejected(self):
        self.assertNotEqual(self.setup_command('install.sh',str(self.cwd)).returncode,0)
        launcher=self.home/'.local/bin/uds-watch';launcher.parent.mkdir(parents=True);launcher.write_bytes(b'keep this executable\n')
        result=self.setup_command('install.sh');self.assertNotEqual(result.returncode,0);self.assertIn('Refusing to replace',result.stderr)
        self.assertEqual(launcher.read_bytes(),b'keep this executable\n')
        self.assertTrue(all(file.read_text()=='# existing configuration\n' for file in self.files))

    def test_created_startup_files_are_removed_without_touching_tasks(self):
        for file in self.files:file.unlink()
        self.env.pop('ZDOTDIR');task=self.cwd/'tasks.yaml';task.write_text('keep these tasks\n')
        self.assertEqual(self.setup_command('install.sh').returncode,0)
        self.assertEqual(self.setup_command('uninstall.sh').returncode,0)
        self.assertTrue(all(not (self.home/name).exists() for name in ('.bashrc','.bash_profile','.zshrc')))
        self.assertEqual(task.read_text(),'keep these tasks\n')


if __name__=='__main__':unittest.main()
