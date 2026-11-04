# Standalone adaptation of Apache-2.0 watcher code; see NOTICE.
"""Read-only attachment to stock UDS/Zarf processes and their existing files.

No launch, injection, database, terminal reads, or guessed process exit codes.
Native SDK messages are diagnostic reports, not execution return callbacks.
"""
from collections import deque
from copy import deepcopy
import base64
import bisect
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import stat
import subprocess
import tarfile
import time

from .definitions import artifact_info, component_info, document_view, safe_reference, declared_charts


def command_args(args):
    """Locate the verb without rewriting the original argv (Cobra globals)."""
    values={'--log-level','-l','--architecture','-a','--uds-cache','--zarf-cache','--tmpdir','--oci-concurrency'}
    switches={'--no-log-file','--no-progress','--insecure','--skip-signature-validation','--no-color'}
    i=1
    while i<len(args) and args[i].startswith('-'):
        flag,equals,_=args[i].partition('=')
        if flag in values:i+=1 if equals else 2
        elif flag in switches:i+=1
        elif args[i][:2] in ('-l','-a') and not args[i].startswith('--'):i+=1
        else:return []  # Unknown flag arity is not a reason to guess the verb.
    return args[i:]


def processes():
    output=subprocess.check_output(['ps','-axo','pid=,uid=,comm=,args=']).decode('utf-8',errors='replace')
    found=[]
    for line in output.splitlines():
        fields=line.strip().split(None,3)
        if len(fields)!=4 or fields[1]!=str(os.getuid()):continue
        try:args=shlex.split(fields[3])
        except ValueError:continue
        if not args:continue
        tool=Path(fields[2]).name
        # macOS ps truncates a full-path comm (e.g. /opt/homebrew/bi).
        # Accept argv[0] only when that absolute comm is its matching prefix.
        if tool not in ('uds','zarf') and fields[2].startswith('/') and args[0].startswith(fields[2]):tool=Path(args[0]).name
        if tool not in ('uds','zarf'):continue
        verbs=command_args(args)
        direct=tool=='uds' and bool(verbs) and (verbs[0] in ('deploy','d') or verbs[:3]==['zarf','package','deploy']) or tool=='zarf' and verbs[:2]==['package','deploy']
        if direct:found.append(dict(pid=int(fields[0]),tool=tool,args=args,kind='deployment process'))
    return found


def open_files(pid):
    # lsof is read-only and available on macOS/Linux. Never open a TTY: doing so
    # would not recover historical writes and could interfere with user input.
    result=subprocess.run(['lsof','-a','-p',str(pid),'-Fftnid'],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=3)
    records=[];entry={}
    for line in result.stdout.decode('utf-8',errors='replace').splitlines():
        if line.startswith('f'):
            if entry:records.append(entry)
            entry={'fd':line[1:]}
        elif line.startswith('t'):entry['type']=line[1:]
        elif line.startswith('n'):entry['path']=line[1:]
        elif line.startswith('i'):entry['inode']=line[1:]
        elif line.startswith('d'):entry['device']=line[1:]
    if entry:records.append(entry)
    return records


def pipe_key(record):
    """Use the shared Linux/macOS output-channel identity convention."""
    from .output import pipe_identity
    return pipe_identity(record)


def task_console(pid):
    """Find only a same-user UDS task ancestor's combined regular output file.

    A normal `uds run` pipes its child's output internally. An explicit shell
    redirect on that task preserves the console without changing its actions.
    Never read the pipe/TTY, or attach to an unrelated tee/log file.
    """
    output=subprocess.check_output(['ps','-axo','pid=,ppid=,uid=,comm=,args='],timeout=3).decode('utf-8',errors='replace')
    rows={}
    for line in output.splitlines():
        fields=line.strip().split(None,4)
        if len(fields)==5:rows[fields[0]]=fields
    current=rows.get(str(pid))
    for _ in range(5):
        if not current:return []
        current=rows.get(current[1])
        if not current or current[2]!=str(os.getuid()):return []
        try:args=shlex.split(current[4])
        except ValueError:return []
        if not args:continue
        comm=current[3]
        tool=Path(comm).name
        if tool!='uds' and comm.startswith('/') and args[0].startswith(comm):tool=Path(args[0]).name
        if tool=='uds' and args[1:2]==['run']:
            sources=[r for r in open_files(int(current[0])) if r.get('type')=='REG' and r.get('fd') in ('1','2')]
            return sources if {r['fd'] for r in sources}=={'1','2'} and len({r['path'] for r in sources})==1 else []
    return []


