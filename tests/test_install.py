"""Explicit installer tests: temporary homes and fake commands only."""
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
        (self.checkout/'scripts').mkdir();shutil.copy2(ROOT/'scripts/task-capture.py',self.checkout/'scripts/task-capture.py')
        self.project=self.root/'deployment repo';(self.project/'tasks').mkdir(parents=True)
        self.task=self.project/'tasks/swf.yaml'
        self.original_tasks='tasks:\n  - name: direct\n    actions:\n      - cmd: uds deploy bundle.tar.zst --confirm\n  - name: relative\n    actions:\n      - cmd: |\n          ./uds deploy bundle.tar.zst --confirm\n        shell:\n          linux: bash\n          darwin: bash\n'
        self.task.write_text(self.original_tasks)
        for path,label in [(self.checkout/'uds-watch','watcher'),(self.bin/'uds','native')]:
            path.write_text('#!'+sys.executable+'\nimport json,os,sys\nprint(json.dumps({"command":'+repr(label)+',"args":sys.argv[1:]}))\nsys.exit(int(os.environ.get("UDS_TEST_EXIT","0")))\n');path.chmod(0o755)
        self.env={key:value for key,value in os.environ.items() if key in ('PATH','TMPDIR','LANG','LC_ALL')}
        self.env.update(HOME=str(self.home),ZDOTDIR=str(self.zdot),PATH=str(self.bin)+os.pathsep+self.env.get('PATH',os.defpath),UDS_DEPLOY_RUNTIME_DIR=str(self.root/'runtime'))

    def install(self):
        return subprocess.run(['bash',str(self.checkout/'install.sh'),str(self.project)],cwd=self.cwd,env=self.env,capture_output=True,text=True,timeout=10)

    def uninstall(self):
        return subprocess.run(['bash',str(self.checkout/'uninstall.sh'),str(self.project)],cwd=self.cwd,env=self.env,capture_output=True,text=True,timeout=10)

    def invoke(self,shell,args,code=0):
        env=dict(self.env,UDS_TEST_EXIT=str(code))
        if shell=='bash':command=[shutil.which(shell),'--noprofile','--norc','-c','. "$HOME/.bashrc"; uds "$@"','probe']
        else:command=[shutil.which(shell),'-dfc','. "$ZDOTDIR/.zshrc"; uds "$@"','probe']
        return subprocess.run(command+args,cwd=self.cwd,env=env,capture_output=True,text=True,timeout=10)

    def test_install_is_idempotent_and_preserves_configuration_and_native_binary(self):
        before=hashlib.sha256((self.bin/'uds').read_bytes()).digest()
        first=self.install();self.assertEqual(first.returncode,0,first.stderr)
        launcher=self.home/'.local/bin/uds-watch'
        self.assertTrue(launcher.is_symlink());self.assertEqual(launcher.resolve(),(self.checkout/'uds-watch').resolve())
        installed={file:file.read_bytes() for file in self.files+[self.task]}
        self.assertEqual(self.task.read_text().count('"$HOME/.local/bin/uds-watch" capture'),2)
        second=self.install();self.assertEqual(second.returncode,0,second.stderr)
        for file,content in installed.items():
            self.assertEqual(file.read_bytes(),content)
            if file!=self.task:
                self.assertTrue(content.startswith(b'# existing configuration\n'))
                self.assertEqual(content.count(b'# >>> uds-watch shortcut >>>'),1)
        self.assertFalse((self.home/'.bash_profile').exists(),'Do not shadow an existing .profile')
        self.assertEqual(hashlib.sha256((self.bin/'uds').read_bytes()).digest(),before)

    def test_bash_and_zsh_route_arguments_and_exit_codes_without_recursion(self):
        self.assertEqual(self.install().returncode,0)
        for shell in ('bash','zsh'):
            if not shutil.which(shell):continue
            for args,expected in [([],('native',[])),(['deploy','a path',''],('native',['deploy','a path',''])),(['watch'],('watcher',[])),(['watch','--port','0','a path',''],('watcher',['--port','0','a path',''])),(['watch','capture'],('watcher',['capture']))]:
                for code in (0,7):
                    with self.subTest(shell=shell,args=args,code=code):
                        result=self.invoke(shell,args,code);self.assertEqual(result.returncode,code,result.stderr)
                        self.assertEqual(json.loads(result.stdout),dict(command=expected[0],args=expected[1]))

    def test_real_launcher_works_from_another_directory(self):
        shutil.copy2(ROOT/'uds-watch',self.checkout/'uds-watch')
        (self.checkout/'src').symlink_to(ROOT/'src',target_is_directory=True)
        self.assertEqual(self.install().returncode,0)
        for shell in ('bash','zsh'):
            if not shutil.which(shell):continue
            result=self.invoke(shell,['watch','--help'])
            self.assertEqual(result.returncode,0,result.stderr);self.assertIn('read-only UDS/Zarf deployment viewer',result.stdout)

    def test_existing_unrelated_launcher_is_not_overwritten(self):
        launcher=self.home/'.local/bin/uds-watch';launcher.parent.mkdir(parents=True);launcher.write_bytes(b'keep this executable\n')
        result=self.install();self.assertNotEqual(result.returncode,0);self.assertIn('Refusing to replace',result.stderr)
        self.assertEqual(launcher.read_bytes(),b'keep this executable\n')
        self.assertTrue(all(file.read_text()=='# existing configuration\n' for file in self.files))

    def test_uninstall_restores_existing_files_and_is_idempotent(self):
        originals={file:file.read_bytes() for file in self.files}
        self.assertEqual(self.install().returncode,0)
        self.assertEqual(self.uninstall().returncode,0)
        self.assertFalse((self.home/'.local/bin/uds-watch').is_symlink())
        self.assertEqual({file:file.read_bytes() for file in self.files},originals)
        self.assertEqual(self.uninstall().returncode,0)
        self.assertEqual({file:file.read_bytes() for file in self.files},originals)
        self.assertTrue((self.bin/'uds').is_file());self.assertEqual(self.task.read_text(),self.original_tasks)

    def test_uninstall_keeps_later_user_settings_and_a_replaced_launcher(self):
        self.assertEqual(self.install().returncode,0)
        with self.files[0].open('ab') as stream:stream.write(b'export KEEP_THIS=1\n')
        launcher=self.home/'.local/bin/uds-watch';launcher.unlink();launcher.write_bytes(b'user replacement\n')
        self.assertEqual(self.uninstall().returncode,0)
        self.assertEqual(self.files[0].read_bytes(),b'# existing configuration\nexport KEEP_THIS=1\n')
        self.assertEqual(launcher.read_bytes(),b'user replacement\n')

    def test_installed_task_tee_preserves_native_output_and_exit_status(self):
        shutil.copy2(ROOT/'uds-watch',self.checkout/'uds-watch');(self.checkout/'src').symlink_to(ROOT/'src',target_is_directory=True)
        self.assertEqual(self.install().returncode,0)
        lines=self.task.read_text().splitlines();start=next(i for i,line in enumerate(lines) if '# uds-watch capture' in line)
        command='\n'.join(line.strip() for line in lines[start+1:start+3])
        for code in (0,7):
            env=dict(self.env,UDS_TEST_EXIT=str(code))
            expected=subprocess.run([str(self.bin/'uds'),'deploy','bundle.tar.zst','--confirm'],env=env,capture_output=True)
            result=subprocess.run(['bash','-c',command],cwd=self.project,env=env,capture_output=True,timeout=10)
            self.assertEqual(result.returncode,code,result.stderr);self.assertEqual(result.stdout,expected.stdout)

    def test_invalid_tasks_are_rejected_before_shell_setup(self):
        self.task.write_text('tasks: []\n')
        result=self.install();self.assertNotEqual(result.returncode,0)
        self.assertFalse((self.home/'.local/bin/uds-watch').exists())
        self.assertTrue(all(file.read_text()=='# existing configuration\n' for file in self.files))

    def test_uninstall_preserves_later_task_argument_changes(self):
        self.assertEqual(self.install().returncode,0)
        self.task.write_text(self.task.read_text().replace('--confirm','--confirm --force-conflicts'))
        self.assertEqual(self.uninstall().returncode,0)
        self.assertEqual(self.task.read_text(),self.original_tasks.replace('--confirm','--confirm --force-conflicts'))

    def test_edited_capture_exit_is_not_silently_removed(self):
        self.assertEqual(self.install().returncode,0)
        self.task.write_text(self.task.read_text().replace('exit "${PIPESTATUS[0]}" # uds-watch capture','exit 0 # user edit'))
        before={file:file.read_bytes() for file in self.files}
        result=self.uninstall();self.assertNotEqual(result.returncode,0)
        self.assertEqual({file:file.read_bytes() for file in self.files},before)
        self.assertTrue((self.home/'.local/bin/uds-watch').is_symlink())

    def test_default_startup_files_are_created(self):
        for file in self.files:file.unlink()
        self.env.pop('ZDOTDIR')
        self.assertEqual(self.install().returncode,0)
        for name in ('.bashrc','.bash_profile','.zshrc'):
            self.assertEqual((self.home/name).read_text().count('# >>> uds-watch shortcut >>>'),1)
        self.assertEqual(self.uninstall().returncode,0)
        self.assertTrue(all(not (self.home/name).exists() for name in ('.bashrc','.bash_profile','.zshrc')))


if __name__=='__main__':unittest.main()
