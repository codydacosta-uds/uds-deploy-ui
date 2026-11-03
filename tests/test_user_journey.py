"""Opt-in user journey: deploy FIRST, then uds-watch and normal Playwright.

Real stock UDS, installed shell hook, NativeReader HTTP API, and Playwright browser.
Action-only artifacts and isolated HOME/KUBECONFIG: no cloud/cluster/application rollout.
BROWSER points to a URL recorder that never launches an OS browser; Playwright
uses its normal default launch safeguards. OS default-browser integration is
explicitly NOT verified by this test.
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


@unittest.skipUnless(os.environ.get('UDS_USER_JOURNEY')=='1','Opt-in deploy-first real browser journey')
class UserJourneyTests(unittest.TestCase):
    def test_deploy_first_then_watch_opens_the_ui(self):
        uds=os.environ.get('UDS_TEST_BINARY') or shutil.which('uds');self.assertTrue(uds)
        playwright=os.environ.get('PLAYWRIGHT_MODULE','playwright')
        sonic=os.environ.get('UDS_JOURNEY_CAPTURE_MODE')=='sonic-task'
        entry=os.environ.get('UDS_JOURNEY_CAPTURE_MODE')=='entrypoint'
        launch=os.environ.get('UDS_JOURNEY_LAUNCH','direct')
        nested=sonic or entry and launch in ('run','run-absolute')
        helper=Path(os.environ.get('UDS_SONIC_TEST_HELPER',''))
        if sonic:self.assertTrue(helper.is_file(),'Supply UDS_SONIC_TEST_HELPER from the SONIC checkout; no production task is run')
        evidence=Path(tempfile.mkdtemp(prefix='uds-user-journey-evidence-'))
        for shell in ('bash','zsh'):
            shell_bin=shutil.which(shell)
            if not shell_bin:continue
            with self.subTest(shell=shell),tempfile.TemporaryDirectory(prefix='uds-user-journey-') as directory:
                root=Path(directory);(root/'home').mkdir();(root/'bin').mkdir()
                if entry:shutil.copy2(uds,root/'uds');(root/'bin/uds').symlink_to(root/'uds')
                else:(root/'bin/uds').symlink_to(uds)
                artifacts=root/'artifacts';artifacts.mkdir()
                env={key:value for key,value in os.environ.items() if key in ('PATH','TMPDIR','LANG','LC_ALL')}
                env.update(HOME=str(root/'home'),PATH=str(root/'bin')+os.pathsep+env['PATH'],UDS_DEPLOY_RUNTIME_DIR=str(root/'runtime'),UDS_CONFIG=str(root/'uds-config.yaml'),KUBECONFIG=str(root/'kubeconfig.json'),PLAYWRIGHT_MODULE=playwright)
                if sonic:
                    (root/'tmp').mkdir();env['TMPDIR']=str(root/'tmp');env.pop('UDS_DEPLOY_RUNTIME_DIR')
                (root/'uds-config.yaml').write_text('{}');(root/'kubeconfig.json').write_text(json.dumps({'apiVersion':'v1','kind':'Config','clusters':[],'contexts':[],'users':[],'current-context':''}))
                started=root/'prepare-started';release_prepare=root/'release-prepare';release_verify=root/'release-verify'
                def action(name,release):
                    body="import pathlib,time,sys;pathlib.Path({!r}).touch();g=pathlib.Path({!r});deadline=time.time()+90\nprint('JOURNEY stdout '+{!r},flush=True)\nprint('JOURNEY stderr '+{!r},file=sys.stderr,flush=True)\nwhile not g.exists() and time.time()<deadline:time.sleep(.03)\nif not g.exists():sys.exit(8)".format(str(root/(name+'-started')),str(release),name,name)
                    return shlex.quote(sys.executable)+' -c '+shlex.quote(body)
                package=root/'package';package.mkdir();definition=dict(kind='ZarfPackageConfig',metadata=dict(name='watcher-journey',version='0.0.1'),components=[dict(name='prepare',required=True,actions={'onDeploy':{'before':[{'description':'Journey prepare action','cmd':action('prepare',release_prepare)}]}}),dict(name='verify',required=True,actions={'onDeploy':{'before':[{'description':'Journey verify action','cmd':action('verify',release_verify)}],'after':[{'description':'Journey final post-deploy action','cmd':'printf "JOURNEY final post-deploy\\n"'}]}})])
                (package/'zarf.yaml').write_text(json.dumps(definition))
                def run(args):
                    result=subprocess.run(args,cwd=root,env=env,capture_output=True,timeout=40)
                    self.assertEqual(result.returncode,0,'Isolated artifact/setup command failed')
                run([uds,'zarf','package','create',str(package),'-a','amd64','--confirm','--skip-sbom','--output',str(artifacts)])
                (root/'uds-bundle.yaml').write_text(json.dumps(dict(kind='UDSBundle',metadata=dict(name='watcher-journey',version='0.0.1'),packages=[dict(name='watcher-journey',path=str(artifacts),ref='0.0.1')])))
                run([uds,'create',str(root),'-a','amd64','--confirm','--output',str(artifacts)])
                bundle=next(artifacts.glob('uds-bundle-*.tar.zst'));startup=root/'startup'
                # One-time setup has already been accepted before this journey.
                if entry:run([str(ROOT/'uds-watch'),'setup','--yes','--cli',str(root/'uds')])
                elif not sonic:run([str(ROOT/'uds-watch'),'setup','--yes','--shell',shell,'--tool','uds','--rc-file',str(startup)])
                args=['--log-level','info','deploy',str(bundle),'-a','amd64','--confirm','--no-progress','--skip-signature-validation']
                launch_args=args;program=['uds']
                if entry and launch in ('script','script-relative','script-absolute'):
                    script=root/'invoke-deploy';script.write_text('#!/bin/sh\nexec '+('./uds' if launch=='script-relative' else shlex.quote(str(root/'uds')) if launch=='script-absolute' else 'uds')+' "$@"\n');script.chmod(0o700);program=[str(script)]
                if entry and launch in ('run','run-absolute'):
                    command=shlex.join([str(root/'uds') if launch=='run-absolute' else './uds']+args)
                    (root/'tasks.yaml').write_text(json.dumps({'tasks':[{'name':'deploy-probe','actions':[{'cmd':command,'shell':{'linux':'bash','darwin':'bash'}}]}]}))
                    launch_args=['--log-level','info','--no-progress','run','deploy-probe']
                if sonic:
                    command=shlex.join([str(root/'bin/uds')]+args)+' 2>&1 | ('+shlex.join([sys.executable,str(helper)])+' || cat); exit "${PIPESTATUS[0]}"'
                    (root/'tasks.yaml').write_text(json.dumps({'tasks':[{'name':'deploy-probe','actions':[{'cmd':command,'shell':{'linux':'bash','darwin':'bash'}}]}]}))
                    launch_args=['--log-level','info','--no-progress','run','deploy-probe']
                terminal=root/'terminal.log';expected=root/'native-output.log' if nested else terminal;gold=None
                viewer_log=root/'viewer.log';task=viewer=driver=None;event=root/'browser-event.json';gold_integrity=None;whole_task=False
                try:
                    with terminal.open('wb') as console:
                        shell_command='shift; exec "$@"' if entry else 'shift; command uds "$@"' if sonic else '. "$1"; shift; uds "$@"'
                        task=subprocess.Popen([shell_bin,'-c',shell_command,'journey',str(startup)]+(program if entry else [])+launch_args,cwd=root,env=env,stdin=subprocess.DEVNULL,stdout=console,stderr=subprocess.STDOUT,start_new_session=True)
                    deadline=time.monotonic()+20
                    while not started.exists():
                        self.assertIsNone(task.poll(),'Native deployment ended before its first gated action');self.assertLess(time.monotonic(),deadline,'Native action readiness timed out');time.sleep(.03)
                    rows=subprocess.check_output(['ps','-axo','pid=,args='],text=True);pid=None
                    for line in rows.splitlines():
                        fields=line.strip().split(None,1)
                        if len(fields)!=2:continue
                        try:argv=shlex.split(fields[1])
                        except ValueError:continue
                        if argv[1:]==args and Path(argv[0]).name=='uds':pid=int(fields[0]);break
                    self.assertIsNotNone(pid)
                    if nested:
                        capture_home=root/'tmp'/('sonic-deploy-output-'+str(os.getuid())) if sonic else root/'runtime/output'
                        records=list(capture_home.glob('*/capture.json'))
                        if entry:
                            direct_records=[record for record in records if json.loads(record.read_text()).get('native_pid')==pid]
                            records=direct_records or [record for record in records if json.loads(record.read_text()).get('task_root')]
                        self.assertEqual(len(records),1,'Find the exact native capture, or its unique parent task capture')
                        gold=(records[0].parent/'console.log').open('rb')
                        if entry:
                            gold_integrity=(records[0].parent/'integrity').open('rb',buffering=0)
                            whole_task=json.loads(records[0].read_text()).get('task_root',False)
                    # Native CLI is NOW already running. Start the normal viewer,
                    # Its browser request is recorded without any OS/browser launch.
                    # A foreground zero-exit recorder prevents platform-browser fallback.
                    browser_env=dict(env,UDS_JOURNEY_BROWSER_EVENT=str(event),BROWSER=shlex.quote(sys.executable)+' '+shlex.quote(str(ROOT/'tests/journey_browser_handoff.py'))+' %s')
                    manifest=root/'manifest.json';task_exit=root/'task-exit.json'
                    private_json(manifest,dict(shell=shell,deploy_pid=pid,deploy_started_before_viewer=started.exists(),browser_event=str(event),release_prepare=str(release_prepare),release_verify=str(release_verify),task_exit=str(task_exit),terminal=str(expected),capture_mode=('entrypoint-'+launch) if entry else 'sonic-task' if sonic else 'hook',evidence=str(evidence)))
                    with viewer_log.open('wb') as log:
                        viewer=subprocess.Popen([str(ROOT/'uds-watch')],cwd=root,env=browser_env,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
                    driver_env=dict(env)
                    cache=Path.home()/'Library/Caches' if sys.platform=='darwin' else Path(os.environ.get('XDG_CACHE_HOME',str(Path.home()/'.cache')))
                    driver_env['PLAYWRIGHT_BROWSERS_PATH']=os.environ.get('PLAYWRIGHT_BROWSERS_PATH',str(cache/'ms-playwright'))
                    driver_command=[sys.executable,str(ROOT/'tests/journey_api_driver.py'),str(manifest)] if os.environ.get('UDS_JOURNEY_API_ONLY')=='1' else ['node',str(ROOT/'tests/test_user_journey_browser.cjs'),str(manifest)]
                    driver=subprocess.Popen(driver_command,cwd=ROOT,env=driver_env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
                    deadline=time.monotonic()+75
                    while driver.poll() is None:
                        ready=True
                        if gold_integrity is not None:
                            gold_integrity.seek(0);quality=gold_integrity.read(1);ready=quality==b'1'
                            self.assertNotEqual(quality,b'!','The test requires an intact capture, not a silently dropped side channel')
                        if task.poll() is not None and not task_exit.exists() and ready:
                            if whole_task:expected.write_bytes(terminal.read_bytes())
                            elif gold is not None:gold.seek(0);expected.write_bytes(gold.read())
                            private_json(task_exit,{'code':task.returncode})
                        self.assertIsNone(viewer.poll(),'Viewer exited before the browser journey completed')
                        self.assertLess(time.monotonic(),deadline,'Deploy-first browser journey timed out');time.sleep(.05)
                    output=driver.communicate(timeout=5)[0].decode(errors='replace')
                    self.assertEqual(driver.returncode,0,output)
                    self.assertEqual(task.wait(timeout=5),0)
                    self.assertTrue(event.exists(),'CLI browser-open handoff must have actually executed')
                    self.assertIn('UDS Watch:',viewer_log.read_text(errors='replace'))
                    viewer.send_signal(signal.SIGINT);self.assertEqual(viewer.wait(timeout=5),0)
                    print(output.strip())
                finally:
                    release_prepare.touch();release_verify.touch()
                    if driver is not None and driver.poll() is None:driver.terminate();driver.communicate(timeout=5)
                    if viewer is not None and viewer.poll() is None:viewer.send_signal(signal.SIGINT);viewer.wait(timeout=5)
                    if gold is not None:gold.close()
                    if gold_integrity is not None:gold_integrity.close()
                    if task is not None and task.poll() is None:
                        # Only this explicitly owned action-only SDK process group.
                        os.killpg(task.pid,signal.SIGINT);task.wait(timeout=15)


if __name__=='__main__':unittest.main()
