"""Optional, private runner snapshots. Records observations, never runs a job."""
from copy import deepcopy
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
import time

from .output import output_home

LIMIT=262144
IDENTIFIER=re.compile(r'[a-zA-Z0-9][a-zA-Z0-9._,-]{0,199}')


def private(path,directory=False):
    info=path.lstat()
    if stat.S_ISLNK(info.st_mode) or info.st_uid!=os.getuid() or stat.S_IMODE(info.st_mode)&0o077:raise ValueError('Run records must be private and owned by you')
    if not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)):raise ValueError('Invalid run record path')
    return info


def run_home(create=False):
    home=output_home();override=os.environ.get('UDS_DEPLOY_RUNTIME_DIR')
    if override:
        runtime=Path(override)
        if create:runtime.mkdir(mode=0o700,parents=True,exist_ok=True)
        private(runtime,True)
    if create:home.mkdir(mode=0o700,parents=True,exist_ok=True)
    private(home,True)
    directory=home/'runs'
    if create:directory.mkdir(mode=0o700,exist_ok=True)
    private(directory,True)
    return directory


def process_table():
    output=subprocess.check_output(['ps','-axo','pid=,ppid=,uid=,lstart='],env=dict(os.environ,LC_ALL='C'),timeout=2).decode()
    rows={}
    for line in output.splitlines():
        fields=line.strip().split(None,3)
        if len(fields)==4 and fields[2]==str(os.getuid()):rows[int(fields[0])]=dict(parent=int(fields[1]),start=fields[3])
    return rows


def validate(data,stored=False):
    def text(value):return isinstance(value,str) and 0<len(value)<=200 and not any(ord(c)<32 for c in value)
    def identity(value):return isinstance(value,str) and IDENTIFIER.fullmatch(value)
    def clock(value):return value is None or type(value) in (int,float) and 0<value<1e12
    allowed={'schema_version','id','label','started_at','completed_at','exit_code','layers','jobs'}
    if stored:allowed|={'pid','owner_start'}
    if not isinstance(data,dict) or set(data)-allowed or type(data.get('schema_version'))!=int or data['schema_version']!=1 or not re.fullmatch(r'[a-f0-9]{32}',str(data.get('id',''))):raise ValueError('Invalid run record')
    if not text(data.get('label')) or not clock(data.get('started_at')) or data.get('started_at') is None or not clock(data.get('completed_at')):raise ValueError('Invalid run timing')
    if data.get('exit_code') is not None and (type(data['exit_code'])!=int or not data.get('completed_at')):raise ValueError('Invalid run result')
    layers=data.get('layers');jobs=data.get('jobs')
    if not isinstance(layers,list) or not 1<=len(layers)<=32 or not isinstance(jobs,list) or not 1<=len(jobs)<=100:raise ValueError('Invalid run inventory')
    if any(not isinstance(layer,dict) or set(layer)!={'id','label'} or not identity(layer['id']) or not text(layer['label']) for layer in layers):raise ValueError('Invalid layer')
    layer_ids={layer['id'] for layer in layers}
    if len(layer_ids)!=len(layers):raise ValueError('Duplicate layer')
    ids=set();packages=set()
    for job in jobs:
        if not isinstance(job,dict) or set(job)!={'id','label','layer','packages','dependencies','pid','started_at','completed_at','exit_code'}:raise ValueError('Invalid job fields')
        if not identity(job['id']) or job['id'] in ids or not text(job['label']) or job['layer'] not in layer_ids:raise ValueError('Invalid job identity')
        ids.add(job['id'])
        if not isinstance(job['packages'],list) or not job['packages'] or len(job['packages'])>100 or any(not identity(p) for p in job['packages']) or len(set(job['packages']))!=len(job['packages']):raise ValueError('Invalid package selection')
        if packages.intersection(job['packages']):raise ValueError('Package belongs to multiple jobs')
        packages.update(job['packages'])
        if not isinstance(job['dependencies'],list) or len(job['dependencies'])>100 or any(not identity(p) for p in job['dependencies']):raise ValueError('Invalid dependencies')
        if not all(clock(job[key]) for key in ('started_at','completed_at')):raise ValueError('Invalid job timing')
        if job['pid'] is not None and (type(job['pid'])!=int or job['pid']<=0 or not job['started_at']):raise ValueError('Invalid child process')
        if job['completed_at'] is not None and (not job['started_at'] or job['completed_at']<job['started_at']):raise ValueError('Invalid job end')
        if job['exit_code'] is not None and (type(job['exit_code'])!=int or not job['completed_at']):raise ValueError('Invalid child result')
    remaining={job['id']:set(job['dependencies']) for job in jobs}
    if any(not deps<=ids for deps in remaining.values()):raise ValueError('Unknown dependency')
    while remaining:
        ready={key for key,deps in remaining.items() if not deps}
        if not ready:raise ValueError('Cyclic run graph')
        remaining={key:deps-ready for key,deps in remaining.items() if key not in ready}
    if stored and (type(data.get('pid'))!=int or data['pid']<=0 or not text(data.get('owner_start'))):raise ValueError('Invalid runner identity')
    return data


