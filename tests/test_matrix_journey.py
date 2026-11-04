"""Opt-in action-only SDK matrix journey against an explicitly supplied runner.

No cluster, charts, images, credentials, or real applications. Separate runtime
and --no-log-file keep these fixtures out of other viewers' capture discovery.
"""
import importlib.util
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

ROOT=Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.environ.get('UDS_MATRIX_JOURNEY')=='1','Opt-in concurrent SDK matrix journey')
class MatrixJourneyTests(unittest.TestCase):
    def test_runner_matrix_success_and_failure(self):
        uds=os.environ.get('UDS_TEST_BINARY') or shutil.which('uds');self.assertTrue(uds)
        runner=os.environ.get('UDS_MATRIX_RUNNER');self.assertTrue(runner and Path(runner).is_file())
        evidence=Path(tempfile.mkdtemp(prefix='uds-matrix-evidence-'))
        for mode in ('success','failure'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory(prefix='uds-matrix-sdk-') as directory:
                root=Path(directory);(root/'home').mkdir();artifacts=root/'artifacts';artifacts.mkdir()
                env={key:value for key,value in os.environ.items() if key in ('PATH','TMPDIR','LANG','LC_ALL')}
                env.update(HOME=str(root/'home'),UDS_DEPLOY_RUNTIME_DIR=str(root/'runtime'),UDS_CONFIG=str(root/'uds-config.yaml'),KUBECONFIG=str(root/'kubeconfig.json'))
                (root/'uds-config.yaml').write_text('{}')
                (root/'kubeconfig.json').write_text(json.dumps({'apiVersion':'v1','kind':'Config','clusters':[],'contexts':[],'users':[],'current-context':''}))
                subprocess.run([str(ROOT/'install.sh')],env=env,capture_output=True,check=True,timeout=10)
                def sdk(args):
                    result=subprocess.run([uds]+args,cwd=root,env=env,capture_output=True,timeout=40)
                    self.assertEqual(result.returncode,0,result.stderr.decode(errors='replace')[-1200:])
                names=('prepare','work-a','work-b','verify')
                for name in names:
                    package=root/name;package.mkdir()
                    code="import pathlib,sys,time;root=pathlib.Path(sys.argv[1]);name=sys.argv[2];(root/(name+'.started')).touch();print('MATRIX '+name+' stdout',flush=True);print('MATRIX '+name+' stderr',file=sys.stderr,flush=True);deadline=time.time()+80\nwhile not (root/(name+'.release')).exists() and time.time()<deadline:time.sleep(.03)\nsys.exit(7 if name=='work-b' and sys.argv[3]=='failure' else 0 if (root/(name+'.release')).exists() else 8)"
                    command=shlex.join([sys.executable,'-c',code,str(root),name,mode])
                    definition=dict(kind='ZarfPackageConfig',metadata=dict(name=name,version='0.0.1'),components=[dict(name='probe',required=True,actions={'onDeploy':{'before':[dict(description='Matrix fixture '+name,cmd=command)],'after':[dict(description='Fixture completed',cmd='printf "MATRIX final action\\n"')]}})])
                    (package/'zarf.yaml').write_text(json.dumps(definition));sdk(['zarf','package','create',str(package),'-a','amd64','--confirm','--skip-sbom','--output',str(artifacts)])
                (root/'uds-bundle.yaml').write_text(json.dumps(dict(kind='UDSBundle',metadata=dict(name='matrix-fixture',version='0.0.1'),packages=[dict(name=name,path=str(artifacts),ref='0.0.1') for name in names])))
                sdk(['create',str(root),'-a','amd64','--confirm','--output',str(artifacts)])
                bundle=next(artifacts.glob('uds-bundle-*.tar.zst'))
                driver=root/'driver.py'
                driver.write_text('''import importlib.util,json,os,pathlib,sys
spec=importlib.util.spec_from_file_location('fixture_runner',sys.argv[1]);runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
root=pathlib.Path(sys.argv[2]);uds=sys.argv[3];bundle=sys.argv[4]
runner.LAYERS=(('Prepare',('prepare',)),('Parallel jobs',('work-a','work-b')),('Verify',('verify',)))
graph={'prepare':set(),'work-a':{'prepare'},'work-b':{'prepare'},'verify':{'work-a','work-b'}}
watch=runner.WatchRun(graph,'Concurrent SDK fixture',dict(os.environ))
assert watch.enabled,'Optional publication failed'
def deploy(name):
 watch.started(name,None)
 code=None
 try:
  work=root/('work-'+name);work.mkdir()
  command=[uds,'--no-log-file','deploy',bundle,'-a','amd64','--confirm','--no-progress','--skip-signature-validation','--tmpdir',str(work),'--uds-cache',str(work/'cache'),'-p',name]
  code=runner.stream_deploy(command,name,root/(name+'.log'),cwd=root,env=dict(os.environ),on_start=lambda pid:watch.started(name,pid))
  return code
 finally:watch.result(name,code)
code=runner.schedule(graph,deploy);watch.finished(code)
(root/'runner.done').write_text(json.dumps({'code':code}))
sys.exit(code)
''')
                viewer=task=browser=None
                try:
                    viewer_env=dict(env,KUBECONFIG='')
                    viewer=subprocess.Popen([str(ROOT/'uds-watch'),'--no-browser','--port','0'],env=viewer_env,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,start_new_session=True)
                    url=None;deadline=time.monotonic()+15
                    while time.monotonic()<deadline:
                        line=viewer.stdout.readline().strip()
                        if line.startswith('http://127.0.0.1:'):url=line;break
                        self.assertIsNone(viewer.poll())
                    self.assertTrue(url)
                    with (root/'runner.log').open('wb') as output:
                        task=subprocess.Popen([sys.executable,str(driver),runner,str(root),str(uds),str(bundle)],env=env,stdout=output,stderr=subprocess.STDOUT,start_new_session=True)
                    manifest=root/'browser.json';manifest.write_text(json.dumps(dict(url=url,directory=str(root),evidence=str(evidence),mode=mode)))
                    browser_env=dict(os.environ,PLAYWRIGHT_MODULE=os.environ.get('PLAYWRIGHT_MODULE','playwright'))
                    browser=subprocess.Popen(['node',str(ROOT/'tests/test_matrix_browser.cjs'),str(manifest)],env=browser_env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
                    output=browser.communicate(timeout=100)[0].decode(errors='replace')
                    self.assertEqual(browser.returncode,0,output)
                    self.assertEqual(task.wait(timeout=10),0 if mode=='success' else 1)
                    self.assertEqual(json.loads((root/'runner.done').read_text())['code'],0 if mode=='success' else 1)
                    self.assertTrue((root/'browser.done').exists());print(output.strip())
                finally:
                    for name in names:(root/(name+'.release')).touch()
                    if browser is not None and browser.poll() is None:browser.terminate();browser.communicate(timeout=5)
                    if task is not None and task.poll() is None:os.killpg(task.pid,signal.SIGINT);task.wait(timeout=15)
                    if viewer is not None:
                        if viewer.poll() is None:viewer.send_signal(signal.SIGINT);viewer.wait(timeout=10)
                        if viewer.stdout:viewer.stdout.close()
        print('Matrix SDK fixture screenshots: '+str(evidence))


if __name__=='__main__':unittest.main()
