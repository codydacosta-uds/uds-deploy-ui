"""Isolated registration rollback, update and capture-integrity gates."""
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import unittest
from unittest.mock import patch

import test_entrypoints as fixtures
from uds_deploy import entrypoints
from uds_deploy.native import NativeReader


class BootstrapTests(unittest.TestCase):
    def test_distributed_artifacts_match_reviewed_source_and_manifest(self):
        home=Path(entrypoints.__file__).parent
        manifest=json.loads((home/'bootstrap/manifest.json').read_text())
        self.assertEqual(manifest['source_sha256'],hashlib.sha256((home/'cli_bootstrap.c').read_bytes()).hexdigest())
        self.assertEqual(set(manifest['sha256']),{'darwin-arm64','darwin-x86_64','linux-aarch64','linux-x86_64'})
        for name,digest in manifest['sha256'].items():
            self.assertEqual(hashlib.sha256((home/'bootstrap'/name).read_bytes()).hexdigest(),digest)
        self.assertTrue(entrypoints.bootstrap_binary().is_file())

    def test_eof_integrity_is_required_before_completion_can_be_inferred(self):
        for final,complete in ((b'1',True),(b'!',False)):
            reader=NativeReader();integrity=io.BytesIO(b'0')
            state=dict(status='deploying',packages=[],source={'output_complete':True})
            reader.sessions['fixture']=dict(pid=-1,state=state,integrity=integrity,capture_description='Full test capture')
            with patch('uds_deploy.native.processes',return_value=[]),patch.object(reader,'read'),patch.object(reader,'event'),patch.object(reader,'check_helm'):
                reader.refresh()
                self.assertFalse(state['source']['output_complete'])
                self.assertNotIn('completed_at',state)
                integrity.seek(0);integrity.write(final);reader.scanned=0;reader.refresh()
                self.assertEqual(state['source']['output_complete'],complete)
                self.assertEqual(state['status'],'unknown','Native exit status is never invented')


@unittest.skipUnless(shutil.which('cc') and shutil.which('lsof'),'Development native fixture prerequisites')
class RegistrationSafetyTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.EntrypointTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.root=self.fixture.root;self.native=self.fixture.native;self.env=self.fixture.env

    def test_partial_preparation_and_config_commit_failure_restore_native(self):
        original=self.native.read_bytes()
        with patch.object(entrypoints,'program',side_effect=ValueError('isolated preparation failure')):
            with self.assertRaises(ValueError):entrypoints.register(self.native)
        self.assertEqual(self.native.read_bytes(),original)
        self.assertEqual(list(self.root.glob('.uds.uds-watch-native-*')),[])
        with patch.dict(os.environ,self.env,clear=True),patch.object(entrypoints,'save_registered',side_effect=OSError('isolated registry failure')):
            with self.assertRaises(OSError):entrypoints.install_many([self.native])
        self.assertEqual(self.native.read_bytes(),original)
        self.assertEqual(list(self.root.glob('.uds.uds-watch-native-*')),[])

    def test_explicit_symlink_selection_is_not_resolved_into_a_replacement(self):
        (self.root/'alias').mkdir();alias=self.root/'alias/uds';alias.symlink_to(self.native)
        original=self.native.read_bytes()
        with patch.dict(os.environ,self.env,clear=True):
            with self.assertRaises(ValueError):entrypoints.install_many([alias])
        self.assertTrue(alias.is_symlink());self.assertEqual(self.native.read_bytes(),original)

    def test_uninstall_refuses_a_live_cli_without_signalling_it(self):
        entrypoints.register(self.native);marker=self.root/'busy'
        process=subprocess.Popen([str(self.native),'deploy','fixture','--wait',str(marker)],cwd=self.root,env=self.env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
        try:
            deadline=time.monotonic()+5
            while not marker.exists():self.assertLess(time.monotonic(),deadline);time.sleep(.02)
            with self.assertRaisesRegex(ValueError,'running'):entrypoints.unregister(self.native)
            self.assertIsNone(process.poll())
        finally:
            Path(str(marker)+'.release').touch();process.communicate(timeout=5)
        entrypoints.unregister(self.native)

    def test_idempotency_native_self_update_and_unrelated_files_are_preserved(self):
        result=entrypoints.register(self.native)
        self.assertFalse(entrypoints.register(self.native)['changed'])
        native=Path(result['native']);source=self.root/'update.c';updated=self.root/'update'
        source.write_text(fixtures.C.replace('return code;','return code+2;'))
        subprocess.run(['cc',str(source),'-o',str(updated)],check=True,capture_output=True)
        expected=updated.read_bytes();os.replace(updated,native)
        note=native.parent/'user-note';note.write_text('Preserve this user file')
        entrypoints.unregister(self.native)
        self.assertEqual(self.native.read_bytes(),expected)
        self.assertEqual(note.read_text(),'Preserve this user file')
        self.assertEqual(subprocess.run([str(self.native),'version'],capture_output=True).returncode,2)


if __name__=='__main__':unittest.main()
