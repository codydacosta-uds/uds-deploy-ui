"""Launch a read-only viewer; never install hooks or modify a CLI."""
import argparse
import errno
import os
from pathlib import Path
import shutil
import sys
import webbrowser

from . import __version__


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
    parser.add_argument('--port',type=int,default=None,help='loopback port; default: try 8765, then choose a free port')
    parser.add_argument('--no-browser',action='store_true',help='print the private URL instead of opening a browser')
    parser.add_argument('--no-setup',action='store_true',help=argparse.SUPPRESS)  # Old launch commands remain harmless.
    commands=parser.add_subparsers(dest='command')
    commands.add_parser('doctor',help='check local prerequisites; change nothing')
    commands.add_parser('capture',help='output-only stdin tee for explicitly wired tasks; never launches UDS')
    args=parser.parse_args(argv)
    if args.command=='doctor':return doctor()
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
        print('\nUDS Watch: '+server.private_url+'\nCurrent session only. Keep this URL and logs private.\nCtrl+C stops only this viewer.\n',flush=True)
        if not args.no_browser:webbrowser.open(server.private_url)
        server.serve_forever(poll_interval=.2)
    except KeyboardInterrupt:pass
    finally:
        server.stopping.set();server.server_close();store.close()
    return 0
