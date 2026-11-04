"""Launch a read-only viewer; never install hooks or modify a CLI."""
import argparse
import errno
import os
from pathlib import Path
import shutil
import sys
import webbrowser

from . import __version__


def terminal(text,code):
    if sys.stdout.isatty() and 'NO_COLOR' not in os.environ and os.environ.get('TERM','dumb')!='dumb':return '\033['+code+'m'+text+'\033[0m'
    return text


def doctor():
    supported=sys.platform in ('darwin','linux')
    checks=[('Platform',supported,'supported' if supported else 'macOS or Linux required')]
    for tool in ('ps','lsof','zstd'):
        available=bool(shutil.which(tool));checks.append((tool,available,'available' if available else 'missing'))
    available=bool(shutil.which('uds') or shutil.which('zarf'))
    checks.append(('UDS/Zarf',available,'available' if available else 'missing'))
    print('\n'+terminal('UDS Watch','1')+'\n')
    for label,ready,detail in checks:
        mark=terminal('OK  ' if ready else 'FAIL','32' if ready else '31')
        print('  '+mark+'  '+f'{label:<10}'+detail)
    print()
    return 0 if all(ready for _,ready,_ in checks) else 1


def bind_viewer(store,port=None):
    from .server import make_server
    try:return make_server(store,8765 if port is None else port)
    except OSError as error:
        if port is not None or error.errno!=errno.EADDRINUSE:raise
        print(terminal('Port 8765 is busy; using a free local port.','33'),flush=True)
        return make_server(store,0)


def main(argv=None):
    parser=argparse.ArgumentParser(prog='uds-watch',description='Open a local, read-only UDS/Zarf deployment viewer. Never starts or stops a deployment.')
    parser.add_argument('--version',action='version',version='%(prog)s '+__version__)
    parser.add_argument('--port',type=int,default=None,help='loopback port; default: try 8765, then choose a free port')
    parser.add_argument('--no-browser',action='store_true',help='print the private URL instead of opening a browser')
    parser.add_argument('--no-setup',action='store_true',help=argparse.SUPPRESS)  # Old launch commands remain harmless.
    commands=parser.add_subparsers(dest='command')
    commands.add_parser('doctor',help='check local prerequisites; change nothing')
    commands.add_parser('capture',help='output-only stdin tee for explicitly wired tasks; never launches UDS')
    commands.add_parser('publish-run',help='record a private runner snapshot from stdin; never launches a job')
    args=parser.parse_args(argv)
    if args.command=='doctor':return doctor()
    if args.command=='publish-run':
        import json
        import subprocess
        from .runs import LIMIT, publish
        try:
            raw=sys.stdin.buffer.read(LIMIT+1)
            if len(raw)>LIMIT:raise ValueError('Run record too large')
            publish(json.loads(raw));return 0
        except (OSError,ValueError,TypeError,KeyError,subprocess.SubprocessError):return 1
    if args.command=='capture':
        helper=str(Path(__file__).with_name('capture.py'))
        os.execv(sys.executable,[sys.executable,helper])
    if args.port is not None and not 0<=args.port<=65535:parser.error('Port must be between 0 and 65535')
    if doctor():
        print('Install the missing prerequisites above, then run uds-watch again.',file=sys.stderr)
        return 1
    from .server import WatcherStore
    store=WatcherStore()
    try:server=bind_viewer(store,args.port)
    except OSError:
        store.close();parser.error('Cannot bind the loopback port. Reuse your existing viewer URL or choose --port 0.')
    try:
        print('  '+terminal('Viewer ready','1;32')+'\n\n  '+terminal(server.private_url,'36')+'\n\n  Private session. Keep URL and logs private.\n  Ctrl+C stops the viewer, not your deployment.\n',flush=True)
        if not args.no_browser:webbrowser.open(server.private_url)
        server.serve_forever(poll_interval=.2)
    except KeyboardInterrupt:pass
    finally:
        server.stopping.set();server.server_close();store.close()
    return 0