def metadata(bundle,uds):
    """Read small OCI metadata layers only; stop before image payloads.

    Return actual bundle and embedded package definitions without unpacking a
    second copy of the artifact. Unsupported layouts get no invented inventory.
    """
    blobs={};bundle_digest=None;zarf_digest=None;package_manifests={};definitions={};definition=None
    prefix=[uds,'tools'] if Path(uds).name=='zarf' else [uds,'zarf','tools']
    process=subprocess.Popen(['zstd','-dc',str(bundle)],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
    def yaml(raw):
        output=subprocess.check_output(prefix+['yq','-o=json','.','-'],input=raw,stderr=subprocess.DEVNULL,timeout=5)
        return json.loads(output)
    try:
        with tarfile.open(fileobj=process.stdout,mode='r|') as archive:
            for member in archive:
                if not member.isfile():continue
                if member.size>2*1024*1024:break  # never scan/decompress image layers to get a UI
                raw=archive.extractfile(member).read()
                if member.name.lstrip('./')=='zarf.yaml':
                    package=yaml(raw);name=package['metadata']['name']
                    return dict(kind=package['kind'],metadata=package['metadata'],packages=[dict(name=name,ref=str(package['metadata'].get('version','unknown')))]),{name:package}
                digest=member.name.rsplit('/',1)[-1]
                if member.name.startswith('blobs/sha256/'):
                    if hashlib.sha256(raw).hexdigest()!=digest:raise ValueError('Artifact metadata digest mismatch')
                    blobs[digest]=raw
                try:document=json.loads(raw)
                except (ValueError,UnicodeError):document={}
                if isinstance(document,dict):
                    for layer in document.get('layers',[]):
                        title=layer.get('annotations',{}).get('org.opencontainers.image.title')
                        if title=='uds-bundle.yaml':bundle_digest=layer['digest'].split(':')[-1]
                        if title=='zarf.yaml':zarf_digest=layer['digest'].split(':')[-1]
                if bundle_digest in blobs and definition is None:
                    definition=yaml(blobs[bundle_digest])
                    for package in definition.get('packages',[]):
                        ref=package.get('ref','')
                        if '@sha256:' in ref:package_manifests[package['name']]=ref.rsplit('@sha256:',1)[-1]
                for alias,manifest in package_manifests.items():
                    if alias in definitions or manifest not in blobs:continue
                    doc=json.loads(blobs[manifest])
                    for layer in doc.get('layers',[]):
                        if layer.get('annotations',{}).get('org.opencontainers.image.title')=='zarf.yaml':
                            target=layer['digest'].split(':')[-1]
                            if target in blobs:definitions[alias]=yaml(blobs[target])
                if not definition and zarf_digest in blobs and bundle_digest is None:
                    package=yaml(blobs[zarf_digest]);name=package['metadata']['name']
                    return dict(kind=package['kind'],metadata=package['metadata'],packages=[dict(name=name,ref=str(package['metadata'].get('version','unknown')))]),{name:package}
                if definition and len(definitions)==len(package_manifests):break
    finally:
        process.stdout.close()
        if process.poll() is None:process.terminate()
        process.wait()
    if not definition:raise ValueError('Bundle metadata is not available before payload layers')
    return definition,definitions


# An exact stock SDK message catalog, not phase-result inference. A matched
# message remains a CLI report even when its wording contains "succeeded".
MESSAGES={
 'starting deploy':('package.start','Deploy package'),
 'deploying component':('component.start','Deploy component'),
 'waiting for cluster connection':('cluster.connect','Connect to cluster'),
 'done waiting for cluster, connected':('cluster.connected','Cluster connection reported ready'),
 'running command':('actions.command','Run action'),
 'action succeeded':('actions.command','Action reported success'),
 'action failed':('actions.command','Action reported failure'),
 'pulling images':('images.pull','Pull images'),
 'saving image':('images.pull','Save image'),
 'done pulling images':('images.pull','Image pull reported complete'),
 'pushing image':('images.push','Push image'),
 'image push in progress':('images.push','Push image'),
 'done pushing images':('images.push','Image push reported complete'),
 'processing Helm chart':('helm.prepare','Prepare Helm chart'),
 'performing Helm install':('helm.install','Helm install'),
 'performing Helm upgrade':('helm.upgrade','Helm upgrade'),
 'running health checks':('health.wait','Check readiness'),
}
ANSI=re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]')


def report_time(value):
    """SDK log clock only; ingestion timestamps still control report ordering."""
    if not isinstance(value,str) or not re.fullmatch(r'\d{4}-\d\d-\d\d[T ]\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)?',value):return None
    try:
        stamp=datetime.datetime.fromisoformat(value.replace('Z','+00:00')).timestamp()
        return stamp if stamp>0 else None
    except (ValueError,OverflowError,OSError):return None


