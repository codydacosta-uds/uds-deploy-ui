"""Opt-in REAL action-only SDK test: no cluster, cloud config, or application rollout.

UDS_LIVE_INTEGRATION=1 UDS_TEST_BINARY=/path/to/uds python3 -m unittest discover -s tests -p test_real_cli.py -v
"""
import json
import os
from pathlib import Path
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from uds_deploy.native import NativeReader,open_files
from uds_deploy.output import active_capture


@unittest.skipUnless(os.environ.get('UDS_LIVE_INTEGRATION')=='1','Opt-in real action-only SDK test')
class RealCLITests(unittest.TestCase):
    def test_task_capture_native_exit_and_interrupt(self):
        uds=os.environ.get('UDS_TEST_BINARY') or shutil.which('uds');self.assertTrue(uds)
        with tempfile.TemporaryDirectory(prefix='uds-watch-sdk-') as directory:
            root=Path(directory);(root/'bin').mkdir();(root/'bin/uds').symlink_to(uds);(root/'home').mkdir();artifacts=root/'artifacts';artifacts.mkdir()
            env={key:value for key,value in os.environ.items() if key in ('PATH','TMPDIR','LANG','LC_ALL')}
            env.update(PATH=str(root/'bin')+os.pathsep+env['PATH'],HOME=str(root/'home'),UDS_DEPLOY_RUNTIME_DIR=str(root/'runtime'),UDS_CONFIG=str(root/'uds-config.yaml'),KUBECONFIG=str(root/'kubeconfig.json'))
            (root/'uds-config.yaml').write_text('{}');(root/'kubeconfig.json').write_text(json.dumps({'apiVersion':'v1','kind':'Config','clusters':[],'contexts':[],'users':[],'current-context':''}))
            marker=root/'started';release=root/'release';outcome=root/'outcome'
            body="import pathlib,time,sys;pathlib.Path({!r}).touch();g=pathlib.Path({!r});deadline=time.time()+45\nwhile not g.exists() and time.time()<deadline:time.sleep(.03)\nprint('SDK stdout marker',flush=True)\nprint('SDK stderr marker',file=sys.stderr,flush=True)\nsys.exit(7 if pathlib.Path({!r}).read_text()=='fail' else 0)".format(str(marker),str(release),str(outcome))
            package=root/'package';package.mkdir()
            definition=dict(kind='ZarfPackageConfig',metadata=dict(name='watcher-probe',version='0.0.1'),components=[dict(name='action',required=True,actions={'onDeploy':{'before':[{'description':'Standalone watcher SDK probe','cmd':shlex.quote(sys.executable)+' -c '+shlex.quote(body),'maxRetries':0}]}})])
            (package/'zarf.yaml').write_text(json.dumps(definition))
            def create(args):
                result=subprocess.run([uds]+args,cwd=root,env=env,capture_output=True,timeout=40)
                self.assertEqual(result.returncode,0,'Isolated SDK artifact creation failed')
            create(['zarf','package','create',str(package),'-a','amd64','--confirm','--skip-sbom','--output',str(artifacts)])
            (root/'uds-bundle.yaml').write_text(json.dumps(dict(kind='UDSBundle',metadata=dict(name='watcher-probe',version='0.0.1'),packages=[dict(name='watcher-probe',path=str(artifacts),ref='0.0.1')])))
            create(['create',str(root),'-a','amd64','--confirm','--output',str(artifacts)])
            bundle=next(artifacts.glob('uds-bundle-*.tar.zst'));zarf=next(artifacts.glob('zarf-package-*.tar.zst'))
            cases=[('bash',True,'deploy',False),('zsh',True,'deploy',False),('bash',False,'deploy',True),('bash',True,'deploy',True),('zsh',False,'deploy',True),('zsh',True,'deploy',True),('bash',True,'zarf',False)]
            results={}
            for shell,captured,verb,interrupt in cases:
                binary=shutil.which(shell)
                if not binary:continue
                with self.subTest(shell=shell,captured=captured,verb=verb,interrupt=interrupt):
                    for file in (marker,release):
                        if file.exists():file.unlink()
                    outcome.write_text('fail')
                    args=['--log-level','info']+(['deploy',str(bundle)] if verb=='deploy' else ['zarf','package','deploy',str(zarf)])+['-a','amd64','--confirm','--no-progress','--skip-signature-validation']
                    status='${pipestatus[1]}' if shell=='zsh' else '${PIPESTATUS[0]}'
                    helper=shlex.join([sys.executable,str(ROOT/'src/uds_deploy/capture.py')])
                    command='shift 2; uds "$@"'+(' 2>&1 | ('+helper+' || cat); exit "'+status+'"' if captured else '')
                    output=root/'terminal.log'
                    with output.open('wb') as console:
                        task=subprocess.Popen([binary,'-c',command,'sdk-probe',str(ROOT/'uds-watch'),shell]+args,env=env,cwd=root,stdout=console,stderr=subprocess.STDOUT,start_new_session=True)
                    reader=NativeReader()
                    try:
                        deadline=time.monotonic()+20
                        while not marker.exists():
                            self.assertIsNone(task.poll(),'Real SDK action exited before readiness')
                            self.assertLess(time.monotonic(),deadline,'Real SDK action readiness timed out');time.sleep(.03)
                        if captured:
                            rows=subprocess.check_output(['ps','-axo','pid=,args='],text=True);pid=None
                            for line in rows.splitlines():
                                fields=line.strip().split(None,1)
                                if len(fields)!=2:continue
                                try:argv=shlex.split(fields[1])
                                except ValueError:continue
                                if len(argv)>1 and argv[1:]==args and Path(argv[0]).name=='uds':pid=int(fields[0]);break
                            self.assertIsNotNone(pid)
                            with patch.dict(os.environ,dict(env,KUBECONFIG=''),clear=True):
                                capture=active_capture(pid,open_files);ready=time.monotonic()+3
                                while not capture or capture.get('pending'):
                                    self.assertLess(time.monotonic(),ready,'Validated capture helper did not become ready');time.sleep(.03);capture=active_capture(pid,open_files)
                                reader.attach(dict(pid=pid,tool='uds',args=[str(root/'bin/uds')]+args));session=next(iter(reader.sessions.values()));reader.read(session)
                                self.assertTrue(session['state']['source']['output_complete'])
                                self.assertEqual(session['state']['artifact_info']['kind'],'UDSBundle' if verb=='deploy' else 'ZarfPackageConfig')
                                self.assertFalse(reader.definition(session['state']['id'],'watcher-probe')['values_hidden'])
                                self.assertTrue(any(r['kind']=='actions.command' for r in session['state']['reports']))
                        if interrupt:os.killpg(task.pid,signal.SIGINT)
                        else:release.touch()
                        code=task.wait(timeout=15);results[(shell,captured,verb,interrupt)]=code;self.assertNotEqual(code,0)
                        if captured:
                            reader.read(session,finished=True);session['file'].seek(0);raw=session['file'].read()
                            self.assertEqual(raw,output.read_bytes(),'Capture and deployment terminal must contain identical original bytes')
                            if not interrupt:self.assertIn(b'SDK stdout marker',raw);self.assertIn(b'SDK stderr marker',raw)
                            self.assertFalse(capture['record'].exists())
                    finally:
                        release.touch();reader.close()
                        if task.poll() is None:
                            # Only this explicitly created isolated SDK process group.
                            os.killpg(task.pid,signal.SIGINT);task.wait(timeout=15)
            for shell in ('bash','zsh'):
                if (shell,False,'deploy',True) in results and (shell,True,'deploy',True) in results:self.assertEqual(results[(shell,False,'deploy',True)],results[(shell,True,'deploy',True)],'The task tee must preserve native Ctrl+C status')
            self.assertEqual(results[('bash',True,'deploy',False)],1)
            self.assertEqual(list(root.rglob('*.sqlite3')),[])


if __name__=='__main__':unittest.main()
