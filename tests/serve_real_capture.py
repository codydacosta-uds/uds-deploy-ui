"""Temporary GET-only bridge for testing current assets on REAL retained captures.

Test helper only. Source capability URL is provided in the environment, never saved.
No lifecycle state is injected, no deployment is launched, no history is persisted.
"""
import json
import os
from pathlib import Path
import sys
from urllib.parse import quote,urlencode,urlsplit
from urllib.request import urlopen

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from uds_deploy.server import make_server


class RealCapture:
    def __init__(self,source):
        parsed=urlsplit(source)
        if parsed.scheme!='http' or parsed.hostname not in ('127.0.0.1','localhost'):raise ValueError('Explicit local viewer source required')
        self.source=source.split('?')[0].rstrip('/')+'/'
    def read(self,path):
        with urlopen(self.source+path,timeout=15) as response:return json.load(response)
    def list(self,summary=False):return self.read('api/deployments')
    def get(self,run):return self.read('api/deployments/'+quote(run,safe=''))
    def processes(self):return self.read('api/processes')
    def definition(self,run,package=None):return self.read('api/deployments/'+quote(run,safe='')+('/packages/'+quote(package,safe='') if package else '')+'/definition')
    def events(self,run,package=None,logs=False,**filters):
        if not logs:return []
        filters.setdefault('latest',False)
        query={key:int(value) if isinstance(value,bool) else value for key,value in filters.items() if value is not None}
        return self.read('api/deployments/'+quote(run,safe='')+('/packages/'+quote(package,safe='') if package else '')+'/logs?'+urlencode(query))


if __name__=='__main__':
    server=make_server(RealCapture(os.environ['UDS_WATCHER_SOURCE_URL']),0)
    print(server.private_url,flush=True)
    try:server.serve_forever(poll_interval=.2)
    except KeyboardInterrupt:pass
    finally:server.stopping.set();server.server_close()
