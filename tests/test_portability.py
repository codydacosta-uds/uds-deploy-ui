"""Isolated platform metadata edge cases, not deployment evidence."""
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from uds_deploy.native import pipe_key


class PipeIdentityTests(unittest.TestCase):
    def test_linux_generic_pipe_names_need_inodes(self):
        self.assertNotEqual(pipe_key({'path':'pipe','inode':'100'}),pipe_key({'path':'pipe','inode':'200'}))
        self.assertEqual(pipe_key({'path':'pipe','inode':'100'}),pipe_key({'path':'pipe','inode':'100'}))
    def test_macos_endpoint_name_fallback(self):
        self.assertEqual(pipe_key({'path':'0x123'}),('path','0x123'))
    def test_unknown_identity_is_not_proof_of_combined_output(self):
        self.assertIsNone(pipe_key({'path':'pipe'}));self.assertIsNone(pipe_key({'inode':'0','path':'pipe'}));self.assertIsNone(pipe_key({}))


if __name__=='__main__':unittest.main()