def report(raw):
    """Normalize source-specific diagnostic reports, never successful phases."""
    # UDS task spinners redraw with CR, then print the child's actual line.
    # Parse the final visible segment only; raw bytes remain untouched.
    text=ANSI.sub('',raw).rstrip('\r\n').rsplit('\r',1)[-1].strip()
    # Stock UDS v0.40 prints this terminal error, without an SDK `action
    # failed` event when the action has no timeout. It is still a CLI claim,
    # not an observable child exit code or an authoritative phase callback.
    terminal=re.fullmatch(r'ERROR:\s+failed to (?:deploy|validate) bundle:\s+(.+)',text)
    if terminal:
        error=terminal.group(1)
        item=dict(kind='deployment.error',label='CLI reported an error',message='deployment error reported',resource=None,action_id=None,error=error[:4096],evidence='cli-report',status='reported')
        quoted=r'("(?:[^"\\]|\\.)*")'
        action=re.fullmatch(r'unable to deploy component '+quoted+r': unable to run component (?:before|after|success|failure) action: command '+quoted+r' (?:failed after \d+ retries|timed out after \d+ seconds)',error)
        if action:
            try:component,command=(json.loads(value) for value in action.groups())
            except ValueError:return item  # Unsupported Go quoting stays unassigned.
            item.update(kind='actions.command',label='Action reported failure',message='action failed',reported_component=component,action_id=hashlib.sha256(command.encode()).hexdigest()[:12])
        return item
    try:
        item=json.loads(text)
        if not isinstance(item,dict):return None
        message=item.get('msg');fields=item;source_time=report_time(item.get('time'))
    except ValueError:
        # v0.40 legacy console logger: ISO local date/time, level, SDK message.
        tokens=text.split(None,3)
        if len(tokens)!=4 or not re.fullmatch(r'\d{4}-\d\d-\d\d',tokens[0]) or not re.fullmatch(r'\d\d:\d\d:\d\d',tokens[1]) or tokens[2] not in ('INF','ERR','WRN','DBG'):return None
        source_time=report_time(tokens[0]+'T'+tokens[1])
        remainder=tokens[3];message=None;fields={}
        for known in sorted(MESSAGES,key=len,reverse=True):
            if remainder==known or remainder.startswith(known+' '):
                message=known
                try:
                    current=None
                    for token in shlex.split(remainder[len(known):]):
                        key,sep,value=token.partition('=')
                        if sep and key in ('name','chart','package','cmd','count','source','duration','complete','remaining'):
                            fields[key]=value;current=key
                        elif current:fields[current]+=' '+token
                except ValueError:pass
                # The SDK logs a display command (often truncated mid-quote),
                # not shell arguments. Preserve that field verbatim for matching.
                suffix=remainder[len(known):].strip()
                if known in ('running command','action succeeded','action failed') and suffix.startswith('cmd='):
                    fields['cmd']=suffix[4:]
                    if known=='action failed':
                        # This SDK always appends err after cmd. If cmd or
                        # err also contains this delimiter, do not guess which
                        # prefix is a command: leave the report unassigned.
                        boundaries=list(re.finditer(r' err=',fields['cmd']))
                        if len(boundaries)==1:
                            boundary=boundaries[0];fields['err']=fields['cmd'][boundary.end():]
                            fields['cmd']=fields['cmd'][:boundary.start()]
                break
    if not isinstance(message,str) or message not in MESSAGES:return None
    kind,label=MESSAGES[message]
    for key in ('name','chart','package'):
        if not isinstance(fields.get(key,''),str):fields[key]=''
    # Body fields are diagnostic claims, never authoritative execution identity.
    resource=fields.get('package') if kind=='package.start' else fields.get('name') if kind=='component.start' else fields.get('chart') or (fields.get('name') if kind.startswith(('images.','helm.')) else None)
    result=dict(kind=kind,label=label,message=message,resource=resource,action_id=hashlib.sha256(str(fields.get('cmd','')).encode()).hexdigest()[:12] if kind=='actions.command' else None,error=fields.get('err')[:4096] if isinstance(fields.get('err'),str) else None,evidence='cli-report',status='reported')
    if source_time is not None:result['source_timestamp']=source_time
    percent=fields.get('complete')
    if message=='image push in progress' and resource and isinstance(percent,str) and re.fullmatch(r'\d+(?:\.\d+)?%',percent):
        value=float(percent[:-1])
        if 0<=value<=100:result['image_percent']=value
    return result


def action_keys(action):
    command=action.get('cmd','');escaped=command.replace('\n','; ')
    raw=escaped.encode();display=action.get('description') or (escaped if len(raw)<=60 else (raw[:57]+b'...').decode('utf-8',errors='replace'))
    # Stock Zarf truncates the display command to 60 bytes. Index the exact
    # display, as well as full/legacy normalized forms; never fuzzy-match it.
    forms={command,display}
    for value in list(forms):
        try:forms.add(' '.join(shlex.split(value)))
        except ValueError:pass
    return {hashlib.sha256(value.encode()).hexdigest()[:12] for value in forms if value}


def action_labels(packages):
    labels={}
    for package in packages.values():
        for component in package.get('components',[]):
            for hook,title in [('before','Pre-deploy action'),('after','Post-deploy action'),('onSuccess','Success action'),('onFailure','Failure action')]:
                for action in component.get('actions',{}).get('onDeploy',{}).get(hook,[]):
                    for key in action_keys(action):labels.setdefault(key,set()).add(title)
    return {key:next(iter(values)) for key,values in labels.items() if len(values)==1}


