"""Installer regressions use isolated fake homes, never the developer's shell files."""
import io
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from uds_deploy import cli,setup


class Terminal(io.StringIO):
    def isatty(self):return True


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='uds-watch-setup-');self.home=Path(self.temp.name)
        self.env=patch.dict(os.environ,{'HOME':str(self.home),'XDG_CONFIG_HOME':str(self.home/'.config'),'ZDOTDIR':str(self.home),'UDS_DEPLOY_RUNTIME_DIR':str(self.home/'runtime')})
        self.env.start()
    def tearDown(self):self.env.stop();self.temp.cleanup()
    def test_private_backup_permissions_and_exact_uninstall(self):
        path=self.home/'.zshrc';original=b"export EXAMPLE='opaque-sensitive-canary'\n# no trailing newline";path.write_bytes(original);path.chmod(0o640)
        result=setup.install(ROOT/'uds-watch','zsh')
        self.assertEqual(len(result['backups']),1);self.assertEqual(result['backups'][0].read_bytes(),original)
        self.assertEqual(stat.S_IMODE(result['backups'][0].stat().st_mode),0o600);self.assertEqual(stat.S_IMODE(result['backups'][0].parent.stat().st_mode),0o700)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode),0o640)
        self.assertEqual(setup.install(ROOT/'uds-watch','zsh')['files'],[],'Repeated setup is idempotent')
        setup.uninstall('zsh');self.assertEqual(path.read_bytes(),original)
    def test_fresh_bash_startup_files_removed_on_uninstall(self):
        result=setup.install(ROOT/'uds-watch','bash');self.assertEqual(len(result['files']),2)
        self.assertTrue((self.home/'.bashrc').exists());self.assertTrue((self.home/'.bash_profile').exists())
        setup.uninstall('bash');self.assertFalse((self.home/'.bashrc').exists());self.assertFalse((self.home/'.bash_profile').exists())
    def test_existing_bash_login_priority_preserved(self):
        profile=self.home/'.profile';profile.write_text('# existing shared profile\n')
        setup.install(ROOT/'uds-watch','bash');self.assertFalse((self.home/'.bash_profile').exists());self.assertIn(setup.START,profile.read_bytes())
        setup.uninstall('bash');self.assertEqual(profile.read_text(),'# existing shared profile\n')
    def test_syntax_check_never_executes_existing_startup(self):
        marker=self.home/'MUST_NOT_EXECUTE';path=self.home/'.bashrc';path.write_text('touch '+str(marker)+'\n')
        setup.install(ROOT/'uds-watch','bash');self.assertFalse(marker.exists())
    def test_invalid_syntax_rejected_without_content_in_diagnostics(self):
        path=self.home/'.bashrc';original=b"export PASSWORD='opaque-sensitive-canary\n";path.write_bytes(original)
        with self.assertRaises(ValueError) as error:setup.install(ROOT/'uds-watch','bash')
        self.assertNotIn('opaque-sensitive-canary',str(error.exception));self.assertEqual(path.read_bytes(),original);self.assertFalse((self.home/'.bash_profile').exists())
    def test_symlinks_hardlinks_and_readonly_files_refused(self):
        source=self.home/'source';source.write_text('# original\n');rc=self.home/'.zshrc';rc.symlink_to(source)
        with self.assertRaises(ValueError):setup.install(ROOT/'uds-watch','zsh')
        rc.unlink();os.link(source,rc)
        with self.assertRaises(ValueError):setup.install(ROOT/'uds-watch','zsh')
        rc.unlink();rc.write_text('# readonly\n');rc.chmod(0o400)
        with self.assertRaises(ValueError):setup.install(ROOT/'uds-watch','zsh')
        rc.chmod(0o600);self.assertEqual(source.read_text(),'# original\n')
    def test_ambiguous_block_refused(self):
        path=self.home/'.zshrc';original=setup.START+b'\n# incomplete\n';path.write_bytes(original)
        with self.assertRaises(ValueError):setup.install(ROOT/'uds-watch','zsh')
        self.assertEqual(path.read_bytes(),original)
    def test_user_edits_after_install_survive_uninstall(self):
        path=self.home/'.zshrc';path.write_bytes(b'# original without newline');setup.install(ROOT/'uds-watch','zsh')
        with path.open('ab') as stream:stream.write(b'export AFTER_INSTALL=retained\n')
        setup.uninstall('zsh');self.assertEqual(path.read_bytes(),b'# original without newline\nexport AFTER_INSTALL=retained\n')
    def test_partial_failure_rolls_back_previous_file(self):
        first=self.home/'.bashrc';second=self.home/'.bash_profile';first.write_text('# first\n');second.write_text('# second\n')
        original=setup.replace_file;calls=0
        def fail_second(*args):
            nonlocal calls
            calls+=1
            if calls==2:raise OSError('isolated write failure')
            return original(*args)
        with patch.object(setup,'replace_file',side_effect=fail_second),self.assertRaises(OSError):setup.install(ROOT/'uds-watch','bash')
        self.assertEqual(first.read_text(),'# first\n');self.assertEqual(second.read_text(),'# second\n')
    def test_noninteractive_launch_never_inspects_startup(self):
        with patch('sys.stdin',io.StringIO()),patch.object(setup,'configured',side_effect=AssertionError('must not inspect rc')):cli.maybe_setup()
    def test_first_run_consent_and_decline_are_respected(self):
        with patch('sys.stdin',Terminal()),patch('sys.stdout',Terminal()),patch.object(cli,'current_shell',return_value='zsh'),patch('builtins.input',return_value='n'):
            cli.maybe_setup()
        self.assertEqual(setup.preference(),'declined');self.assertFalse((self.home/'.zshrc').exists())
        with patch('sys.stdin',Terminal()),patch('sys.stdout',Terminal()),patch.object(cli,'current_shell',return_value='zsh'),patch('builtins.input',side_effect=AssertionError('must not prompt again')):cli.maybe_setup()
        setup.preference('installed')
        with patch('sys.stdin',Terminal()),patch('sys.stdout',Terminal()),patch.object(cli,'current_shell',return_value='zsh'),patch('builtins.input',return_value='y'),patch.object(sys,'argv',[str(ROOT/'uds-watch')]):cli.maybe_setup()
        self.assertTrue(setup.configured('zsh'))
    def test_cli_noninteractive_requires_explicit_approval(self):
        result=subprocess.run([str(ROOT/'uds-watch'),'setup','--shell','zsh'],stdin=subprocess.DEVNULL,capture_output=True,timeout=10)
        self.assertNotEqual(result.returncode,0);self.assertFalse((self.home/'.zshrc').exists())
    def test_installed_blocks_work_and_reload_without_overwriting(self):
        binary=self.home/'uds';binary.write_text('#!/bin/sh\nprintf native\nexit 7\n');binary.chmod(0o755)
        env=dict(os.environ,PATH=str(self.home)+os.pathsep+os.environ['PATH'])
        for shell in ('bash','zsh'):
            executable=shutil.which(shell)
            if not executable:continue
            path=self.home/('rc-'+shell);setup.install(ROOT/'uds-watch',shell,rc_file=path)
            script='. "$1"; . "$1"; uds deploy fixture.tar.zst'
            result=subprocess.run([executable,'-c',script,'isolated',str(path)],env=env,capture_output=True,timeout=10)
            self.assertEqual(result.returncode,7);self.assertEqual(result.stdout,b'native');self.assertEqual(result.stderr,b'')
            self.assertEqual(binary.read_text(),'#!/bin/sh\nprintf native\nexit 7\n')
    def test_existing_aliases_and_functions_remain_in_control(self):
        binary=self.home/'uds';binary.write_text('#!/bin/sh\nprintf native\n');binary.chmod(0o755)
        env=dict(os.environ,PATH=str(self.home)+os.pathsep+os.environ['PATH'])
        for shell in ('bash','zsh'):
            executable=shutil.which(shell)
            if not executable:continue
            for original,invoke in [('function uds(){ printf original-function; }\n','uds'),("alias uds='printf original-alias'\n","eval uds")]:
                path=self.home/('existing-'+shell);path.write_text(('shopt -s expand_aliases\n' if shell=='bash' and original.startswith('alias ') else '')+original);setup.install(ROOT/'uds-watch',shell,rc_file=path)
                result=subprocess.run([executable,'-c','. "$1"; '+invoke,'isolated',str(path)],env=env,capture_output=True,timeout=10)
                self.assertEqual(result.returncode,0);self.assertIn(b'original-',result.stdout);self.assertIn(b'already an alias/function',result.stderr)
    def test_shared_profile_is_inert_in_other_shells(self):
        path=self.home/'.profile';path.write_text('# shared profile\n');setup.install(ROOT/'uds-watch','bash')
        result=subprocess.run(['/bin/sh','-c','set -eu; . "$1"; printf shared-ok','isolated',str(path)],capture_output=True,timeout=10)
        self.assertEqual(result.returncode,0);self.assertEqual(result.stdout,b'shared-ok');self.assertEqual(result.stderr,b'')
    def test_missing_clone_fails_open_even_with_errexit(self):
        path=self.home/'.bashrc';setup.install(self.home/'removed clone/uds-watch','bash')
        result=subprocess.run(['bash','--noprofile','--norc','-c','set -eu; . "$1"; printf shell-ok','isolated',str(path)],capture_output=True,timeout=10)
        self.assertEqual(result.returncode,0);self.assertEqual(result.stdout,b'shell-ok')


if __name__=='__main__':unittest.main()
