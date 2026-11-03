"""The viewer must not install anything, prompt for setup, or edit user files."""
import contextlib
import io
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import Mock,patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from uds_deploy import cli


class CLISafetyTests(unittest.TestCase):
    def test_launch_only_opens_and_closes_the_viewer(self):
        with tempfile.TemporaryDirectory() as directory:
            home=Path(directory);rc=home/'.zshrc';rc.write_text('# untouched fixture\n')
            server=Mock(private_url='http://127.0.0.1:0/test-only/')
            server.serve_forever.side_effect=KeyboardInterrupt
            store=Mock()
            with patch.dict(os.environ,{'HOME':directory,'XDG_CONFIG_HOME':str(home/'config')}),patch('builtins.input',side_effect=AssertionError('No setup prompt allowed')),patch.object(cli,'doctor',return_value=0),patch('uds_deploy.server.WatcherStore',return_value=store),patch.object(cli,'bind_viewer',return_value=server),patch.object(cli.webbrowser,'open') as browser,contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cli.main(['--no-browser','--port','0']),0)
                browser.assert_not_called()
            self.assertEqual(rc.read_text(),'# untouched fixture\n')
            self.assertEqual(list(home.iterdir()),[rc])
            server.server_close.assert_called_once();store.close.assert_called_once()

    def test_installation_commands_are_not_part_of_the_app(self):
        for command in ('setup','uninstall','shell-init'):
            with self.subTest(command=command),contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit) as error:
                cli.main([command])
            self.assertEqual(error.exception.code,2)
        package=Path(cli.__file__).parent
        for removed in ('entrypoints.py','entrypoint_bootstrap.py','cli_bootstrap.c','bootstrap','setup.py'):
            self.assertFalse((package/removed).exists(),removed+' must not be shipped')

    def test_obsolete_hook_probe_does_not_consume_stdin(self):
        result=subprocess.run([sys.executable,str(Path(cli.__file__).with_name('capture.py')),'--check-command','uds','deploy'],input=b'not deployment input',capture_output=True,timeout=3)
        self.assertEqual(result.returncode,1)
        self.assertEqual(result.stdout,b'');self.assertEqual(result.stderr,b'')

    def test_capture_is_only_a_stdin_tee_not_a_deployment_wrapper(self):
        with patch.object(cli.os,'execv',side_effect=SystemExit(0)) as execute,self.assertRaises(SystemExit):cli.main(['capture'])
        args=execute.call_args.args
        self.assertEqual(args[0],sys.executable)
        self.assertEqual(Path(args[1][1]).name,'capture.py')
        self.assertEqual(len(args[1]),2)


if __name__=='__main__':unittest.main()