def action_declarations(packages):
    """Unify exact SDK display/full-command forms only for one declared action."""
    aliases={}
    for package,definition in packages.items():
        for component in definition.get('components',[]):
            for hook,actions in component.get('actions',{}).get('onDeploy',{}).items():
                if not isinstance(actions,list):continue
                for index,action in enumerate(actions):
                    identity=hashlib.sha256(json.dumps([package,component['name'],hook,index]).encode()).hexdigest()[:16]
                    for key in action_keys(action):aliases.setdefault(key,set()).add(identity)
    return {key:next(iter(values)) for key,values in aliases.items() if len(values)==1}


def action_names(packages):
    """Only declared descriptions, never command bodies or guessed action names."""
    names={}
    for package in packages.values():
        for component in package.get('components',[]):
            for actions in component.get('actions',{}).get('onDeploy',{}).values():
                if not isinstance(actions,list):continue
                for action in actions:
                    description=action.get('description')
                    description=re.sub(r'https?://\S+',lambda m:safe_reference(m.group()),' '.join(ANSI.sub('',description).split()))[:240] if isinstance(description,str) and description.strip() else None
                    for key in action_keys(action):names.setdefault(key,set()).add(description)
    return {key:next(iter(values)) for key,values in names.items() if len(values)==1 and None not in values}


def definition_owners(definitions):
    """Index declared resource ownership, not guessed runtime identities.

    A report can reference a uniquely declared chart/image/action. This means
    'that resource is defined under this component', not 'this phase succeeded'.
    Reused resources/commands stay unassigned rather than choosing an alias.
    """
    index={}
    def add(kind,resource,package,component=None):
        owner=dict(package=package,component=component,evidence='artifact-definition')
        owners=index.setdefault((kind,resource),[])
        if owner not in owners:owners.append(owner)
    for alias,definition in definitions.items():
        add('package.start',definition.get('metadata',{}).get('name',alias),alias)
        add('package.start',alias,alias)
        for component in definition.get('components',[]):
            name=component['name'];add('component.start',name,alias,name)
            for chart in declared_charts(component,definition.get('metadata',{}).get('name')):add('helm',chart['name'],alias,name)
            for image in component.get('images',[]):add('images',image,alias,name)
            if component.get('images'):add('images','',alias,name)
            for actions in component.get('actions',{}).get('onDeploy',{}).values():
                if not isinstance(actions,list):continue
                for action in actions:
                    for key in action_keys(action):add('actions',key,alias,name)
    return index


