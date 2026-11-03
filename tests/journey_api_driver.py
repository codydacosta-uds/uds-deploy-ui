"""API-only Linux SDK journey; intentionally not browser verification."""
import json
from pathlib import Path
import sys
import time
from urllib.parse import urljoin,quote
from urllib.request import urlopen

manifest=json.loads(Path(sys.argv[1]).read_text())
def until(test,description):
    deadline=time.monotonic()+30
    while time.monotonic()<deadline:
        value=test()
        if value:return value
        time.sleep(.05)
    raise AssertionError(description)
event=Path(manifest['browser_event'])
until(event.exists,'Viewer handoff missing')
url=json.loads(event.read_text())['url']
def get(path,raw=False):
    with urlopen(urljoin(url,path),timeout=5) as response:
        content=response.read()
    return content if raw else json.loads(content)
run=until(lambda:next((state for state in get('api/deployments') if state.get('source',{}).get('pid')==manifest['deploy_pid']),None),'Native capture not attached')
route='api/deployments/'+quote(run['id'])
assert run['source']['output_complete']
assert manifest['deploy_started_before_viewer']
Path(manifest['release_prepare']).touch()
until(lambda:any(report.get('definition_owner',{}).get('component')=='verify' and report.get('message')=='running command' for report in get(route)['reports']),'Live CLI transition missing')
Path(manifest['release_verify']).touch()
until(Path(manifest['task_exit']).exists,'Native task did not exit')
assert json.loads(Path(manifest['task_exit']).read_text())['code']==0
until(lambda:get(route).get('completed_at') and get(route)['source']['output_complete'],'Intact EOF not observed')
assert get(route+'/logs?download=1',raw=True)==Path(manifest['terminal']).read_bytes(),'Download differs from original output'
print('API-only deploy-first journey passed ('+manifest['shell']+', '+manifest['capture_mode']+'): native progress, intact EOF and byte-exact download; no browser was tested.')
