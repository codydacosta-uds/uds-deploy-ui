"""Reuse only unchanged packaged inventories; never share mutable child state."""
from pathlib import Path
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from uds_deploy.native import NativeReader


class MetadataCacheTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name);self.bundle=self.root/'bundle.tar.zst';self.binary=self.root/'uds'
        self.bundle.write_bytes(b'packaged archive');self.binary.write_bytes(b'fixture executable')
        self.result=({'metadata':{'name':'bundle'},'packages':[{'name':'first'},{'name':'second'}]},
                     {'first':{'metadata':{'name':'first'},'components':[]},'second':{'metadata':{'name':'second'},'components':[]}})
        self.reader=NativeReader();self.addCleanup(self.reader.close)
        mock=patch('uds_deploy.native.metadata',return_value=self.result)
        self.decode=mock.start();self.addCleanup(mock.stop)

    def read(self,bundle=None):return self.reader.artifact_metadata(bundle or self.bundle,self.binary)

    def test_unchanged_artifact_reuses_one_scan_and_isolates_children(self):
        definition,packages=self.read()
        definition['packages'].clear();packages['first']['components'].append({'name':'child-only'})
        again=self.read();again[1].pop('second')
        fresh=self.read()
        self.assertEqual(len(fresh[0]['packages']),2)
        self.assertEqual(fresh[1]['first']['components'],[])
        self.assertIn('second',fresh[1]);self.assertEqual(self.decode.call_count,1)

    def test_bundle_and_cli_changes_invalidate_inventory(self):
        self.read()
        self.bundle.write_bytes(b'changed archive')
        self.read();self.assertEqual(self.decode.call_count,2)
        self.binary.write_bytes(b'changed executable')
        self.read();self.assertEqual(self.decode.call_count,3)

    def test_atomic_replacement_invalidates_even_with_same_size_and_mtime(self):
        self.read()
        for index,path in enumerate((self.bundle,self.binary),2):
            previous=path.stat();replacement=path.with_suffix('.replacement')
            replacement.write_bytes(path.read_bytes())
            os.utime(replacement,ns=(previous.st_atime_ns,previous.st_mtime_ns));replacement.replace(path)
            self.read();self.assertEqual(self.decode.call_count,index)

    def test_only_one_inventory_is_retained(self):
        other=self.root/'other.tar.zst';other.write_bytes(b'other packaged archive')
        self.read();self.read(other);self.read()
        self.assertEqual(self.decode.call_count,3)

    def test_failed_or_disappearing_artifacts_never_return_cached_metadata(self):
        self.decode.side_effect=ValueError('unreadable fixture')
        with self.assertRaises(ValueError):self.read()
        self.assertIsNone(self.reader.metadata_cache)
        self.decode.side_effect=None;self.read()
        self.bundle.unlink();self.decode.side_effect=FileNotFoundError('removed fixture')
        with self.assertRaises(FileNotFoundError):self.read()
        self.assertEqual(self.decode.call_count,3)

    def test_artifact_changed_during_scan_is_not_cached(self):
        def decode(*_):
            if self.decode.call_count==1:self.bundle.write_bytes(b'replaced during metadata scan')
            return self.result
        self.decode.side_effect=decode
        self.read();self.assertIsNone(self.reader.metadata_cache)
        self.read();self.read();self.assertEqual(self.decode.call_count,2)


if __name__=='__main__':unittest.main()
