"""Explicit, reversible registration of native CLI entrypoints.

Never invoked by a viewer GET. Never edits a binary's bytes, runs user startup
configuration, or installs a service. Development/tests use isolated copies.
"""
import hashlib
import json
import os
from pathlib import Path
import stat
import struct
import subprocess
import platform
import sys
import tempfile
import uuid

MARKER=b'UDSWATCH_ENTRY_V2'
MAGIC=(b'\x7fELF',b'\xcf\xfa\xed\xfe',b'\xce\xfa\xed\xfe',b'\xfe\xed\xfa\xcf',b'\xfe\xed\xfa\xce',b'\xca\xfe\xba\xbe',b'\xca\xfe\xba\xbf')


def canonical(path):
    path=Path(path).expanduser()
    return path.parent.resolve()/path.name  # Never follow a selected file symlink.


def configuration(path):
    path=Path(path)
    if path.is_symlink():raise ValueError('Register the real CLI file, not a symlink')
    with path.open('rb') as stream:
        info=os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o022:raise ValueError('CLI entrypoint must be regular, owned by you, and not writable by other users')
        if info.st_size>1024*1024:return None
        data=stream.read()
    from .output import entrypoint_config
    config=entrypoint_config(path)
    if MARKER in data and config is None:raise ValueError('Registered CLI launcher was edited; no files changed')
    return config


def preflight(path):
    path=canonical(path)
    if path.name not in ('uds','zarf'):raise ValueError('Select an executable named uds or zarf')
    if path.is_symlink():raise ValueError('Register the real CLI file, not a symlink')
    info=path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_nlink!=1:raise ValueError('CLI must be a regular, owned file without hard links')
    if info.st_mode&(stat.S_ISUID|stat.S_ISGID|0o022):raise ValueError('Privileged or externally writable CLI files cannot be registered')
    if not info.st_mode&stat.S_IXUSR or not os.access(path.parent,os.W_OK):raise ValueError('CLI and its directory must be writable/owned for reversible registration; do not use sudo to bypass this check')
    config=configuration(path)
    if config:return path,info,config
    with path.open('rb') as stream:
        if stream.read(4) not in MAGIC:raise ValueError('Only native ELF/Mach-O UDS/Zarf executables can be registered; scripts are left unchanged')
    return path,info,None


def bootstrap_binary():
    arch={'amd64':'x86_64','arm64':'arm64' if sys.platform=='darwin' else 'aarch64'}.get(platform.machine(),platform.machine())
    path=Path(__file__).parent/'bootstrap'/(sys.platform+'-'+arch)
    if not path.is_file():raise ValueError('This distribution lacks a CLI bootstrap for your platform; no CLI files changed')
    manifest=json.loads(path.with_name('manifest.json').read_text())
    if manifest.get('sha256',{}).get(path.name)!=hashlib.sha256(path.read_bytes()).hexdigest():raise ValueError('CLI bootstrap integrity check failed; no CLI files changed')
    try:result=subprocess.run([str(path),'--uds-watch-bootstrap-probe-v1'],capture_output=True,timeout=3)
    except (OSError,subprocess.SubprocessError) as error:raise ValueError('CLI bootstrap cannot run on this platform/ABI; no CLI files changed') from error
    if result.returncode:raise ValueError('CLI bootstrap cannot run on this platform/ABI; no CLI files changed')
    return path


def program(config):
    fields=[config[key] for key in ('entry','native','python','bootstrap','package','tool')]+[str(config['uid'])]
    payload=b'\0'.join(os.fsencode(value) for value in fields)+b'\0'
    template=bootstrap_binary().read_bytes();offset=template.find(b'UDSWATCH_PLACEHOLDER_V2')
    if offset<0:raise ValueError('Invalid CLI bootstrap template')
    block=payload+MARKER+struct.pack('<I',len(payload))+hashlib.sha256(payload).hexdigest().encode()
    if len(block)>65536:raise ValueError('CLI registration metadata exceeds safe bound')
    return template[:offset]+block.ljust(65536,b'\0')+template[offset+65536:]


def runtime_program(config):
    bootstrap=Path(__file__).with_name('entrypoint_bootstrap.py').read_bytes()
    tail=b'\nif __name__=="__main__":\n    raise SystemExit(relay(CONFIG,int(sys.argv[2]),int(sys.argv[3]),sys.argv[4:]))\n'
    return b'CONFIG = '+repr(config).encode()+b'\n'+bootstrap+tail


def interpreter_image():
    if sys.platform=='linux':return os.readlink('/proc/self/exe')
    import ctypes
    libc=ctypes.CDLL(None);size=ctypes.c_uint32(4096);buffer=ctypes.create_string_buffer(size.value)
    if libc._NSGetExecutablePath(buffer,ctypes.byref(size)):raise ValueError('Cannot verify the Python interpreter image')
    return os.fsdecode(buffer.value)


def identity(info):return (info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns,info.st_mode,info.st_uid,info.st_nlink)


