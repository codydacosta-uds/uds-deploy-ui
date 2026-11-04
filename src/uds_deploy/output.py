# Shared output-only capture protocol for standalone and integrated viewers.
"""Output-only task tee. Never launches, signals, schedules, or retries a deploy."""
import json
import os
from pathlib import Path
import shutil
import shlex
import subprocess
import stat
import sys
import tempfile


def output_home():
    override=os.environ.get('UDS_DEPLOY_RUNTIME_DIR')
    return Path(override)/'output' if override else Path(tempfile.gettempdir())/('uds-watch-output-'+str(os.getuid()))


def capture_homes():
    """Read only this viewer's configured capture namespace."""
    return [output_home()]


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
