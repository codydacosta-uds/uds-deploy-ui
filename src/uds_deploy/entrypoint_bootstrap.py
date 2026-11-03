"""Output-only child for an explicitly registered CLI invocation.

The native bootstrap parent execs UDS itself: this child never launches, waits
for, retries, cancels, or signals the deployment. It never reads stdin or an
existing deployment's TTY/pipe. Only newly allocated invocation-owned output
channels are read. Original argv/environment never pass through Python.
"""
import array
import json
import os
from pathlib import Path
import selectors
import signal
import socket
import stat
import struct
import sys
import subprocess
import time


def channels():
    import fcntl
    import pty
    import termios
    first,second=os.fstat(1),os.fstat(2)
    same=(first.st_dev,first.st_ino,first.st_rdev)==(second.st_dev,second.st_ino,second.st_rdev)
    combined=same and (os.isatty(1) or stat.S_ISFIFO(first.st_mode))
    result=[]
    try:
        for target in ((1,) if combined else (1,2)):
            if os.isatty(target):
                reader,writer=pty.openpty()
                attrs=termios.tcgetattr(writer);attrs[1]&=~termios.OPOST;termios.tcsetattr(writer,termios.TCSANOW,attrs)
                fcntl.ioctl(writer,termios.TIOCSWINSZ,fcntl.ioctl(target,termios.TIOCGWINSZ,b'\0'*8))
            else:reader,writer=os.pipe()
            result.append(dict(reader=reader,writer=writer,target=target,terminal=os.isatty(target),window=os.dup(target) if os.isatty(target) else None))
        return result,combined
    except BaseException:
        for entry in result:
            for name in ('reader','writer'):
                try:os.close(entry[name])
                except OSError:pass
        raise