def register(path):
    if sys.version_info<(3,10):raise ValueError('CLI registration requires Python 3.10 or newer')
    path,info,previous=preflight(path)
    bootstrap_binary()  # No compiler/download/install side effects at setup time.
    if previous:return dict(entry=path,native=Path(previous['native']),changed=False)
    assert_idle(dict(native=str(path)))
    directory=path.parent/('.'+path.name+'.uds-watch-native-'+uuid.uuid4().hex)
    directory.mkdir(mode=0o755)
    native=directory/path.name;name=None
    moved=False;published=False
    try:
        config=dict(tool=path.name,entry=str(path),native=str(native),uid=os.getuid(),package=str(Path(__file__).parent),python=sys.executable,python_image=interpreter_image(),bootstrap=str(directory/'invoke.py'))
        (directory/'invoke.py').write_bytes(runtime_program(config));(directory/'invoke.py').chmod(0o644)
        data=program(config);fd,name=tempfile.mkstemp(prefix='.uds-watch-entry-',dir=path.parent)
        with os.fdopen(fd,'wb') as stream:
            os.fchmod(stream.fileno(),stat.S_IMODE(info.st_mode));stream.write(data);stream.flush();os.fsync(stream.fileno())
        if sys.platform=='darwin':subprocess.run(['/usr/bin/codesign','--force','--sign','-',name],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        registry=directory/'registration.json'
        registry.write_text(json.dumps(dict(config,entry_sha256=hashlib.sha256(Path(name).read_bytes()).hexdigest(),bootstrap_sha256=hashlib.sha256((directory/'invoke.py').read_bytes()).hexdigest())));registry.chmod(0o600)
        if identity(path.stat())!=identity(info):raise ValueError('Native CLI changed during registration; no replacement attempted')
        os.rename(path,native);moved=True
        os.link(name,path);published=True
        return dict(entry=path,native=native,changed=True)
    except BaseException:
        if moved and not published and not path.exists():os.rename(native,path)
        if not native.exists():__import__('shutil').rmtree(directory)
        raise
    finally:
        if name is not None and os.path.exists(name):os.unlink(name)


def unregister(path):
    path=canonical(path);config=configuration(path)
    if config is None:raise ValueError('Selected path is not a managed CLI entrypoint; no files changed')
    original=path.read_bytes();native=Path(config['native']);info=native.stat()
    if native.is_symlink() or not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_nlink!=1 or info.st_mode&(stat.S_ISUID|stat.S_ISGID|0o022):raise ValueError('Preserved native CLI identity/permissions are no longer safe')
    assert_idle(config)
    # Respect a native self-update: restore the executable currently behind the
    # launcher, never overwrite it with an old saved copy.
    if path.read_bytes()!=original:raise ValueError('CLI entrypoint changed during uninstall')
    os.replace(native,path)
    script=Path(config['bootstrap'])
    if script.is_file() and hashlib.sha256(script.read_bytes()).hexdigest()==config.get('bootstrap_sha256'):script.unlink()
    (native.parent/'registration.json').unlink()
    try:native.parent.rmdir()
    except OSError:pass  # Preserve unrelated or edited user files in that directory.
    return path


def assert_idle(config):
    # Moving a live UDS executable can break its later self-invocations. Never
    # uninstall during a command; inspect executable metadata, not its output.
    result=subprocess.run(['lsof','-t','-a','-d','txt','--',config['native']],capture_output=True,timeout=3)
    if result.returncode not in (0,1):raise ValueError('Cannot verify that the preserved CLI is idle; no files changed')
    if result.stdout.strip():raise ValueError('CLI is running; wait for it to finish before uninstalling')


def selected(tool='both'):
    import shutil
    result=[]
    for name in (('uds','zarf') if tool=='both' else (tool,)):
        binary=shutil.which(name)
        for candidate in ([Path(binary)] if binary else [])+[Path.cwd()/name]:
            if candidate.is_file():
                candidate=candidate.resolve()
                if candidate not in result:result.append(candidate)
    return result


def registered():
    from .setup import config_home,read_file
    data,_=read_file(config_home()/'cli-registrations.json')
    if data is None:return []
    value=json.loads(data)
    paths=value.get('entrypoints') if isinstance(value,dict) else None
    if not isinstance(paths,list) or not all(isinstance(path,str) and Path(path).is_absolute() for path in paths):raise ValueError('Invalid CLI registration list')
    return [Path(path) for path in paths]


def save_registered(paths):
    from .setup import config_home,private_directory,read_file,replace_file
    home=private_directory(config_home());path=home/'cli-registrations.json';original,_=read_file(path)
    replace_file(path,original,(json.dumps({'entrypoints':[str(path) for path in paths]})+'\n').encode(),0o600)


def install_many(paths):
    paths=list(dict.fromkeys(canonical(path) for path in paths))
    if not paths:raise ValueError('No UDS/Zarf executable found; supply --cli /path/to/uds')
    for path in paths:preflight(path)
    previous=registered();created=[];result=[]
    try:
        for path in paths:
            item=register(path);result.append(item)
            if item['changed']:created.append(path)
        save_registered(list(dict.fromkeys(previous+paths)))
    except BaseException:
        for path in reversed(created):unregister(path)
        raise
    return result


def uninstall_many(paths=None):
    previous=registered();paths=list(dict.fromkeys(canonical(path) for path in (paths or previous)))
    for path in paths:
        if configuration(path) is None:raise ValueError('CLI entrypoint was replaced outside setup; no files changed')
        config=configuration(path);native=Path(config['native'])
        if native.is_symlink() or not native.is_file() or native.stat().st_uid!=os.getuid() or native.stat().st_nlink!=1 or native.stat().st_mode&(stat.S_ISUID|stat.S_ISGID|0o022):raise ValueError('Preserved native CLI is not safe to restore')
        assert_idle(config)
    restored=[unregister(path) for path in paths]
    save_registered([path for path in previous if path not in restored])
    return restored


def configured():
    try:return bool(registered()) and all(configuration(path) is not None for path in registered())
    except (OSError,ValueError):return False
