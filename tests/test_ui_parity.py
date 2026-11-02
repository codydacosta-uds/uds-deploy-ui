"""Reject any unreviewed drift in the shared deployment viewer UI."""
import hashlib
import json
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
WEB=next(path for path in (ROOT/'src/uds_deploy/web',ROOT/'scripts/uds_deploy/web') if path.is_dir())


class UIParityTests(unittest.TestCase):
    def test_shared_template_defaults_to_the_approved_watcher(self):
        self.assertIn(b'<body data-mode="live">',(WEB/'index.html').read_bytes(),'Never expose the legacy scheduler UI when a running server serves updated assets')
    def test_all_shared_assets_match_the_pinned_manifest(self):
        document=json.loads((ROOT/'ui-assets.json').read_text())
        self.assertEqual(document['schema_version'],1)
        expected=document['files'];actual={}
        for path in WEB.rglob('*'):
            self.assertFalse(path.is_symlink(),'Shared UI cannot depend on symlinked external files')
            if not path.is_file() or path.name=='.DS_Store' or '__pycache__' in path.parts:continue
            actual[str(path.relative_to(WEB))]=hashlib.sha256(path.read_bytes()).hexdigest()
        self.assertEqual(actual,expected,'UI drift detected. Edit only the canonical UI, refresh its manifest, and synchronize all consumers.')


if __name__=='__main__':unittest.main()
