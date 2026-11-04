"""Loopback-only GET API, adapted from Apache-2.0 watcher code; see NOTICE.

There is deliberately no deployment engine, start API, retry API, or database.
"""
import base64
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import secrets
from socketserver import ThreadingMixIn
import threading
from urllib.parse import parse_qs, quote, unquote, urlsplit

from .model import package_by_id
from .native import NativeReader, processes
from .pipeline import view

WEB = Path(__file__).parent / 'web'
STATIC_ASSETS = {
    'index.html':'text/html', 'app.js':'text/javascript', 'style.css':'text/css',
    'theme.js':'text/javascript', 'theme.css':'text/css',
    'uds-logo.png':'image/png', 'uds-logo-on-dark.png':'image/png', 'doug.png':'image/png',
    **{'fonts/'+name:'font/woff2' for name in ('GitLabSans.woff2','GitLabSans-Italic.woff2','GitLabMono.woff2','GitLabMono-Italic.woff2')},
    **{'fonts/'+name:'text/plain' for name in ('GitLabSans-LICENSE.txt','GitLabMono-LICENSE.txt','NOTICE.txt')},
}


class WatcherStore:
    live_only = True
    def __init__(self):
        self.reader = NativeReader()
        self.lock = threading.RLock()
    def list(self, summary=False):
        with self.lock:return sorted(self.reader.list(),key=lambda state:state['created_at'],reverse=True)
    def get(self, run, private=False):
        if private:raise PermissionError('No saved deployment credentials or retry context')
        with self.lock:return self.reader.get(run)
    def processes(self):
        with self.lock:return [{key:row[key] for key in ('pid','tool','kind')} for row in processes()]
    def definition(self, run, package=None):
        with self.lock:return self.reader.definition(run,package)
    def events(self, run, **filters):
        with self.lock:return self.reader.events(run,**filters)
    def close(self):
        with self.lock:self.reader.close()


class LocalServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def make_server(store, port=8765):
    prefix = '/' + secrets.token_urlsafe(32)
    stopping = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):pass  # Never log capability URLs or config/log content.
        def send_headers(self, status, kind, download=None):
            self.send_response(status)
            self.send_header('Content-Type',kind)
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Referrer-Policy','no-referrer')
            self.send_header('Content-Security-Policy',"default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; font-src 'self'; frame-ancestors 'none'; base-uri 'none'")
            if download:self.send_header('Content-Disposition',"attachment; filename*=UTF-8''"+quote(download,safe=''))
            self.end_headers()
        def body(self, data, status=200):
            self.send_headers(status,'application/json; charset=utf-8')
            self.wfile.write(json.dumps(data).encode())
        def route(self):
            allowed={'127.0.0.1:'+str(self.server.server_port),'localhost:'+str(self.server.server_port)}
            if self.headers.get('Host') not in allowed:raise PermissionError('Local Host header required')
            url=urlsplit(self.path)
            if not url.path.startswith(prefix+'/'):raise PermissionError('Open the private URL printed by uds-watch')
            return [unquote(part) for part in url.path[len(prefix):].strip('/').split('/')],parse_qs(url.query)
        def do_GET(self):
            try:
                parts,query=self.route()
                filename='index.html' if parts==[''] else '/'.join(parts)
                if filename in STATIC_ASSETS:
                    kind=STATIC_ASSETS[filename]
                    self.send_headers(200,kind if kind.startswith(('font/','image/')) else kind+'; charset=utf-8')
                    content=(WEB/filename).read_bytes()
                    if filename=='index.html':content=content.replace(b'<body>',b'<body data-mode="live">')
                    self.wfile.write(content)
                    return
                if parts==['api','processes']:
                    self.body(store.processes());return
                if parts==['api','deployments']:
                    self.body(store.list(summary=True));return
                if parts[:2]!=['api','deployments'] or len(parts)<3:raise KeyError('Not found')
                run=parts[2];state=view(store.get(run));tail=parts[3:]
                if not tail:self.body(state);return
                if tail==['pipeline']:self.body(state['pipeline']);return
                if tail==['packages']:self.body(state['packages']);return
                package=None
                if len(tail)>=2 and tail[0]=='packages':
                    package=tail[1];row=package_by_id(state,package)
                    if len(tail)==2:self.body(row);return
                    tail=tail[2:]
                if tail==['definition']:self.body(store.definition(run,package));return
                if tail==['logs']:
                    value=lambda key,default:query.get(key,[default])[0]
                    filters=dict(package=package,attempt=value('attempt',None),logs=True,
                                 component=value('component',None),phase=value('phase',None),
                                 process=value('process',None),operation_execution=value('operation_execution',None),
                                 search=value('search',None),level=value('level',None))
                    if value('download','0')=='1':
                        self.send_headers(200,'application/octet-stream',download=run+'-'+(package or 'full')+'.log')
                        after=0;end=state.get('log_cursor',state['cursor'])+1
                        while True:
                            rows=store.events(run,after=after,before=end,limit=100,**filters)
                            for row in rows:
                                data=row['data'];self.wfile.write(base64.b64decode(data['raw_b64']) if 'raw_b64' in data else data['raw'].encode())
                                after=row['id']
                            self.wfile.flush()
                            if len(rows)<100:break
                        return
                    self.body(store.events(run,after=int(value('after',0)),before=int(value('before',0)) or None,
                                           latest=value('latest','1')=='1',limit=int(value('limit',500)),**filters));return
                if tail==['events'] and package is None:
                    after=int(self.headers.get('Last-Event-ID') or query.get('after',[0])[0])
                    self.send_headers(200,'text/event-stream')
                    while not stopping.is_set():
                        rows=store.events(run,after=after)
                        for row in rows:
                            after=row.get('event_cursor',row['id'])
                            self.wfile.write(('id: {}\nevent: change\ndata: {}\n\n'.format(after,json.dumps(row))).encode())
                        if not rows:self.wfile.write(b': keepalive\n\n')
                        self.wfile.flush();stopping.wait(.5)
                    return
                raise KeyError('Not found')
            except (BrokenPipeError,ConnectionResetError):pass
            except PermissionError as error:self.body({'error':str(error)},403)
            except (KeyError,StopIteration):self.body({'error':'Not found'},404)
            except (ValueError,OSError):self.body({'error':'Invalid request or unavailable local source'},400)
        def reject_write(self):
            self.body({'error':'Read-only watcher. Run deployment commands in your terminal.'},403)
        do_POST=reject_write
        do_PUT=reject_write
        do_PATCH=reject_write
        do_DELETE=reject_write

    server=LocalServer(('127.0.0.1',port),Handler)
    server.private_url='http://127.0.0.1:{}{}/'.format(server.server_port,prefix)
    server.stopping=stopping
    return server
