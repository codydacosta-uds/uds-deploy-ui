"""Small terminal formatting checks; no real viewer or CLI is launched."""
import contextlib
import io
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock,patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from uds_deploy import cli


class TerminalOutputTests(unittest.TestCase):
    def test_colors_are_only_for_capable_interactive_terminals(self):
        for tty,env,colored in [(True,{'TERM':'xterm-256color'},True),(False,{'TERM':'xterm'},False),(True,{'TERM':'dumb'},False),(True,{'TERM':'xterm','NO_COLOR':''},False)]:
            with self.subTest(tty=tty,env=env),patch.dict(os.environ,env,clear=True),patch.object(cli.sys,'stdout',Mock(isatty=lambda:tty)):
                value=cli.terminal('ready','32')
                self.assertEqual(value,'\033[32mready\033[0m' if colored else 'ready')

    def test_doctor_is_aligned_and_missing_dependencies_still_fail(self):
        output=io.StringIO()
        with patch.object(cli.sys,'platform','linux'),patch.object(cli.shutil,'which',side_effect=lambda tool:None if tool=='zstd' else '/fixture/'+tool),contextlib.redirect_stdout(output):
            self.assertEqual(cli.doctor(),1)
        text=output.getvalue();self.assertIn('UDS Watch\n\n',text)
        self.assertRegex(text,r'FAIL\s+zstd\s+missing');self.assertRegex(text,r'OK\s+UDS/Zarf\s+available')
        self.assertNotIn('\033[',text)

    def test_startup_keeps_the_full_private_url_plain_when_redirected(self):
        server=Mock(private_url='http://127.0.0.1:0/fixture-only/')
        server.serve_forever.side_effect=KeyboardInterrupt;output=io.StringIO()
        with patch.object(cli,'doctor',return_value=0),patch('uds_deploy.server.WatcherStore'),patch.object(cli,'bind_viewer',return_value=server),contextlib.redirect_stdout(output):
            self.assertEqual(cli.main(['--no-browser']),0)
        text=output.getvalue();self.assertIn('Viewer ready\n\n  '+server.private_url,text)
        self.assertIn('Ctrl+C stops the viewer, not your deployment.',text);self.assertNotIn('\033[',text)


if __name__=='__main__':unittest.main()
