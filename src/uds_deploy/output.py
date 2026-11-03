# Shared output-only capture protocol for standalone and integrated viewers.
"""Output-only task tee. Never launches, signals, schedules, or retries a deploy."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import shlex
import subprocess
import stat
import struct
import sys
import tempfile


def output_home():
    override=os.environ.get('UDS_DEPLOY_RUNTIME_DIR')
    return Path(override)/'output' if override else Path(tempfile.gettempdir())/('sonic-deploy-output-'+str(os.getuid()))


def capture_homes():
    """Read known capture namespaces without changing where this helper writes."""
    home=output_home()
    if os.environ.get('UDS_DEPLOY_RUNTIME_DIR'):return [home]
    return [home,Path(tempfile.gettempdir())/('uds-watch-output-'+str(os.getuid()))]


def capture_helper(args):
    # Identity alone is not authorization: below we also validate same-user
    # ancestry, private files, held log descriptor, and (in NativeReader) pipes.
    scripts=any(Path(arg).name=='deploy-output.py' or Path(arg).name=='capture.py' and Path(arg).parent.name=='uds_deploy' for arg in args[1:])
    entrypoint=any(Path(arg).name=='uds-watch' and args[i+1:i+2]==['capture'] for i,arg in enumerate(args))
    return scripts or entrypoint


def pipe_identity(record):
    inode=record.get('inode')
    if inode and inode!='0':return ('inode',inode)
    path=record.get('path')
    device=record.get('device','')
    if device.startswith('0x') and path and path.startswith('->0x'):
        try:return ('peers',tuple(sorted((int(device,16),int(path[2:],16)))))
        except ValueError:return None
    return ('path',path) if path and path not in ('pipe','FIFO') else None


def open_capture():
    override=os.environ.get('UDS_DEPLOY_RUNTIME_DIR')
    if override:
        runtime=Path(override)
        if runtime.is_symlink():raise ValueError('Runtime directory cannot be a symlink')
        runtime.mkdir(mode=0o700,parents=True,exist_ok=True)
        if runtime.stat().st_uid!=os.getuid() or stat.S_IMODE(runtime.stat().st_mode)&0o077:raise ValueError('Runtime directory must be private and owned by you')
    home=output_home()
    if home.is_symlink():raise ValueError('Capture directory cannot be a symlink')
    home.mkdir(mode=0o700,parents=True,exist_ok=True)
    if home.stat().st_uid!=os.getuid() or stat.S_IMODE(home.stat().st_mode)&0o077:raise ValueError('Capture directory must be private and owned by you')
    # A killed tee may leave data; it is not saved history. Only remove a dead
    # capture owner on the next task, never another live task's files.
    for record in home.glob('*/capture.json'):
        try:
            if record.is_symlink() or record.parent.is_symlink() or record.stat().st_uid!=os.getuid():continue
            data=json.loads(record.read_text())
            try:os.kill(data['pid'],0)
            except ProcessLookupError:shutil.rmtree(str(record.parent))
        except (OSError,ValueError,KeyError,TypeError):continue
    directory=Path(tempfile.mkdtemp(prefix='console-',dir=str(home)))
    try:
        stream=(directory/'console.log').open('xb');os.chmod(str(directory/'console.log'),0o600)
        fd=os.open(str(directory/'capture.json'),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w') as record:json.dump(dict(pid=os.getpid(),shell_pid=os.getppid(),stream='stdout+stderr'),record)
        return directory,stream
    except BaseException:
        shutil.rmtree(str(directory));raise


def entrypoint_config(path):
    path=Path(path)
    if path.is_symlink():return None
    info=path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o022 or info.st_size>1024*1024:return None
    data=path.read_bytes();marker=b'UDSWATCH_ENTRY_V2';end=len(data);fields=None
    while end:
        offset=data.rfind(marker,0,end)
        if offset<0:break
        end=offset
        if offset+len(marker)+68>len(data):continue
        length=struct.unpack_from('<I',data,offset+len(marker))[0]
        if not 0<length<=65536 or length>offset:continue
        payload=data[offset-length:offset]
        if hashlib.sha256(payload).hexdigest().encode()!=data[offset+len(marker)+4:offset+len(marker)+68]:continue
        fields=payload.rstrip(b'\0').split(b'\0')
        if len(fields)==7:break
        fields=None
    if fields is None:return None
    value=dict(zip(('entry','native','python','bootstrap','package','tool','uid'),map(os.fsdecode,fields)))
    if value['uid']!=str(os.getuid()) or value['tool'] not in ('uds','zarf'):return None
    registry=Path(value['native']).parent/'registration.json'
    if registry.is_symlink() or registry.stat().st_uid!=os.getuid() or stat.S_IMODE(registry.stat().st_mode)&0o077 or registry.stat().st_size>65536:return None
    trusted=json.loads(registry.read_text())
    if trusted.get('entry_sha256')!=hashlib.sha256(data).hexdigest() or any(str(trusted.get(key))!=val for key,val in value.items()):return None
    if path.resolve()!=Path(value['entry']).resolve():return None
    return trusted


def registered_deployments():
    found={}
    for home in capture_homes():
        try:
            if home.is_symlink() or not home.exists() or home.stat().st_uid!=os.getuid() or stat.S_IMODE(home.stat().st_mode)&0o077:continue
            for record in home.glob('*/capture.json'):
                try:
                    if record.is_symlink() or record.parent.is_symlink() or record.stat().st_uid!=os.getuid() or stat.S_IMODE(record.stat().st_mode)&0o077:continue
                    data=json.loads(record.read_text())
                    if data.get('producer')!='registered-cli-v1' or type(data.get('native_pid'))!=int:continue
                    config=entrypoint_config(data['entry_path'])
                    if config and config['native']==data.get('native_path') and isinstance(data.get('metadata_args'),list) and all(isinstance(arg,str) for arg in data['metadata_args']):found[data['native_pid']]=dict(tool=config['tool'],args=data['metadata_args'])
                except (OSError,ValueError,TypeError,KeyError):continue
        except OSError:continue
    return found


def active_capture(deploy_pid,open_files):
    """Validate a live sibling tee and its held private log, without pipe reads."""
    homes=[]
    for home in capture_homes():
        try:
            if home.is_symlink():continue
            if home.exists() and (home.stat().st_uid!=os.getuid() or stat.S_IMODE(home.stat().st_mode)&0o077):continue
            homes.append(home)
        except OSError:continue
    if not homes:return None
    rows={}
    output=subprocess.check_output(['ps','-axo','pid=,ppid=,uid=,args='],timeout=3).decode('utf-8',errors='replace')
    for line in output.splitlines():
        fields=line.strip().split(None,3)
        if len(fields)==4:rows[int(fields[0])]=fields
    deploy=rows.get(deploy_pid)
    if not deploy:return None
    parent=int(deploy[1]);uid=str(os.getuid());matches=[]
    # An explicitly registered CLI entrypoint owns these newly allocated output
    # channels. Validate its immutable launcher, native child and held log; never
    # open the native process's terminal or output channel ourselves.
    for record in [record for home in homes for record in home.glob('*/capture.json')]:
        try:
            if record.is_symlink() or record.parent.is_symlink() or record.stat().st_uid!=os.getuid() or stat.S_IMODE(record.stat().st_mode)&0o077:continue
            data=json.loads(record.read_text())
            if data.get('producer')!='registered-cli-v1' or data.get('native_pid')!=deploy_pid or type(data.get('pid'))!=int:continue
            pid=data['pid'];producer=rows.get(pid)
            if not producer or producer[2]!=uid or deploy[2]!=uid or data.get('shell_pid')!=deploy_pid:continue
            guardian=rows.get(data.get('guardian_pid'))
            if not guardian or guardian[2]!=uid or int(guardian[1])!=deploy_pid or int(producer[1])!=int(guardian[0]):continue
            config=entrypoint_config(data['entry_path'])
            if not config or config['native']!=data.get('native_path'):continue
            script=Path(config['bootstrap'])
            if script.is_symlink() or not script.is_file() or script.stat().st_uid!=os.getuid() or script.stat().st_mode&0o022 or hashlib.sha256(script.read_bytes()).hexdigest()!=config.get('bootstrap_sha256'):continue
            files=open_files(pid);cwd=next((r['path'] for r in files if r.get('fd')=='cwd'),None)
            # ps does not quote argv paths containing spaces. Validate the
            # held interpreter executable and the registered bootstrap path,
            # rather than treating this display string as shell-quoted argv.
            if config['bootstrap'] not in producer[3] or config['entry'] not in producer[3]:continue
            if not any(r.get('fd') in ('txt','mem') and r.get('type')=='REG' and Path(r.get('path','')).resolve()==Path(config['python_image']).resolve() for r in files):continue
            native=Path(config['native']);identity=native.stat()
            if identity.st_ino!=data.get('native_inode') or identity.st_dev!=data.get('native_device'):continue
            if not any(r.get('fd')=='txt' and r.get('type')=='REG' and Path(r.get('path','')).resolve()==native.resolve() for r in open_files(deploy_pid)):continue
            path=record.parent/'console.log'
            if path.is_symlink() or not path.is_file() or path.stat().st_uid!=os.getuid() or stat.S_IMODE(path.stat().st_mode)&0o077:continue
            if not any(r.get('type')=='REG' and Path(r.get('path','')).resolve()==path.resolve() for r in files):continue
            integrity=record.parent/'integrity'
            if integrity.is_symlink() or not integrity.is_file() or integrity.stat().st_uid!=os.getuid() or stat.S_IMODE(integrity.stat().st_mode)&0o077:continue
            matches.append(dict(integrity=integrity,path=path,pid=pid,record=record,registered_stdio=True,task_root=data.get('task_root',False),deployments=data.get('deployments',[]),task_ambiguous=data.get('task_ambiguous',False),native_pid=deploy_pid))
        except (OSError,ValueError,KeyError,TypeError):continue
    if matches:return matches[0] if len(matches)==1 else None
    producer=rows.get(parent)
    if producer and producer[2]==uid:
        try:
            files=open_files(parent);cwd=next((r['path'] for r in files if r.get('fd')=='cwd'),'.')
            for arg in shlex.split(producer[3])[1:]:
                if arg.startswith('-'):continue
                candidate=Path(arg) if Path(arg).is_absolute() else Path(cwd)/arg
                if candidate.is_file() and entrypoint_config(candidate):return {'pending':True}
        except (OSError,ValueError,TypeError):pass
    pipes=[row for row in open_files(deploy_pid) if row.get('fd') in ('1','2') and row.get('type') in ('PIPE','FIFO')]
    identities={pipe_identity(row) for row in pipes}
    if {row['fd'] for row in pipes}!={'1','2'} or None in identities or len(identities)!=1:return None
    pipe=next(iter(identities))
    def sibling(owner):
        return owner==parent or owner in rows and rows[owner][2]==uid and int(rows[owner][1])==parent
    for record in [record for home in homes for record in home.glob('*/capture.json')]:
        try:
            if record.is_symlink() or record.parent.is_symlink() or record.stat().st_uid!=os.getuid() or stat.S_IMODE(record.stat().st_mode)&0o077:continue
            data=json.loads(record.read_text());pid=data['pid'];shell=data['shell_pid']
            if type(pid)!=int or type(shell)!=int or not sibling(shell):continue
            helper=rows.get(pid)
            if not helper or helper[2]!=uid or int(helper[1])!=shell:continue
            args=shlex.split(helper[3])
            if not capture_helper(args):continue
            path=record.parent/'console.log'
            if path.is_symlink() or path.stat().st_uid!=os.getuid() or not path.is_file() or stat.S_IMODE(path.stat().st_mode)&0o077:continue
            files=open_files(pid)
            if not any(r.get('fd')=='0' and r.get('type') in ('PIPE','FIFO') and pipe_identity(r)==pipe for r in files):continue
            if not any(r.get('type')=='REG' and Path(r.get('path','')).resolve()==path.resolve() for r in files):continue
            matches.append(dict(path=path,pid=pid,record=record))
        except (OSError,ValueError,KeyError,TypeError):continue
    if len(matches)==1:return matches[0]
    # The pipeline logger can start just before its registration is flushed.
    # Defer observation, not execution, rather than locking onto a partial log.
    for pid,row in rows.items():
        try:
            if row[2]==uid and sibling(int(row[1])) and capture_helper(shlex.split(row[3])):return {'pending':True}
        except ValueError:pass
    return None


def copy_output(source,destination):
    """Pass bytes through even if optional file capture or console output fails."""
    directory=stream=None;console=True;warned=False
    def warn():
        nonlocal warned
        if warned:return
        warned=True
        try:sys.stderr.write('Watcher output capture unavailable; deployment output continues in the terminal.\n');sys.stderr.flush()
        except OSError:pass
    try:
        try:directory,stream=open_capture()
        except (OSError,ValueError):warn()
        read=getattr(source,'read1',source.read)
        while True:
            chunk=read(32768)
            if not chunk:break
            if stream is not None:
                try:stream.write(chunk);stream.flush()
                except OSError:
                    warn()
                    try:(directory/'capture.json').unlink()
                    except OSError:pass
                    try:stream.close()
                    except OSError:pass
                    stream=None
            if console:
                try:destination.write(chunk);destination.flush()
                except OSError:console=False  # Do not close the deployment's pipe.
    finally:
        if stream is not None:
            try:stream.close()
            except OSError:pass
        if directory is not None:
            try:shutil.rmtree(str(directory))
            except OSError:pass
    return 0
