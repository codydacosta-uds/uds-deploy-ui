"""Read-only viewer and explicitly approved, reversible capture setup."""
import argparse
import errno
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import webbrowser

from . import __version__


def current_shell():
    try:
        name=Path(subprocess.check_output(['ps','-p',str(os.getppid()),'-o','comm='],stderr=subprocess.DEVNULL,timeout=2).decode().strip()).name.lstrip('-')
        if name in ('bash','zsh'):return name
    except (OSError,subprocess.SubprocessError):pass
    return Path(os.environ.get('SHELL','bash')).name


def shell_init(shell,tool):
    binary=shutil.which(tool)
    if not binary:raise ValueError('Install '+tool+' and put it on PATH first')
    if shell not in ('bash','zsh'):raise ValueError('Shell integration supports Bash and zsh; use --shell bash or --shell zsh')
    python=shlex.quote(sys.executable);helper=shlex.quote(str(Path(__file__).with_name('capture.py')))
    native=shlex.quote(binary)
    status='${PIPESTATUS[0]}' if shell=='bash' else '${pipestatus[1]}'
    options='  emulate -L zsh\n' if shell=='zsh' else ''
    return f'''# uds-watch: explicit output-only integration; no shell startup files are edited.
if alias {tool} >/dev/null 2>&1; then
  printf '%s\\n' 'uds-watch: {tool} is already an alias/function; remove it before enabling this hook.' >&2
elif typeset -f {tool} >/dev/null 2>&1; then
  case "$(typeset -f {tool})" in
    *'_uds_watch_wrapper_marker'*) : ;;
    *) printf '%s\\n' 'uds-watch: {tool} is already an alias/function; remove it before enabling this hook.' >&2 ;;
  esac
else
  function {tool}() {{
    (
    # Isolate options: Bash 3.2 errexit otherwise replaces some pipeline statuses.
    set +e
{options}    local _uds_watch_status _uds_watch_wrapper_marker
    if ! {python} {helper} --check-command {tool} "$@"; then
      command {native} "$@"
      return $?
    fi
    if (exec {native} "$@") 2>&1 | ({python} {helper} || command cat); then
      _uds_watch_status="{status}"
    else
      _uds_watch_status="{status}"
    fi
    return "$_uds_watch_status"
    )
  }}
fi
'''


def setup_result(result):
    if not result['files']:print('No startup-file changes needed.')
    for path in result['files']:print('Updated: '+str(path))
    for path in result['backups']:print('Private backup: '+str(path))
    print('Open a NEW deployment terminal for the change to take effect. Existing terminals are unchanged.')


def confirm_setup(prompt):
    if not sys.stdin.isatty():raise ValueError('Non-interactive setup requires --yes')
    try:return input(prompt).strip().lower() in ('y','yes')
    except EOFError:return False


def remember_setup(value):
    from . import setup
    try:setup.preference(value)
    except (OSError,ValueError):print('Setup preference could not be saved; startup-file results above still apply.',file=sys.stderr)


def maybe_setup(disabled=False):
    # Non-interactive launches never inspect or edit startup files or prompt.
    if disabled or not sys.stdin.isatty() or not sys.stdout.isatty():return
    try:
        if os.tcgetpgrp(sys.stdin.fileno())!=os.getpgrp():return  # Never suspend a background viewer for input.
    except (OSError,ValueError):pass  # Embedded terminal streams may not expose a file descriptor.
    from . import setup,entrypoints
    if entrypoints.configured() or setup.preference()=='declined':return
    print('\nEnable automatic capture at your UDS/Zarf CLI entrypoints?')
    print('Setup places reversible launchers at the paths below and preserves each original executable unchanged beside it.')
    print('This covers direct commands, scripts and uds run that invoke these configured executables; it does not edit shell startup or deployment configuration.')
    paths=entrypoints.selected()
    for path in paths:print('  '+str(path))
    try:
        if confirm_setup('Register these CLI paths? [y/N] '):
            for item in entrypoints.install_many(paths):print('Registered: '+str(item['entry']))
            remember_setup('installed')
        else:remember_setup('declined');print('Skipped. You can enable it later with uds-watch setup.')
    except (OSError,ValueError,subprocess.SubprocessError) as error:
        print('Automatic CLI registration unavailable: '+str(error)+'. No deployment was started; the viewer will still open.',file=sys.stderr)


def doctor():
    supported=sys.platform in ('darwin','linux')
    print('Platform: '+('supported' if supported else 'macOS or Linux required'))
    missing=[]
    for tool in ('ps','lsof','zstd'):
        available=shutil.which(tool)
        print(tool+': '+('available' if available else 'missing'))
        if not available:missing.append(tool)
    cli=shutil.which('uds') or shutil.which('zarf')
    print('UDS/Zarf: '+('available' if cli else 'missing'))
    if not cli:missing.append('uds or zarf')
    try:
        from .entrypoints import bootstrap_binary
        bootstrap_binary();print('CLI capture bootstrap: available (no runtime compiler/download)')
    except (OSError,ValueError,subprocess.SubprocessError) as error:
        print('CLI capture bootstrap: unavailable ('+str(error)+')')
        # Existing task captures remain readable without executable registration.
    return 0 if supported and not missing else 1


