"""Consent-based shell setup. Never executes existing shell configuration."""
import json
import os
from pathlib import Path
import shlex
import shutil
import stat
import subprocess
import tempfile

START=b'# >>> uds-watch capture >>>'
END=b'# <<< uds-watch capture <<<'
MAX_RC=2*1024*1024


def config_home():
    return Path(os.environ.get('XDG_CONFIG_HOME',str(Path.home()/'.config')))/'uds-watch'


def private_directory(path):
    if path.is_symlink():raise ValueError('Setup directory cannot be a symlink')
    path.mkdir(mode=0o700,parents=True,exist_ok=True)
    info=path.stat()
    if info.st_uid!=os.getuid() or stat.S_IMODE(info.st_mode)&0o077:raise ValueError('Setup directory must be private and owned by you')
    return path


def read_file(path):
    if path.is_symlink():raise ValueError('Startup file is a symlink; use shell-init manually or select its real path with --rc-file')
    try:fd=os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0))
    except FileNotFoundError:return None,0o600
    with os.fdopen(fd,'rb') as stream:
        info=os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_nlink!=1:raise ValueError('Startup file must be regular, owned by you, and without hard links')
        if not info.st_mode&stat.S_IWUSR:raise ValueError('Startup file is read-only; configure it manually')
        if info.st_size>MAX_RC:raise ValueError('Startup file is too large for automatic setup; use shell-init manually')
        return stream.read(),stat.S_IMODE(info.st_mode)


def targets(shell,rc_file=None,all_login=False):
    if rc_file:return [Path(rc_file).expanduser().absolute()]
    home=Path.home()
    if shell=='zsh':return [Path(os.environ.get('ZDOTDIR') or home)/'.zshrc']
    if shell!='bash':raise ValueError('Automatic setup supports Bash and zsh only')
    login=[home/name for name in ('.bash_profile','.bash_login','.profile')]
    if all_login:return [home/'.bashrc']+login
    return [home/'.bashrc',next((path for path in login if path.exists() or path.is_symlink()),login[0])]


def split_block(data):
    data=data or b''
    starts=data.count(START);ends=data.count(END)
    if not starts and not ends:return None
    if starts!=1 or ends!=1:raise ValueError('Ambiguous or incomplete managed block; no startup files were changed')
    begin=data.index(START);end=data.index(END)
    if end<begin or begin and data[begin-1:begin]!=b'\n':raise ValueError('Invalid managed block boundary')
    end+=len(END)
    if end<len(data) and data[end:end+1]!=b'\n':raise ValueError('Invalid managed block boundary')
    if data[end:end+1]==b'\n':end+=1
    return data[:begin],data[begin:end],data[end:]


def block(launcher,shell,tool,created,separator):
    command=shlex.quote(str(Path(launcher).absolute()))
    tools=('uds','zarf') if tool=='both' else (tool,)
    lines=[START.decode(),'# Output-only hook; native CLI binaries and configuration are unchanged.',
           '# uds-watch created-file: '+('yes' if created else 'no'),
           '# uds-watch separator: '+('yes' if separator else 'no')]
    # Guard against moved/removed clones and missing CLIs. A setup failure must
    # not stop a user's shell, including shells configured with errexit.
    version='BASH_VERSION' if shell=='bash' else 'ZSH_VERSION'
    lines+=['if [ -n "${'+version+'-}" ] && [ -x '+command+' ]; then']
    for binary in tools:
        lines+=['  if command -v '+binary+' >/dev/null 2>&1; then',
                '    if _uds_watch_code="$('+command+' shell-init --shell '+shell+' --tool '+binary+' 2>/dev/null)"; then',
                '      eval "$_uds_watch_code" || :','    fi','  fi']
    lines+=['  unset _uds_watch_code','fi',END.decode()]
    return ('\n'.join(lines)+'\n').encode()