def relay(config,control_fd,native_pid,argv):
    control=socket.socket(fileno=control_fd)
    # Drop unrelated inherited handles only in this output-only child. Native's
    # process and inherited stdin/other descriptors are unchanged by its parent.
    for name in os.listdir('/dev/fd' if sys.platform=='darwin' else '/proc/self/fd'):
        try:
            fd=int(name)
            if fd not in (1,2,control_fd):os.close(fd)
        except (ValueError,OSError):pass
    for sig in (signal.SIGINT,signal.SIGQUIT,signal.SIGTERM):signal.signal(sig,signal.SIG_IGN)
    streams=[];directory=stream=integrity=None;selector=selectors.DefaultSelector()
    try:
        if os.getuid()!=config['uid'] or not Path(config['package']).is_dir():return 0
        sys.path.insert(0,str(Path(config['package']).parent))
        try:
            from uds_deploy.native import command_args
            from uds_deploy.output import open_capture
            verbs=command_args([config['tool']]+argv[1:])
            direct=config['tool']=='uds' and (verbs[:1] in (['deploy'],['d']) or verbs[:3]==['zarf','package','deploy']) or config['tool']=='zarf' and verbs[:2]==['package','deploy']
            task=config['tool']=='uds' and verbs[:1] in (['run'],['r'])
            if not (direct or task):return 0
            streams,combined=channels();directory,stream=open_capture()
            integrity=(directory/'integrity').open('x+b');os.chmod(directory/'integrity',0o600);integrity.write(b'0');integrity.flush()
            identity=os.stat(config['native'])
            prefix=['zarf','package','deploy'] if verbs[:3]==['zarf','package','deploy'] else ['package','deploy'] if config['tool']=='zarf' else [verbs[0]]
            operand=next((arg for arg in verbs[len(prefix):] if arg.endswith('.tar.zst')),None)
            metadata_args=[config['native']]+prefix+([operand] if operand else [])
            if config['tool']=='uds' and prefix[0] in ('deploy','d'):
                for i,arg in enumerate(verbs):
                    selected=verbs[i+1] if arg in ('-p','--packages') and i+1<len(verbs) else arg.split('=',1)[1] if arg.startswith(('-p=','--packages=')) else arg[2:] if arg.startswith('-p') and not arg.startswith('--') else None
                    if selected is not None:metadata_args+=['--packages',selected];break
            # Inventory selection only: never store arbitrary flags, environment,
            # resolved config/credentials, or the user's full command line.
            record=dict(pid=os.getpid(),shell_pid=native_pid,stream='stdout+stderr',producer='registered-cli-v1',native_pid=native_pid,native_path=config['native'],native_inode=identity.st_ino,native_device=identity.st_dev,entry_path=config['entry'],metadata_args=metadata_args,tool=config['tool'],guardian_pid=os.getppid(),task_root=task,deployments=[])
            registration=directory/'ready.json'
            with registration.open('x') as writer:os.chmod(registration,0o600);json.dump(record,writer)
            os.replace(registration,directory/'capture.json')
            handles=array.array('i',[entry[name] for entry in streams for name in ('reader','writer')])
            control.sendmsg([(b'1' if combined else b'2')],[(socket.SOL_SOCKET,socket.SCM_RIGHTS,handles)])
        except (OSError,ValueError,ImportError):return 0
        for entry in streams:
            os.close(entry.pop('writer'))
            if not entry['terminal']:os.close(entry.pop('reader'))
        null=os.open(os.devnull,os.O_WRONLY)
        os.dup2(null,1);os.dup2(null,2);os.close(null)
        # Sending the path is the readiness ACK: no extra native writer or
        # original pipeline handle remains in Python when native can start.
        control.sendall(os.fsencode(directory/'capture.json')+b'\0')
        selector.register(control,selectors.EVENT_READ)
        # The C forwarder owns the native readers. Python receives only framed
        # copies, never bytes that the native terminal is still waiting for.
        def resized(*_):
            import fcntl,termios
            for entry in streams:
                if entry['terminal']:
                    try:fcntl.ioctl(entry['reader'],termios.TIOCSWINSZ,fcntl.ioctl(entry['window'],termios.TIOCGWINSZ,b'\0'*8))
                    except OSError:pass
        signal.signal(signal.SIGWINCH,resized)
        last_audit=0
        def audit_task():
            nonlocal last_audit
            if not task or time.monotonic()-last_audit<.2:return
            last_audit=time.monotonic()
            try:
                from uds_deploy.native import processes
                rows={}
                for line in subprocess.check_output(['ps','-axo','pid=,ppid=,uid='],timeout=2,stderr=subprocess.DEVNULL).decode().splitlines():
                    fields=line.split()
                    if len(fields)==3 and fields[2]==str(os.getuid()):rows[int(fields[0])]=int(fields[1])
                found=set(record['deployments'])
                for process in processes():
                    current=process['pid']
                    for _ in range(32):
                        current=rows.get(current)
                        if current==native_pid:found.add(process['pid']);break
                        if current is None:break
                record['deployments']=sorted(found)
                if len(found)>1:record['task_ambiguous']=True
                pending=directory/'ready.json'
                with pending.open('w') as writer:os.chmod(pending,0o600);json.dump(record,writer)
                os.replace(pending,directory/'capture.json')
            except (OSError,ValueError,subprocess.SubprocessError):record['task_ambiguous']=True
        pending=bytearray()
        while True:
            audit_task()
            if not selector.select(.2):continue
            chunk=control.recv(65536)
            if not chunk:return 0  # No authenticated EOF frame: integrity stays incomplete.
            pending.extend(chunk)
            while len(pending)>=4:
                size=struct.unpack_from('<I',pending)[0]
                if size>32768:raise ValueError('Invalid capture frame')
                if len(pending)<size+4:break
                if size==0:
                    # A separate held descriptor survives cleanup. Only an
                    # explicit forwarder EOF can certify the complete capture.
                    integrity.seek(0)
                    if integrity.read(1)==b'0':integrity.seek(0);integrity.write(b'1');integrity.flush()
                    return 0
                stream.write(pending[4:size+4]);stream.flush();del pending[:size+4]
    except (OSError,ValueError,ImportError,subprocess.SubprocessError):
        if integrity is not None:
            try:integrity.seek(0);integrity.write(b'!');integrity.flush()
            except OSError:pass
        return 0
    finally:
        selector.close();control.close()
        for entry in streams:
            if entry.get('window') is not None:os.close(entry['window'])
            for name in ('reader','writer'):
                if name in entry:
                    try:os.close(entry[name])
                    except OSError:pass
        if stream is not None:
            try:stream.close()
            except OSError:pass
        if integrity is not None:integrity.close()
        if directory is not None:__import__('shutil').rmtree(directory,ignore_errors=True)
