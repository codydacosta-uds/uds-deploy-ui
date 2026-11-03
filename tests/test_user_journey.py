"""Deploy-first journey using an explicit task tee, never CLI/shell setup.

Action-only SDK artifacts, isolated HOME/KUBECONFIG and normal Playwright.
An explicit API-only mode is available for Linux checks. No OS browser or
real application/cluster deployment is involved.
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

ROOT=Path(__file__).resolve().parents[1]


def private_json(path,data):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as stream:json.dump(data,stream)


@unittest.skipUnless(os.environ.get('UDS_USER_JOURNEY')=='1','Opt-in deploy-first task-capture journey')
class UserJourneyTests(unittest.TestCase):
    def test_deploy_first_then_watch_opens_the_ui(self):
        uds=os.environ.get('UDS_TEST_BINARY') or shutil.which('uds');self.assertTrue(uds)
        sonic=os.environ.get('UDS_JOURNEY_CAPTURE_MODE')=='sonic-task'
        helper=Path(os.environ['UDS_SONIC_TEST_HELPER']) if sonic else ROOT/'src/uds_deploy/capture.py'
        self.assertTrue(helper.is_file())
        playwright=os.environ.get('PLAYWRIGHT_MODULE','playwright')
        evidence=Path(tempfile.mkdtemp(prefix='uds-task-journey-evidence-'))
        for shell in ('bash','zsh'):
            binary=shutil.which(shell)
            if not binary:continue
            with self.subTest(shell=shell),tempfile.TemporaryDirectory(prefix='uds-task-journey-') as directory:
                root=Path(directory);(root/'home').mkdir();(root/'bin').mkdir();(root/'bin/uds').symlink_to(uds)
                artifacts=root/'artifacts';artifacts.mkdir()
                env={key:value for key,value in os.environ.items() if key in ('PATH','TMPDIR','LANG','LC_ALL')}
                env.update(HOME=str(root/'home'),PATH=str(root/'bin')+os.pathsep+env['PATH'],UDS_DEPLOY_RUNTIME_DIR=str(root/'runtime'),UDS_CONFIG=str(root/'uds-config.yaml'),KUBECONFIG=str(root/'kubeconfig.json'),PLAYWRIGHT_MODULE=playwright)
                if sonic:
                    (root/'tmp').mkdir();env['TMPDIR']=str(root/'tmp');env.pop('UDS_DEPLOY_RUNTIME_DIR')
                (root/'uds-config.yaml').write_text('{}')
                (root/'kubeconfig.json').write_text(json.dumps({'apiVersion':'v1','kind':'Config','clusters':[],'contexts':[],'users':[],'current-context':''}))
                release_prepare=root/'release-prepare';release_verify=root/'release-verify';started=root/'prepare-started'
                def action(name,release):
                    body="import pathlib,time,sys;pathlib.Path({!r}).touch();g=pathlib.Path({!r});deadline=time.time()+90\nprint('JOURNEY stdout '+{!r},flush=True)\nprint('JOURNEY stderr '+{!r},file=sys.stderr,flush=True)\nwhile not g.exists() and time.time()<deadline:time.sleep(.03)\nif not g.exists():sys.exit(8)".format(str(root/(name+'-started')),str(release),name,name)
                    return shlex.quote(sys.executable)+' -c '+shlex.quote(body)
                package=root/'package';package.mkdir()
                definition=dict(kind='ZarfPackageConfig',metadata=dict(name='watcher-journey',version='0.0.1'),components=[dict(name='prepare',required=True,actions={'onDeploy':{'before':[{'description':'Journey prepare action','cmd':action('prepare',release_prepare)}]}}),dict(name='verify',required=True,actions={'onDeploy':{'before':[{'description':'Journey verify action','cmd':action('verify',release_verify)}],'after':[{'description':'Journey final post-deploy action','cmd':'printf "JOURNEY final post-deploy\\n"'}]}})])
                (package/'zarf.yaml').write_text(json.dumps(definition))
                def run(args):
                    result=subprocess.run([uds]+args,cwd=root,env=env,capture_output=True,timeout=40)
                    self.assertEqual(result.returncode,0,'Isolated SDK artifact creation failed: '+result.stderr.decode(errors='replace')[-1000:])
                run(['zarf','package','create',str(package),'-a','amd64','--confirm','--skip-sbom','--output',str(artifacts)])
                # Exercise a real bundle alias different from packaged Zarf name.
                shutil.copy2(next(artifacts.glob('zarf-package-*.tar.zst')),artifacts/'zarf-package-watcher-journey-alias-amd64-0.0.1.tar.zst')
                (root/'uds-bundle.yaml').write_text(json.dumps(dict(kind='UDSBundle',metadata=dict(name='watcher-journey',version='0.0.1'),packages=[dict(name='watcher-journey-alias',path=str(artifacts),ref='0.0.1')])))
                run(['create',str(root),'-a','amd64','--confirm','--output',str(artifacts)])
                bundle=next(artifacts.glob('uds-bundle-*.tar.zst'))
                args=['--log-level','info','deploy',str(bundle),'-a','amd64','--confirm','--no-progress','--skip-signature-validation']
                command=shlex.join([str(root/'bin/uds')]+args)+' 2>&1 | ('+shlex.join([sys.executable,str(helper)])+' || cat); exit "${PIPESTATUS[0]}"'
                (root/'tasks.yaml').write_text(json.dumps({'tasks':[{'name':'deploy-probe','actions':[{'cmd':command,'shell':{'linux':'bash','darwin':'bash'}}]}]}))
                terminal=root/'terminal.log';expected=root/'native-output.log';event=root/'browser-event.json';viewer_log=root/'viewer.log'
                task=viewer=driver=None;gold=None
                try:
                    with terminal.open('wb') as console:
                        task=subprocess.Popen([binary,'-c','exec "$@"','journey',str(root/'bin/uds'),'--log-level','info','--no-progress','run','deploy-probe'],cwd=root,env=env,stdin=subprocess.DEVNULL,stdout=console,stderr=subprocess.STDOUT,start_new_session=True)
                    deadline=time.monotonic()+20
                    while not started.exists():
                        self.assertIsNone(task.poll());self.assertLess(time.monotonic(),deadline);time.sleep(.03)
                    pid=None
                    for line in subprocess.check_output(['ps','-axo','pid=,args='],text=True).splitlines():
                        fields=line.strip().split(None,1)
                        if len(fields)!=2:continue
                        try:argv=shlex.split(fields[1])
                        except ValueError:continue
                        if argv[1:]==args and Path(argv[0]).name=='uds':pid=int(fields[0]);break
                    self.assertIsNotNone(pid)
                    home=root/'tmp'/('sonic-deploy-output-'+str(os.getuid())) if sonic else root/'runtime/output'
                    records=list(home.glob('*/capture.json'));self.assertEqual(len(records),1)
                    gold=(records[0].parent/'console.log').open('rb')
                    browser_env=dict(env,UDS_JOURNEY_BROWSER_EVENT=str(event),BROWSER=shlex.quote(sys.executable)+' '+shlex.quote(str(ROOT/'tests/journey_browser_handoff.py'))+' %s')
                    manifest=root/'manifest.json';task_exit=root/'task-exit.json'
                    private_json(manifest,dict(shell=shell,package_alias='watcher-journey-alias',deploy_pid=pid,deploy_started_before_viewer=True,browser_event=str(event),release_prepare=str(release_prepare),release_verify=str(release_verify),task_exit=str(task_exit),terminal=str(expected),capture_mode='sonic-task' if sonic else 'task',evidence=str(evidence)))
                    with viewer_log.open('wb') as log:
                        viewer=subprocess.Popen([str(ROOT/'uds-watch')],cwd=root,env=browser_env,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
                    driver_env=dict(env)
                    cache=Path.home()/'Library/Caches' if sys.platform=='darwin' else Path(os.environ.get('XDG_CACHE_HOME',str(Path.home()/'.cache')))
                    driver_env['PLAYWRIGHT_BROWSERS_PATH']=os.environ.get('PLAYWRIGHT_BROWSERS_PATH',str(cache/'ms-playwright'))
                    driver_command=[sys.executable,str(ROOT/'tests/journey_api_driver.py'),str(manifest)] if os.environ.get('UDS_JOURNEY_API_ONLY')=='1' else ['node',str(ROOT/'tests/test_user_journey_browser.cjs'),str(manifest)]
                    driver=subprocess.Popen(driver_command,cwd=ROOT,env=driver_env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
                    deadline=time.monotonic()+75
                    while driver.poll() is None:
                        if task.poll() is not None and not task_exit.exists():
                            gold.seek(0);expected.write_bytes(gold.read());private_json(task_exit,{'code':task.returncode})
                        self.assertIsNone(viewer.poll());self.assertLess(time.monotonic(),deadline);time.sleep(.05)
                    output=driver.communicate(timeout=5)[0].decode(errors='replace');self.assertEqual(driver.returncode,0,output)
                    self.assertEqual(task.wait(timeout=5),0)
                    viewer.send_signal(signal.SIGINT);self.assertEqual(viewer.wait(timeout=5),0)
                    print(output.strip())
                finally:
                    release_prepare.touch();release_verify.touch()
                    if driver is not None and driver.poll() is None:driver.terminate();driver.communicate(timeout=5)
                    if viewer is not None and viewer.poll() is None:viewer.send_signal(signal.SIGINT);viewer.wait(timeout=5)
                    if gold is not None:gold.close()
                    if task is not None and task.poll() is None:os.killpg(task.pid,signal.SIGINT);task.wait(timeout=15)


if __name__=='__main__':unittest.main()
