"""Protocol parity and isolated cross-platform metadata regression fixtures."""
import hashlib
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
PACKAGE=ROOT/'src/uds_deploy'
if not (PACKAGE/'output.py').is_file():PACKAGE=ROOT/'scripts/uds_deploy'
sys.path.insert(0,str(PACKAGE.parent))
from uds_deploy.output import capture_helper,pipe_identity


class CaptureProtocolTests(unittest.TestCase):
    def test_shared_protocol_matches_manifest(self):
        manifest=json.loads((ROOT/'capture-protocol.json').read_text())
        self.assertEqual(hashlib.sha256((PACKAGE/'output.py').read_bytes()).hexdigest(),manifest['sha256'],'Do not independently change producer/reader capture conventions')

    def test_known_helper_roles(self):
        self.assertTrue(capture_helper(['python3','scripts/deploy-output.py']))
        self.assertTrue(capture_helper(['python3','/clone/src/uds_deploy/capture.py']))
        self.assertTrue(capture_helper(['python3','/clone/uds-watch','capture']))
        self.assertFalse(capture_helper(['python3','/clone/uds-watch','doctor']))
        self.assertFalse(capture_helper(['python3','/unrelated/capture.py']))
        self.assertFalse(capture_helper(['python3','/unrelated/tee.py']))

    def test_linux_requires_identifiable_pipe(self):
        self.assertEqual(pipe_identity({'inode':'100','path':'pipe'}),('inode','100'))
        self.assertNotEqual(pipe_identity({'inode':'100','path':'pipe'}),pipe_identity({'inode':'200','path':'pipe'}))
        self.assertIsNone(pipe_identity({'path':'pipe'}))
        self.assertIsNone(pipe_identity({'inode':'0','path':'pipe'}))

    def test_macos_reciprocal_pipe_endpoints(self):
        self.assertEqual(pipe_identity({'device':'0x10','path':'->0x20'}),pipe_identity({'device':'0x20','path':'->0x10'}))
        self.assertNotEqual(pipe_identity({'device':'0x10','path':'->0x20'}),pipe_identity({'device':'0x30','path':'->0x40'}))


if __name__=='__main__':unittest.main()