def bind_viewer(store,port=None):
    from .server import make_server
    try:return make_server(store,8765 if port is None else port)
    except OSError as error:
        if port is not None or error.errno!=errno.EADDRINUSE:raise
        print('Default port 8765 is in use; choosing an available loopback port.',flush=True)
        return make_server(store,0)


def main(argv=None):
    parser=argparse.ArgumentParser(prog='uds-watch',description='Open a local, read-only UDS/Zarf deployment viewer. Never starts or stops a deployment.')
    parser.add_argument('--version',action='version',version='%(prog)s '+__version__)
    parser.add_argument('--port',type=int,default=None,help='explicit loopback port; 0 chooses an available port (default: try 8765, then choose a free port)')
    parser.add_argument('--no-browser',action='store_true',help='print the private URL without opening a browser')
    parser.add_argument('--no-setup',action='store_true',help='skip the first-run capture setup prompt')
    commands=parser.add_subparsers(dest='command')
    commands.add_parser('doctor',help='check local prerequisites without contacting a cluster')
    hook=commands.add_parser('shell-init',help='print an opt-in output-only shell function; does not edit your shell files')
    hook.add_argument('--shell',choices=('bash','zsh'),default=None)
    hook.add_argument('--tool',choices=('uds','zarf'),default='uds')
    for action in ('setup','uninstall'):
        command=commands.add_parser(action,help=('install' if action=='setup' else 'remove')+' reversible CLI capture registration (or an explicit legacy shell hook)' )
        command.add_argument('--shell',choices=('bash','zsh'))
        command.add_argument('--rc-file',type=Path,help='explicit startup file, for a nonstandard shell configuration')
        command.add_argument('--yes',action='store_true',help='explicitly approve the displayed setup changes without a prompt')
        command.add_argument('--cli',type=Path,action='append',help='register/restore this CLI executable; repeat for additional installations')
        command.add_argument('--legacy-shell-hook',action='store_true',help='explicit legacy current-shell integration instead of executable registration')
        if action=='setup':command.add_argument('--tool',choices=('uds','zarf','both'),default='both')
    commands.add_parser('capture',help='copy stdin to the terminal and private temporary capture; never launches UDS')
    args=parser.parse_args(argv)
    if args.command=='doctor':return doctor()
    if args.command in ('setup','uninstall'):
        from . import setup,entrypoints
        shell=args.shell or current_shell()
        if args.cli or not (args.legacy_shell_hook or args.rc_file):
            try:
                paths=[path.expanduser().absolute() for path in args.cli] if args.cli else entrypoints.selected(args.tool) if args.command=='setup' else entrypoints.registered()
                print('Reversible CLI '+args.command+':')
                for path in paths:print('  '+str(path))
                print('Native executable bytes are preserved. No deployment commands or configuration are changed.')
                if not args.yes and not confirm_setup('Approve these CLI entrypoint changes? [y/N] '):print('No changes made.');return 0
                if args.command=='setup':
                    for item in entrypoints.install_many(paths):print('Registered: '+str(item['entry'])+'; preserved native: '+str(item['native']))
                else:
                    for path in entrypoints.uninstall_many(paths):print('Restored native: '+str(path))
                remember_setup('installed' if args.command=='setup' else 'declined');return 0
            except (OSError,ValueError,subprocess.SubprocessError) as error:parser.error(str(error))
        try:
            files=setup.targets(shell,args.rc_file,all_login=args.command=='uninstall')
            print('Managed capture '+args.command+' for '+shell+':')
            for path in files:print('  '+str(path))
            if not args.yes and not confirm_setup('Approve startup-file changes? [y/N] '):print('No changes made.');return 0
            result=setup.install(Path(sys.argv[0]).resolve(),shell,args.tool,args.rc_file) if args.command=='setup' else setup.uninstall(shell,args.rc_file)
            setup_result(result);remember_setup('installed' if args.command=='setup' else 'declined')
            if args.command=='uninstall':print('No existing functions or aliases were removed from your current terminal.')
            return 0
        except (OSError,ValueError,subprocess.SubprocessError) as error:parser.error(str(error))
    if args.command=='shell-init':
        try:print(shell_init(args.shell or current_shell(),args.tool),end='');return 0
        except ValueError as error:parser.error(str(error))
    if args.command=='capture':
        helper=str(Path(__file__).with_name('capture.py'))
        os.execv(sys.executable,[sys.executable,helper])
    if args.port is not None and not 0<=args.port<=65535:parser.error('Port must be between 0 and 65535')
    if doctor():
        print('Install the missing prerequisites above, then run uds-watch again.',file=sys.stderr)
        return 1
    from .server import WatcherStore
    store=WatcherStore()
    try:
        server=bind_viewer(store,args.port)
    except OSError:
        store.close();parser.error('Cannot bind the loopback port. Reuse your existing viewer URL or choose --port 0.')
    try:
        maybe_setup(args.no_setup)
        print('\nUDS Watch: '+server.private_url+'\nCurrent session only. Keep this URL and logs private.\nCtrl+C stops only this viewer.\n',flush=True)
        if not args.no_browser:webbrowser.open(server.private_url)
        server.serve_forever(poll_interval=.2)
    except KeyboardInterrupt:pass
    finally:
        server.stopping.set();server.server_close();store.close()
    return 0