def validate(shell,data):
    executable=shutil.which(shell)
    if not executable:raise ValueError('The selected shell is not installed')
    env={key:value for key,value in os.environ.items() if key in ('PATH','LANG','LC_ALL','TMPDIR')}
    flags=['--noprofile','--norc','-n'] if shell=='bash' else ['-f','-n']
    with tempfile.TemporaryDirectory(prefix='uds-watch-syntax-') as home:
        env.update(HOME=home,ZDOTDIR=home)
        result=subprocess.run([executable]+flags,input=data,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,env=env,timeout=5)
    if result.returncode:raise ValueError('Shell syntax validation failed; no startup files were changed. Use shell-init manually.')


def replace_file(path,original,data,mode):
    current,_=read_file(path)
    if current!=original:raise ValueError('Startup file changed during setup; retry without concurrent editing')
    if data is None:
        path.unlink();return
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(prefix='.uds-watch-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as stream:
            os.fchmod(stream.fileno(),mode);stream.write(data);stream.flush();os.fsync(stream.fileno())
        if original is None:os.link(name,path)  # Never overwrite a concurrently created file.
        else:os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)


def apply(shell,changes):
    # Validate every affected file before changing any of them. Backups contain
    # opaque startup bytes, may be sensitive, and are never printed or executed.
    for path,original,data,mode in changes:
        validate(shell,original or b'')
        validate(shell,data or b'')
    if changes:private_directory(config_home())
    backups=[]
    for path,original,data,mode in changes:
        if original is None:continue
        directory=private_directory(config_home());directory=private_directory(directory/'backups')
        fd,name=tempfile.mkstemp(prefix=path.name+'-',dir=directory)
        with os.fdopen(fd,'wb') as stream:stream.write(original)
        backups.append(Path(name))
    applied=[]
    try:
        for path,original,data,mode in changes:
            replace_file(path,original,data,mode);applied.append((path,original,data,mode))
    except BaseException:
        for path,original,data,mode in reversed(applied):
            replace_file(path,data,original,mode)
        raise
    return dict(files=[path for path,_,_,_ in changes],backups=backups)


def install(launcher,shell,tool='both',rc_file=None):
    changes=[]
    for path in targets(shell,rc_file):
        original,mode=read_file(path);parts=split_block(original)
        if parts:
            prefix,previous,suffix=parts
            created=b'# uds-watch created-file: yes\n' in previous
            separator=b'# uds-watch separator: yes\n' in previous
        else:
            prefix=original or b'';suffix=b'';created=original is None
            separator=bool(prefix and not prefix.endswith(b'\n'))
            if separator:prefix+=b'\n'
        data=prefix+block(launcher,shell,tool,created,separator)+suffix
        if data!=original:changes.append((path,original,data,mode))
    return apply(shell,changes)


def uninstall(shell,rc_file=None):
    changes=[]
    for path in targets(shell,rc_file,all_login=True):
        # Do not inspect unrelated symlink-managed login files.
        if path.is_symlink():continue
        original,mode=read_file(path);parts=split_block(original)
        if not parts:continue
        prefix,previous,suffix=parts
        if not suffix and b'# uds-watch separator: yes\n' in previous and prefix.endswith(b'\n'):prefix=prefix[:-1]
        data=prefix+suffix
        if not data and b'# uds-watch created-file: yes\n' in previous:data=None
        changes.append((path,original,data,mode))
    return apply(shell,changes)


def configured(shell):
    try:return any(split_block(read_file(path)[0]) for path in targets(shell))
    except (OSError,ValueError):return False


def preference(value=None):
    path=config_home()/'preferences.json'
    if value is None:
        try:
            data,_=read_file(path)
            value=json.loads(data or b'{}')
            return value.get('capture_setup') if isinstance(value,dict) else None
        except (OSError,ValueError):return None
    directory=private_directory(config_home());data=(json.dumps({'capture_setup':value})+'\n').encode()
    original,_=read_file(path);replace_file(directory/'preferences.json',original,data,0o600)
