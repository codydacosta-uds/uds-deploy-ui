"""Port selection regression checks; never stop or replace an existing listener."""
import contextlib
import errno
import io
from pathlib import Path
import socket
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from uds_deploy.cli import bind_viewer
from uds_deploy.server import make_server


class PortTests(unittest.TestCase):
    def test_default_port_busy_uses_an_available_port(self):
        result=object()
        with patch('uds_deploy.server.make_server',side_effect=[OSError(errno.EADDRINUSE,'busy'),result]) as factory,contextlib.redirect_stdout(io.StringIO()):
            self.assertIs(bind_viewer(None),result)
        self.assertEqual([call.args[1] for call in factory.call_args_list],[8765,0])
    def test_explicit_port_is_not_silently_changed(self):
        with patch('uds_deploy.server.make_server',side_effect=OSError(errno.EADDRINUSE,'busy')) as factory,self.assertRaises(OSError):bind_viewer(None,8765)
        self.assertEqual(factory.call_count,1)
    def test_unrelated_binding_error_is_not_masked(self):
        with patch('uds_deploy.server.make_server',side_effect=OSError(errno.EACCES,'denied')) as factory,self.assertRaises(OSError):bind_viewer(None)
        self.assertEqual(factory.call_count,1)
    def test_explicit_zero_is_passed_through(self):
        with patch('uds_deploy.server.make_server') as factory:bind_viewer(None,0)
        self.assertEqual(factory.call_args.args[1],0)
    def test_real_occupied_listener_is_left_intact(self):
        with socket.socket() as busy:
            busy.bind(('127.0.0.1',0));busy.listen();port=busy.getsockname()[1]
            def allocate(store,requested):return make_server(store,port if requested==8765 else requested)
            with patch('uds_deploy.server.make_server',side_effect=allocate),contextlib.redirect_stdout(io.StringIO()):server=bind_viewer(None)
            try:
                self.assertNotEqual(server.server_port,port)
                with socket.create_connection(('127.0.0.1',port),timeout=1):pass
            finally:server.server_close()


if __name__=='__main__':unittest.main()