def record_report(state,item,owners=None):
    """Record CLI claims with optional definition ownership; never phase results."""
    reports=state.setdefault('reports',[])
    item=dict(item,timestamp=time.time())
    kind=item['kind'];resource=item.get('resource') or ''
    lookup='helm' if kind.startswith('helm.') or kind=='health.wait' else 'images' if kind.startswith('images.') else 'actions' if kind=='actions.command' else kind
    matches=(owners or {}).get((lookup,item.get('action_id') or resource),[])
    if len(matches)==1 and (not item.get('reported_component') or matches[0].get('component')==item['reported_component']):item['definition_owner']=dict(matches[0])
    if not item.get('definition_owner') and (lookup=='helm' or lookup=='images' and resource) and len(matches)>1:
        # Stock UDS/Zarf deploys components sequentially. Reused chart/image
        # names need the explicit component boundary, not a global name guess.
        # Aggregate image completion still requires observed pushes below.
        source=state.get('source',{})
        sequential=source.get('kind')=='stock-process' and source.get('output_complete') is True and source.get('activity_available') is not False and source.get('single_cli') is not False and state.get('mode') not in ('parallel','concurrent') and sum(p.get('status')=='deploying' for p in state.get('packages',[]))<=1
        starts=[r for r in reports if r['kind'] in ('package.start','component.start')]
        boundary=max(starts,key=lambda r:r['timestamp']) if starts else None
        scope=boundary.get('definition_owner') if boundary and boundary['kind']=='component.start' else None
        if sequential and scope in matches and (not item.get('reported_component') or item['reported_component']==scope.get('component')):
            item['definition_owner']=dict(scope)
            item['scope_evidence']='explicit-sequential-cli-component-start'
            if boundary.get('log_id') is not None:item['scope_log_id']=boundary['log_id']
    if not item.get('definition_owner') and kind=='images.push' and item['message']=='done pushing images':
        # The stock SDK completion is component-wide and has no image name.
        # Scope it only with an explicit, uniquely owned component-start report
        # plus observed pushes from that same component. Never use the next
        # Helm operation, elapsed time, or process exit as completion evidence.
        starts=[r for r in reports if r['kind'] in ('package.start','component.start')]
        boundary=max(starts,key=lambda r:r['timestamp']) if starts else None
        scope=boundary.get('definition_owner') if boundary and boundary['kind']=='component.start' else None
        pushes=[r for r in reports if r['kind']=='images.push' and r['message'] in ('pushing image','image push in progress') and boundary and r['timestamp']>=boundary['timestamp']]
        if scope in matches and pushes and all(r.get('definition_owner')==scope for r in pushes):
            item['definition_owner']=dict(scope);item['scope_evidence']='explicit-cli-component-start-and-image-pushes'
    owner=item.get('definition_owner',{})
    key='/'.join([owner.get('package',''),owner.get('component') or '',kind,str(item.get('declaration_id') or item.get('action_id') or resource)])
    item['id']=key
    previous=next((r for r in reports if r['id']==key),None)
    if isinstance(item.get('source_timestamp'),(int,float)):
        if not previous:item['first_source_timestamp']=item['source_timestamp']
        elif previous.get('first_source_timestamp') is not None:item['first_source_timestamp']=previous['first_source_timestamp']
        else:item['timing_uncertain']=True
    if previous and isinstance(item.get('log_id'),int) and item['log_id']!=previous.get('log_id') and (kind in ('package.start','component.start','helm.prepare','helm.install','helm.upgrade') or kind=='actions.command' and item['message']=='running command'):
        item['timing_uncertain']=True
    if previous and isinstance(previous.get('first_log_id'),int):item['first_log_id']=previous['first_log_id']
    elif isinstance(item.get('log_id'),int):item.setdefault('first_log_id',item['log_id'])
    if previous:
        if 'source_timestamp' not in item:previous.pop('source_timestamp',None)
        if kind.startswith('images.') and 'image_percent' not in item:previous.pop('image_percent',None)
        previous.update(item);item=previous
    else:
        if len(reports)>=2048:reports.pop(0)
        reports.append(item)
    if owner.get('component'):
        for package in state.get('packages',[]):
            if package.get('id')!=owner.get('package'):continue
            for attempt in package.get('attempts',[]):
                for component in (attempt.get('execution') or {}).get('components',[]):
                    if component['id']==owner.get('component') and component.get('selection')=='not-selected':
                        component.update(expected=True,selection='observed',selection_evidence='CLI reported activity for this component')
    if owner:
        seen=state.setdefault('reported_definitions',[])
        if owner not in seen:seen.append(owner)
    return item


def unselected_components(bundle,item,package):
    """Known optional omissions from packaged UDS selection, not runtime success.

    UDS v0.40 uses Zarf's non-interactive filter: required/default components
    plus optionalComponents. Unknown schemas/selectors/groups remain expected.
    Actual CLI activity overrides this definition-only projection.
    """
    if bundle.get('kind')!='UDSBundle':return set()
    requested=item.get('optionalComponents',[])
    if not isinstance(requested,list) or any(not isinstance(name,str) or not re.fullmatch(r'[a-z0-9][a-z0-9._-]*',name) for name in requested):return set()
    version=package.get('apiVersion')
    if version not in (None,'zarf.dev/v1alpha1','zarf.dev/v1beta1'):return set()
    beta=version=='zarf.dev/v1beta1'
    excluded=set()
    for component in package.get('components',[]):
        optional=component.get('optional') is True if beta else component.get('required') is not True
        if optional and component.get('default') is not True and not component.get('group') and component['name'] not in requested:excluded.add(component['name'])
    return excluded