def follows(previous,data):
    # A result update cannot silently drop selected work or rewrite a terminal job.
    static=('id','label','layer','packages','dependencies')
    if any(previous[key]!=data[key] for key in ('id','label','started_at','layers')):return False
    if [{key:j[key] for key in static} for j in previous['jobs']]!=[{key:j[key] for key in static} for j in data['jobs']]:return False
    if previous.get('completed_at') and previous!=data:return False
    for old,new in zip(previous['jobs'],data['jobs']):
        if old['completed_at'] and old!=new:return False
        if old['started_at'] and old['started_at']!=new['started_at'] or old['pid'] and old['pid']!=new['pid']:return False
    return True


def publish(data):
    """Explicit stdin publication by the runner's child helper; no external config."""
    validate(data)
    rows=process_table();pid=os.getppid();owner=rows.get(pid)
    if not owner:raise ValueError('Runner process unavailable')
    data=dict(data,pid=pid,owner_start=owner['start'])
    home=run_home(True);path=home/(data['id']+'.json')
    if path.exists() or path.is_symlink():
        private(path)
        previous=json.loads(path.read_text())
        validate(previous,True)
        if (previous.get('pid'),previous.get('owner_start'))!=(pid,owner['start']):raise ValueError('Run belongs to another process')
        if not follows(previous,data):raise ValueError('Run plan or terminal result changed')
    else:
        # Like console capture cleanup: only old dead owners, never a live run.
        for old in home.glob('*.json'):
            try:
                info=private(old)
                if time.time()-info.st_mtime<30 or info.st_size>LIMIT:continue
                item=validate(json.loads(old.read_text()),True)
                if rows.get(item['pid'],{}).get('start')!=item['owner_start']:old.unlink()
            except (OSError,ValueError,KeyError,TypeError):continue
    content=json.dumps(data).encode()
    if len(content)>LIMIT:raise ValueError('Run record too large')
    fd,temporary=tempfile.mkstemp(prefix='.snapshot-',dir=home)
    try:
        with os.fdopen(fd,'wb') as output:output.write(content)
        os.replace(temporary,path)
    finally:
        if os.path.exists(temporary):os.unlink(temporary)


class RunReader:
    def __init__(self):self.sessions={};self.scanned=0
    def refresh(self,children):
        if time.monotonic()-self.scanned<.5:return
        self.scanned=time.monotonic()
        try:
            home=run_home();paths=list(home.glob('*.json'))[:200]
        except (OSError,ValueError):paths=[]
        if not paths and not self.sessions:return
        try:rows=process_table()
        except (OSError,ValueError,subprocess.SubprocessError):return
        for path in paths:
            try:
                if private(path).st_size>LIMIT:continue
                data=validate(json.loads(path.read_text()),True)
                if path.name!=data['id']+'.json':continue
                known=self.sessions.get(data['id'])
                alive=rows.get(data['pid'],{}).get('start')==data['owner_start']
                if not alive and not known:continue  # Session history, not saved run discovery.
                if known and ((known['data']['pid'],known['data']['owner_start'])!=(data['pid'],data['owner_start']) or not follows(known['data'],data)):continue
                session=self.sessions.setdefault(data['id'],dict(data=data,links={},ended=None))
                session['data']=data
            except (OSError,ValueError,TypeError,KeyError):continue
        for session in self.sessions.values():
            data=session['data'];alive=rows.get(data['pid'],{}).get('start')==data['owner_start']
            if not alive and session['ended'] is None:session['ended']=time.time()
            session['alive']=alive
            if not alive:continue
            for job in data['jobs']:
                if job['id'] in session['links'] or not job['pid']:continue
                matches=[]
                for child in children.values():
                    state=child['state'];pid=child['pid'];process=rows.get(pid,{});launcher=rows.get(job['pid'],{})
                    related=pid==job['pid'] and process.get('parent')==data['pid'] or process.get('parent')==job['pid'] and launcher.get('parent')==data['pid']
                    if related and state.get('source',{}).get('single_cli') is True and {p['id'] for p in state['packages']}==set(job['packages']):
                        matches.append(state['id'])
                if len(matches)==1:session['links'][job['id']]=matches[0]
    def list(self):return [self.get('matrix-'+key) for key in self.sessions]
    def get(self,run):
        session=self.sessions[run.removeprefix('matrix-')];data=session['data'];ended=data.get('completed_at') or session['ended']
        jobs=[]
        for item in data['jobs']:
            job={key:deepcopy(item[key]) for key in ('id','label','layer','packages','dependencies','started_at','completed_at','exit_code')}
            code=job['exit_code']
            job['status']='completed' if code==0 else 'failed' if code is not None else 'unknown' if ended else 'deploying' if job['started_at'] else 'waiting'
            if ended and not job['started_at']:job['status']='not-started'
            job['child_run_id']=session['links'].get(job['id']);jobs.append(job)
        code=data.get('exit_code')
        status='failed' if code is not None and code!=0 or any(j['status']=='failed' for j in jobs) else 'completed' if code==0 and all(j['status']=='completed' for j in jobs) else 'unknown' if ended else 'deploying'
        return dict(id='matrix-'+data['id'],bundle_name=data['label'],version='',created_at=data['started_at'],started_at=data['started_at'],completed_at=ended,status=status,mode='concurrent',source={'kind':'runner-record'},reports=[],checks=[],cursor=0,packages=[{'id':p} for p in dict.fromkeys(p for j in jobs for p in j['packages'])],matrix=dict(layers=deepcopy(data['layers']),jobs=jobs))
    def child_ids(self):return {child for session in self.sessions.values() for child in session['links'].values()}
