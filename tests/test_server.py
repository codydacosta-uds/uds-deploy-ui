"""Isolated HTTP security/protocol regressions; not browser lifecycle evidence."""
import base64
from copy import deepcopy
import json
from pathlib import Path
import sys
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request,urlopen

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from uds_deploy.server import make_server


class FixtureStore:
    def __init__(self):
        self.state=dict(id='isolated',created_at=0,cursor=2,log_cursor=2,mode='observed',packages=[])
        self.raw=[b'first\r\n',b'last \xff\n']
    def list(self,summary=False):return [deepcopy(self.state)]
    def processes(self):return []
    def get(self,run):
        if run!='isolated':raise KeyError(run)
        return deepcopy(self.state)
    def definition(self,run,package=None):return dict(filename='zarf.yaml',yaml='kind: "ZarfPackageConfig"\n',values_hidden=False)
    def events(self,run,after=0,before=None,limit=500,logs=False,**filters):
        return [dict(id=i,data=dict(raw_b64=base64.b64encode(raw).decode())) for i,raw in enumerate(self.raw,1) if i>after and (before is None or i<before)][:limit] if logs else []


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.store=FixtureStore();self.server=make_server(self.store,0)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start();self.url=self.server.private_url
    def tearDown(self):
        self.server.stopping.set();self.server.shutdown();self.server.server_close();self.thread.join(timeout=2)
    def test_only_loopback_and_capability(self):
        self.assertEqual(self.server.server_address[0],'127.0.0.1')
        for url in [self.url.replace(self.url.split('/')[3],'wrong'),self.url]:
            request=Request(url,headers={'Host':'evil.example'}) if url==self.url else url
            with self.assertRaises(HTTPError) as error:urlopen(request)
            self.assertEqual(error.exception.code,403);error.exception.close()
    def test_static_allowlist_and_headers(self):
        for path,kind in [('', 'text/html'),('theme.js','text/javascript'),('fonts/GitLabSans.woff2','font/woff2'),('fonts/NOTICE.txt','text/plain'),('uds-logo.png','image/png'),('uds-logo-on-dark.png','image/png'),('doug.png','image/png'),('doug.png?v=2','image/png')]:
            with urlopen(self.url+path) as response:
                self.assertEqual(response.headers.get_content_type(),kind);self.assertEqual(response.headers['Cache-Control'],'no-store')
                self.assertIn("font-src 'self'",response.headers['Content-Security-Policy']);self.assertNotIn('https:',response.headers['Content-Security-Policy'])
        for path in ['../server.py','fonts%2f..%2f..%2fserver.py','capture.py','other-logo.png']:
            with self.assertRaises(HTTPError) as error:urlopen(self.url+path)
            self.assertEqual(error.exception.code,404);error.exception.close()
    def test_mutations_are_never_supported(self):
        for method in ('POST','PUT','PATCH','DELETE'):
            with self.assertRaises(HTTPError) as error:urlopen(Request(self.url+'api/deployments',data=b'{}',method=method))
            self.assertEqual(error.exception.code,403);error.exception.close()
    def test_original_download_is_byte_exact(self):
        with urlopen(self.url+'api/deployments/isolated/logs?download=1') as response:self.assertEqual(response.read(),b''.join(self.store.raw))
    def test_definitions_are_full_and_not_arbitrary_files(self):
        with urlopen(self.url+'api/deployments/isolated/definition') as response:self.assertFalse(json.load(response)['values_hidden'])
        with self.assertRaises(HTTPError) as error:urlopen(self.url+'api/deployments/isolated/packages/unknown/definition')
        self.assertEqual(error.exception.code,404);error.exception.close()


if __name__=='__main__':unittest.main()