class NativeReader:
    def __init__(self):self.sessions={};self.scanned=0;self.excluded=set();self.capture_wait={}
    def refresh(self):
        if time.monotonic()-self.scanned<.5:return
        self.scanned=time.monotonic();active=processes();active_ids={p['pid'] for p in active}
        for process in active:
            if process['pid'] in self.excluded:continue
            if any(s['pid']==process['pid'] for s in self.sessions.values()):continue
            try:self.attach(process)
            except (OSError,ValueError,TypeError,AttributeError,KeyError,subprocess.SubprocessError):continue
        for session in self.sessions.values():
            self.read(session,finished=session['pid'] not in active_ids)
            if session.get('capture') and session['pid'] in active_ids:
                if session['capture']['record'].exists():session.pop('capture_missing_since',None)
                elif time.monotonic()-session.setdefault('capture_missing_since',time.monotonic())>2:
                    session['state']['source'].update(output_complete=False,activity_available=False,note='Output capture stopped while CLI is still running; check the deployment terminal')
            if session['pid'] not in active_ids and session['state']['status']=='deploying':
                session['state'].update(status='unknown',completed_at=time.time(),error='CLI process exited. Its exit code is not observable by a late-attached watcher; check the deployment terminal.')
                for p in session['state']['packages']:p['status']='unknown'
                self.event(session,'process.exited',{})
            self.check_helm(session)
    def attach(self,process):
        records=open_files(process['pid']);cwd=next((r['path'] for r in records if r['fd']=='cwd'),None)
        if not cwd:return
        args=process['args'];verbs=command_args(args);operand=next((x for x in verbs[1:] if x.endswith('.tar.zst')),None)
        if not operand:return  # remote refs need an authoritative local metadata interface
        bundle=Path(operand) if Path(operand).is_absolute() else Path(cwd)/operand
        sources=[r for r in records if r.get('type')=='REG' and r.get('fd') in ('1','2')]
        complete={r['fd'] for r in sources}=={'1','2'} and len({r['path'] for r in sources})==1
        description='Console output file' if complete else 'Partial redirected console stream; not all terminal output is available'
        sources.sort(key=lambda r:r['fd']!='2')
        from .output import active_capture
        capture=None
        if not sources:
            capture=active_capture(process['pid'],open_files)
            if capture and capture.get('pending'):
                first=self.capture_wait.setdefault(process['pid'],time.monotonic())
                if time.monotonic()-first<2:return
                capture=None
            if capture:
                pipes=[r for r in records if r.get('fd') in ('1','2') and r.get('type') in ('PIPE','FIFO')]
                keys={pipe_key(r) for r in pipes}
                complete={r['fd'] for r in pipes}=={'1','2'} and None not in keys and len(keys)==1
                if complete:
                    sources=[dict(fd='1',type='REG',path=str(capture['path']))]
                    description='Task-captured stdout/stderr; full CLI session'
                else:capture=None  # Never bind an unrelated/split pipe to a full capture.
        if not sources:
            sources=task_console(process['pid'])
            if sources:complete=True;description='Task console output file; full task session'
        if not sources:
            description='Native CLI log only; this UDS version omits some console progress'
            sources=[r for r in records if r.get('type')=='REG' and Path(r.get('path','')).name.startswith(('uds-','zarf-')) and r['path'].endswith('.log')]
        if not sources:return
        path=Path(sources[0]['path'])
        if not stat.S_ISREG(path.stat().st_mode) or path.stat().st_uid!=os.getuid():return
        binary=next((r['path'] for r in records if r.get('fd')=='txt' and Path(r.get('path','')).name in ('uds','zarf')),shutil.which(process['tool']))
        definition,packages=metadata(bundle,binary)
        wanted=None
        if process['tool']=='uds' and verbs[:1] in (['deploy'],['d']):
            # v0.40 uses the first StringArray --packages value, with comma-
            # separated aliases. Match its selection, including equals syntax.
            for i,arg in enumerate(verbs[1:],1):
                value=None
                if arg in ('-p','--packages') and i+1<len(verbs):value=verbs[i+1]
                elif arg.startswith(('--packages=','-p=')):value=arg.split('=',1)[1]
                elif arg.startswith('-p') and not arg.startswith('--'):value=arg[2:]
                if value is not None:wanted=set(value.replace(' ','').split(','));break
        started=None
        try:
            stamp=subprocess.check_output(['ps','-p',str(process['pid']),'-o','lstart='],env=dict(os.environ,LC_ALL='C')).decode().strip()
            started=time.mktime(time.strptime(stamp,'%a %b %d %H:%M:%S %Y'))
        except (ValueError,OSError,subprocess.SubprocessError):pass
        plan=[];run='native-'+str(process['pid'])+'-'+str(int(time.time()*1000000))
        from .model import definition_operations
        for item in definition.get('packages',[]):
            if wanted is not None and item['name'] not in wanted:continue
            package=packages.get(item['name'],{})
            excluded=unselected_components(definition,item,package);components=[]
            for c in package.get('components',[]):
                component=dict(id=c['name'],expected=True,observed=False,status='pending',started_at=None,completed_at=None,error=None,phases=definition_operations(c,package.get('metadata',{}).get('name')),artifact_info=component_info(c,package.get('metadata',{}).get('name')))
                if c['name'] in excluded:component.update(expected=False,selection='not-selected',selection_evidence='Optional component not selected by the packaged bundle')
                components.append(component)
            plan.append(dict(id=item['name'],name=item['name'],artifact_info=artifact_info(package,item.get('ref')),version=item.get('ref','unknown').split('@')[0],dependencies=[],layer=0,status='unknown',started_at=None,completed_at=None,error=None,operation='Definition; execution is CLI-reported',attempts=[dict(id=item['name']+'-native',number=1,status='unknown',started_at=None,completed_at=None,error=None,execution=dict(schema_version=1,observation='definition-only',components=components))],retry_supported=False,retry_reason='Use the deployment terminal'))
        state=dict(id=run,artifact_info=artifact_info(definition),bundle_name=definition.get('metadata',{}).get('name',bundle.name),version=str(definition.get('metadata',{}).get('version','unknown')),status='deploying',created_at=started if started is not None else time.time(),started_at=started,completed_at=None,heartbeat=None,target='Local CLI process '+str(process['pid']),environment='local',mode='observed',packages=plan,layers={},invocations=[],cursor=0,reports=[],checks=[],source=dict(kind='stock-process',pid=process['pid'],output_complete=complete,single_cli=not description.startswith('Task console output file;'),note=description))
        packages={key:value for key,value in packages.items() if any(p['id']==key for p in plan)}
        documents={'package:'+key:deepcopy(value) for key,value in packages.items() if artifact_info(value)['has_yaml']}
        if definition.get('kind')=='UDSBundle':documents['bundle']=deepcopy(definition)
        self.sessions[run]=dict(capture=capture,documents=documents,pid=process['pid'],file=path.open('rb'),partial=b'',state=state,events=deque(maxlen=500),log_index=[],sequence=0,line_sequence=0,offset=0,checked=0,definitions=packages,binary=binary,action_labels={},owners=definition_owners(packages))
        self.sessions[run]['action_labels']=action_labels(packages)
        self.sessions[run]['action_names']=action_names(packages)
        self.sessions[run]['action_declarations']=action_declarations(packages)
        self.event(self.sessions[run],'process.attached',{})
    def event(self,session,kind,data):
        session['sequence']+=1;session['state']['cursor']=session['sequence']
        identifier=session['sequence']
        if kind=='log':
            session['line_sequence']+=1;identifier=session['line_sequence'];session['state']['log_cursor']=identifier
        single=session['state']['packages'][0] if len(session['state']['packages'])==1 and kind=='log' else None
        session['events'].append(dict(id=identifier,event_cursor=session['sequence'],run=session['state']['id'],type=kind,timestamp=time.time(),data=data,package=single['id'] if single else None,attempt=single['attempts'][0]['id'] if single else None))
    def read(self,session,finished=False):
        output=session['file']
        # bounded per refresh, so a noisy process cannot freeze the viewer
        consumed=0
        for _ in range(4096):
            if consumed>=4*1024*1024:break
            start=output.tell();raw=output.readline(32768)
            if not raw:break
            if len(raw)<32768 and not raw.endswith(b'\n') and not finished:output.seek(start);break
            consumed+=len(raw)
            if session['line_sequence']%128==0:session['log_index'].append((session['line_sequence'],start))
            decoded=raw.decode('utf-8',errors='replace')
            self.event(session,'log',dict(raw=decoded,text=decoded,raw_b64=base64.b64encode(raw).decode(),level='unclassified',process_id=str(session['pid'])))
            item=report(decoded)
            if item:
                if item.get('action_id') in session['action_labels']:item['label']=session['action_labels'][item['action_id']]
                if item.get('action_id') in session.get('action_names',{}):item['resource']=session['action_names'][item['action_id']]
                if item.get('action_id') in session.get('action_declarations',{}):item['declaration_id']=session['action_declarations'][item['action_id']]
                item['timestamp']=time.time();item['log_id']=session['line_sequence']
                item=record_report(session['state'],item,session['owners'])
                if item.get('action_id') in session['action_labels']:item['label']=session['action_labels'][item['action_id']]
                self.event(session,'cli.report',item)
    def check_helm(self,session,emit=True):
        # Read-only, opt-in by explicit watcher KUBECONFIG. Never contact the
        # ambient default cluster context, nor persist any Helm secret/values.
        if session.get('checks_final') or not os.environ.get('KUBECONFIG') or time.monotonic()-session['checked']<3:return
        session['checked']=time.monotonic();targets={}
        for package in session['definitions'].values():
            for component in package.get('components',[]):
                for chart in declared_charts(component,package.get('metadata',{}).get('name')):
                    namespace=chart.get('namespace');release=chart.get('releaseName',chart.get('name'))
                    if namespace and release:targets.setdefault(namespace,set()).add(release)
        namespaces=sorted(targets);checks=list(session['state']['checks'])
        cursor=session.get('namespace_cursor',0)
        selected=[namespaces[(cursor+i)%len(namespaces)] for i in range(min(2,len(namespaces)))]
        session['namespace_cursor']=cursor+len(selected)
        kubectl=([session['binary'],'tools'] if Path(session['binary']).name=='zarf' else [session['binary'],'zarf','tools'])+['kubectl']
        for namespace in selected:
            try:
                # Project only revision metadata: never decode release values or
                # send secret data into the watcher. One read per namespace.
                columns='custom-columns=RELEASE:.metadata.labels.name,REVISION:.metadata.labels.version,STATUS:.metadata.labels.status,CREATED:.metadata.creationTimestamp'
                output=subprocess.check_output(kubectl+['get','secrets','-n',namespace,'-l','owner=helm','-o',columns,'--no-headers','--request-timeout=1s'],stderr=subprocess.DEVNULL,timeout=2)
                revisions={}
                for line in output.decode().splitlines():
                    fields=line.split()
                    if len(fields)!=4 or fields[0] not in targets[namespace]:continue
                    release,version,status,updated=fields;version=int(version)
                    if release in revisions and revisions[release]['revision']>=version:continue
                    try:current=datetime.datetime.strptime(updated,'%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=datetime.timezone.utc).timestamp()>=session['state']['started_at'] if session['state'].get('started_at') is not None else False
                    except ValueError:current=False
                    revisions[release]=dict(kind='helm-release',name=release,namespace=namespace,revision=version,status=status,evidence='Kubernetes Helm revision metadata',updated_at=updated,current_deployment=current)
                observed=list(revisions.values())
                active={name for name,row in revisions.items() if row['current_deployment'] and row['status']=='deployed'}
                if active:
                    deployments=json.loads(subprocess.check_output(kubectl+['get','deployments','-n',namespace,'-o','json','--request-timeout=1s'],stderr=subprocess.DEVNULL,timeout=2))['items']
                    for deployment in deployments:
                        release=deployment['metadata'].get('annotations',{}).get('meta.helm.sh/release-name')
                        if release not in active:continue
                        desired=deployment['spec'].get('replicas',1);status=deployment.get('status',{})
                        ready=desired>0 and status.get('readyReplicas',0)>=desired and status.get('updatedReplicas',0)>=desired and status.get('observedGeneration',0)>=deployment['metadata']['generation']
                        observed.append(dict(kind='deployment-readiness',name=deployment['metadata']['name'],release=release,namespace=namespace,status='ready' if ready else 'waiting',ready=status.get('readyReplicas',0),desired=desired,evidence='Kubernetes Deployment status',current_deployment=True))
                checks=[c for c in checks if c['namespace']!=namespace]+observed
                if session['state'].get('completed_at'):session.setdefault('final_namespaces',set()).add(namespace)
            except (OSError,ValueError,TypeError,AttributeError,KeyError,subprocess.SubprocessError):continue
        checks.sort(key=lambda c:(c['namespace'],c['kind'],c['name']))
        if checks!=session['state']['checks']:
            session['state']['checks']=checks
            if emit:self.event(session,'cluster.check',{})
        # Freeze terminal observations; later deployments must not rewrite them.
        completed=session['state'].get('completed_at')
        if completed and (time.time()-completed>=30 or set(namespaces)<=session.get('final_namespaces',set()) and all(c['status'] in ('deployed','ready','failed') for c in checks)):session['checks_final']=True
    def list(self):self.refresh();return [deepcopy(s['state']) for s in self.sessions.values() if s['pid'] not in self.excluded]
    def get(self,run):self.refresh();return deepcopy(self.sessions[run]['state'])
    def definition(self,run,package=None):
        self.refresh()
        return document_view(self.sessions[run]['documents']['package:'+package if package else 'bundle'])
    def events(self,run,after=0,package=None,attempt=None,logs=False,before=None,limit=500,latest=False,**filters):
        self.refresh();session=self.sessions[run];limit=min(max(1,limit),1000)
        # Raw original output lives in the CLI's file, not a watcher database.
        if logs:
            if any(filters.get(key) for key in ('component','phase','operation_execution')):return []
            if filters.get('level') not in (None,'','unclassified'):return []
            output=session['file'];position=output.tell();rows=[]
            end=min(session['state'].get('log_cursor',0),before-1 if before is not None else float('inf'))
            start=max(after,end-limit) if latest and not filters.get('search') else after
            point=bisect.bisect_right(session['log_index'],(start,float('inf')))-1
            index,offset=session['log_index'][point] if point>=0 else (0,0)
            output.seek(offset)
            try:
                while index<end:
                    raw=output.readline(32768)
                    if not raw:break
                    index+=1
                    text=raw.decode('utf-8',errors='replace')
                    single=session['state']['packages'][0] if len(session['state']['packages'])==1 else None
                    if package and (not single or package!=single['id']) or attempt and (not single or attempt!=single['attempts'][0]['id']):continue
                    if index<=after or before is not None and index>=before:continue
                    if filters.get('search') and filters['search'].lower() not in text.lower():continue
                    row=dict(id=index,run=run,type='log',timestamp=session['state']['created_at'],package=single['id'] if single else None,attempt=single['attempts'][0]['id'] if single else None,data=dict(raw=text,text=text,raw_b64=base64.b64encode(raw).decode(),level='unclassified'))
                    rows.append(row)
                    if latest and len(rows)>limit:rows.pop(0)
                    elif not latest and len(rows)>=limit:break
            finally:output.seek(position)
            return rows
        rows=[deepcopy(e) for e in session['events'] if e['event_cursor']>after and (before is None or e['event_cursor']<before)]
        if rows and rows[0]['event_cursor']>after+1:
            cursor=rows[0]['event_cursor']-1
            rows.insert(0,dict(id=cursor,event_cursor=cursor,run=run,type='observer.gap',timestamp=time.time(),package=None,attempt=None,data={'reason':'Live event buffer advanced; original file remains available'}))
        return rows[-limit:] if latest else rows[:limit]
    def close(self):
        for session in self.sessions.values():session['file'].close()
