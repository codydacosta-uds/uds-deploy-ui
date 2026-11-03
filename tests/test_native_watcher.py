"""Stock process discovery, trusted-file attribution, reports vs verified outcomes."""
# Standalone adaptation of Apache-2.0 regression tests; see NOTICE.
import base64
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from uds_deploy import native
from uds_deploy.native import NativeReader, report, action_labels, record_report, definition_owners, processes


class NativeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.output=self.root/'console.log';self.output.write_bytes(b'')
        self.process=dict(pid=os.getpid(),tool='uds',args=['uds','deploy','bundle.tar.zst'],kind='deployment process')
        self.definition=dict(metadata=dict(name='actual-bundle',version='1'),packages=[dict(name='actual-alias',ref='1')])
        self.package=dict(metadata=dict(name='actual-zarf-name',version='1'),components=[dict(name='actual-component',images=['example/image:1.0.0'],charts=[dict(name='podinfo',releaseName='actual-release',namespace='fixture')],actions={'onDeploy':{'before':[{'cmd':"echo 'before action'; sleep 1"}],'after':[{'cmd':"echo 'after action'; sleep 1"}]}})])
        self.reader=NativeReader();self.addCleanup(self.reader.close)
        self.files=[dict(fd='cwd',type='DIR',path=str(self.root)),dict(fd='1',type='REG',path=str(self.output)),dict(fd='2',type='REG',path=str(self.output)),dict(fd='txt',type='REG',path='/opt/homebrew/bin/uds')]
        self.patches=[patch('uds_deploy.native.processes',return_value=[self.process]),patch('uds_deploy.native.open_files',return_value=self.files),patch('uds_deploy.native.metadata',return_value=(self.definition,{'actual-alias':self.package})),patch.dict(os.environ,{'KUBECONFIG':''})]
        for p in self.patches:p.start();self.addCleanup(p.stop)
    def refresh(self):self.reader.scanned=0;self.reader.refresh()
    def test_package_starts_accept_bundle_alias_and_packaged_name(self):
        owners=definition_owners({'actual-alias':self.package})
        for name in ('actual-alias','actual-zarf-name'):
            item=record_report({'reports':[]},report(json.dumps({'msg':'starting deploy','package':name})),owners)
            self.assertEqual(item['definition_owner']['package'],'actual-alias')
        shared=definition_owners({'first':self.package,'second':self.package})
        ambiguous=record_report({'reports':[]},report(json.dumps({'msg':'starting deploy','package':'actual-zarf-name'})),shared)
        self.assertNotIn('definition_owner',ambiguous)

    def test_messages_remain_reports_not_execution_or_success(self):
        for line in ('Ready; performing Helm upgrade','action succeeded',json.dumps(dict(msg='unrecognized operation')),json.dumps(dict(msg=['performing Helm upgrade']))):self.assertIsNone(report(line))
        for line in ('2026-11-01 12:00:00 INF performing Helm upgrade chart=real-chart',json.dumps(dict(msg='done pushing images',count=1,execution_package='impostor'))):
            event=report(line)
            self.assertEqual(event['status'],'reported')
            self.assertEqual(event['evidence'],'cli-report')
            self.assertNotIn('package_id',event)
        labels=action_labels({'actual-alias':self.package})
        before=report("2026-11-01 12:00:00 INF running command cmd=echo 'before action'; sleep 1")
        after=report("2026-11-01 12:00:00 INF running command cmd=echo 'after action'; sleep 1")
        self.assertEqual(labels[before['action_id']],'Pre-deploy action')
        self.assertEqual(labels[after['action_id']],'Post-deploy action')
        self.assertNotEqual(before['action_id'],after['action_id'])
    def test_action_descriptions_and_full_error_commands_share_one_declared_action(self):
        action=self.package['components'][0]['actions']['onDeploy']['before'][0]
        action['description']='Prepare actual resource'
        self.output.write_text('2026-11-01 12:00:00 INF running command cmd=Prepare actual resource\n'+'ERROR: failed to deploy bundle: unable to deploy component "actual-component": unable to run component before action: command '+json.dumps(action['cmd'])+' failed after 0 retries\n')
        self.refresh();state=self.reader.list()[0];actions=[r for r in state['reports'] if r['kind']=='actions.command']
        self.assertEqual(len(actions),1);self.assertEqual(actions[0]['message'],'action failed')
        self.assertEqual(actions[0]['resource'],'Prepare actual resource');self.assertIn('declaration_id',actions[0])
        self.assertNotIn(action['cmd'],actions[0]['resource'])
    def test_ambiguous_actions_are_not_merged_or_given_a_guessed_description(self):
        first=self.package['components'][0]['actions']['onDeploy']['before'][0]
        first['description']='First declared action'
        second=dict(first,description='Second declared action')
        self.package['components'][0]['actions']['onDeploy']['before'].append(second)
        raw=report(json.dumps(dict(msg='running command',cmd=first['cmd'])))['action_id']
        self.assertNotIn(raw,native.action_declarations({'alias':self.package}))
        self.assertNotIn(raw,native.action_names({'alias':self.package}))
        first_key=report(json.dumps(dict(msg='running command',cmd=first['description'])))['action_id']
        second_key=report(json.dumps(dict(msg='running command',cmd=second['description'])))['action_id']
        identities=native.action_declarations({'alias':self.package})
        self.assertNotEqual(identities[first_key],identities[second_key])
    def test_global_flags_do_not_hide_a_deployment_or_its_package_selection(self):
        self.definition['packages'].append(dict(name='not-selected',ref='2'))
        for prefix in (['--log-level','info'],['--no-color','-linfo'],['--architecture=amd64','--no-progress']):
            args=['uds']+prefix+['deploy','bundle.tar.zst','-p','actual-alias']
            self.assertEqual(native.command_args(args),['deploy','bundle.tar.zst','-p','actual-alias'])
            process=dict(self.process,args=args)
            output=('123 '+str(os.getuid())+' uds '+' '.join(args)+'\n').encode()
            with patch('uds_deploy.native.subprocess.check_output',return_value=output):self.assertEqual(processes()[0]['args'],args)
            reader=NativeReader();self.addCleanup(reader.close);reader.attach(process)
            self.assertEqual([p['id'] for p in next(iter(reader.sessions.values()))['state']['packages']],['actual-alias'])
        self.assertEqual(native.command_args(['uds','--unknown-arity','deploy','bundle.tar.zst']),[])
    def test_late_attachment_scopes_from_args_and_preserves_original_bytes(self):
        raw=b'2026-11-01 12:00:00 INF performing Helm install chart=podinfo\n  exact CRLF  \r\n\xff\n'
        self.output.write_bytes(raw);self.refresh()
        state=self.reader.list()[0];self.assertTrue(state['source']['output_complete'])
        self.assertEqual(state['bundle_name'],'actual-bundle')
        self.assertEqual(state['packages'][0]['id'],'actual-alias')
        self.assertEqual(state['packages'][0]['attempts'][0]['execution']['components'][0]['id'],'actual-component')
        rows=self.reader.events(state['id'],logs=True)
        self.assertEqual(b''.join(base64.b64decode(row['data']['raw_b64']) for row in rows),raw)
        self.assertTrue(all(row['package']=='actual-alias' for row in rows))
        self.assertEqual(len(state['reports']),1)
        phases=state['packages'][0]['attempts'][0]['execution']['components'][0]['phases']
        self.assertTrue(all(p['status']=='pending' and not p['observed'] for p in phases))
        events=self.reader.events(state['id'])
        self.assertEqual(sorted(e['event_cursor'] for e in events),[e['event_cursor'] for e in events])
        self.assertEqual([r['id'] for r in rows],[1,2,3])
    def test_partial_writes_and_event_replay_do_not_duplicate_original_lines(self):
        self.output.write_bytes(b'2026-11-01 12:00:00 INF pushing image name=example/image:1.0.0')
        self.refresh();state=self.reader.list()[0];self.assertEqual(self.reader.events(state['id'],logs=True),[])
        with self.output.open('ab') as output:output.write(b'\nsecond line\n')
        self.refresh();rows=self.reader.events(state['id'],logs=True)
        self.assertEqual(len(rows),2)
        self.assertEqual(rows[0]['id'],1);self.assertEqual(rows[1]['id'],2)
        cursor=self.reader.get(state['id'])['cursor']
        with self.output.open('ab') as output:output.write(b'third line\n')
        self.refresh();events=self.reader.events(state['id'],after=cursor)
        self.assertEqual(len(events),1);self.assertEqual(events[0]['id'],3)
        self.assertEqual(events[0]['type'],'log')
        self.assertEqual(self.reader.events(state['id'],logs=True,after=2)[0]['data']['raw'],'third line\n')
    def test_exit_code_is_not_guessed_from_success_words_or_sentinels(self):
        self.output.write_bytes(b'2026-11-01 12:00:00 INF action succeeded cmd=echo hello\n___UDS_DONE_0___\n')
        self.refresh();state=self.reader.list()[0]
        with patch('uds_deploy.native.processes',return_value=[]):self.refresh()
        final=self.reader.get(state['id'])
        self.assertEqual(final['status'],'unknown')
        self.assertEqual(final['packages'][0]['status'],'unknown')
        self.assertNotIn('exit_code',final)
    def test_tty_is_never_opened_and_native_log_is_explicitly_partial(self):
        files=[dict(fd='cwd',type='DIR',path=str(self.root)),dict(fd='1',type='CHR',path='/dev/ttys000'),dict(fd='2',type='CHR',path='/dev/ttys000'),dict(fd='4',type='REG',path=str(self.root/'uds-native.log'))]
        (self.root/'uds-native.log').write_text('native diagnostic log\n')
        with patch('uds_deploy.native.open_files',return_value=files):self.refresh()
        state=self.reader.list()[0]
        self.assertFalse(state['source']['output_complete'])
        self.assertIn('omits some console progress',state['source']['note'])
    def test_capture_loss_does_not_leave_last_report_claiming_a_live_feed(self):
        self.output.write_text("2026-11-01 12:00:00 INF running command cmd=echo 'before action'; sleep 1\n")
        self.refresh();session=next(iter(self.reader.sessions.values()))
        self.assertTrue(session['state']['reports'])
        session['capture']={'record':self.root/'missing-capture.json'}
        session['capture_missing_since']=native.time.monotonic()-3
        self.refresh();source=session['state']['source']
        self.assertFalse(source['output_complete']);self.assertFalse(source['activity_available'])
        self.assertIn('capture stopped',source['note']);self.assertEqual(session['state']['status'],'deploying')
    def test_generated_manifest_chart_has_exact_definition_owner_and_release(self):
        import hashlib
        self.package['components'][0]['manifests']=[dict(name='actual-manifest',namespace='fixture',files=['private.yaml'])]
        name='raw-actual-zarf-name-actual-component-actual-manifest'
        self.output.write_text('2026-11-01 12:00:00 INF performing Helm upgrade chart='+name+'\n')
        self.refresh();state=self.reader.list()[0]
        self.assertEqual(state['reports'][0]['definition_owner']['component'],'actual-component')
        component=state['packages'][0]['attempts'][0]['execution']['components'][0]
        phase=next(p for p in component['phases'] if p['resource'].get('manifest')=='actual-manifest')
        self.assertEqual(phase['resource']['chart'],name)
        self.assertEqual(phase['resource']['release'],'zarf-'+hashlib.sha1(name.encode()).hexdigest())
        self.assertEqual(phase['resource']['namespace'],'fixture')
        self.assertFalse(phase['observed']);self.assertEqual(phase['status'],'pending')
        self.assertNotIn(('helm','raw-actual-alias-actual-component-actual-manifest'),native.definition_owners({'actual-alias':self.package}))
    def test_old_helm_revision_is_not_proof_of_this_deployment(self):
        self.refresh();session=next(iter(self.reader.sessions.values()))
        projected=b'actual-release 4 deployed 2020-01-01T12:00:00Z\n'
        with patch.dict(os.environ,{'KUBECONFIG':'explicit-test-kubeconfig'}),patch('uds_deploy.native.subprocess.check_output',return_value=projected):
            self.reader.check_helm(session)
        check=session['state']['checks'][0]
        self.assertEqual(check['status'],'deployed')
        self.assertFalse(check['current_deployment'])
        self.assertNotIn('data',check)
    def test_package_selection_filters_definitions_and_cluster_targets(self):
        self.definition['packages'].append(dict(name='not-selected',ref='2'))
        for flags in (['--packages','actual-alias'],['--packages=actual-alias'],['-p','actual-alias'],['-pactual-alias']):
            with self.subTest(flags=flags):
                reader=NativeReader();self.addCleanup(reader.close)
                process=dict(self.process,args=self.process['args']+flags)
                with patch('uds_deploy.native.metadata',return_value=(self.definition,{'actual-alias':self.package,'not-selected':self.package})):reader.attach(process)
                state=reader.list()[0]
                self.assertEqual([p['id'] for p in state['packages']],['actual-alias'])
                self.assertEqual(list(next(iter(reader.sessions.values()))['definitions']),['actual-alias'])
                self.assertEqual(state['packages'][0]['status'],'unknown')
                self.assertIsNone(state['packages'][0]['started_at'])
    def test_high_volume_original_paging_survives_bounded_event_replay(self):
        raw=b''.join(('original line %05d\n'%i).encode() for i in range(1,12001))
        self.output.write_bytes(raw)
        for _ in range(3):self.refresh()
        state=self.reader.list()[0];run=state['id']
        session=next(iter(self.reader.sessions.values()))
        self.assertEqual(state['log_cursor'],12000)
        self.assertLessEqual(len(session['events']),500)
        self.assertLessEqual(len(session['log_index']),95)
        latest=self.reader.events(run,logs=True,latest=True,limit=100)
        self.assertEqual([r['id'] for r in latest],list(range(11901,12001)))
        earlier=self.reader.events(run,logs=True,latest=True,before=1200,limit=100)
        self.assertEqual([r['id'] for r in earlier],list(range(1100,1200)))
        search=self.reader.events(run,logs=True,search='line 07502')
        self.assertEqual([r['id'] for r in search],[7502])
        replay=self.reader.events(run,after=1)
        self.assertEqual(replay[0]['type'],'observer.gap')
        recovered=[];after=0
        while True:
            page=self.reader.events(run,logs=True,after=after,limit=1000)
            if not page:break
            recovered.extend(base64.b64decode(r['data']['raw_b64']) for r in page);after=page[-1]['id']
        self.assertEqual(b''.join(recovered),raw)
    def test_cluster_queries_are_bounded_project_metadata_and_freeze_terminal_runs(self):
        self.package['components'][0]['charts']=[dict(name='chart'+str(i),namespace='ns'+str(i)) for i in range(3)]
        self.refresh();session=next(iter(self.reader.sessions.values()))
        session['state']['completed_at']=__import__('time').time()
        def output(command,**kwargs):
            self.assertIn('--no-headers',command)
            self.assertTrue(any(value.startswith('custom-columns=') for value in command))
            namespace=command[command.index('-n')+1]
            return ('chart'+namespace[-1]+' 2 deployed 2020-01-01T12:00:00Z\n').encode()
        with patch.dict(os.environ,{'KUBECONFIG':'explicit-test-kubeconfig'}),patch('uds_deploy.native.subprocess.check_output',side_effect=output) as query:
            self.reader.check_helm(session)
            self.assertEqual(query.call_count,2)
            self.assertFalse(session.get('checks_final',False))
            session['checked']=0;self.reader.check_helm(session)
            self.assertEqual(len(session['state']['checks']),3)
            self.assertTrue(session['checks_final'])
            query.reset_mock();session['checked']=0;self.reader.check_helm(session)
            query.assert_not_called()
    def test_sdk_truncated_action_display_has_exact_definition_ownership(self):
        command="echo 'pkg1 / prepare — checking the local deployment context'; sleep 12"
        package={'metadata':{'name':'pkg1'},'components':[{'name':'prepare','actions':{'onDeploy':{'before':[{'cmd':command}]}}}]}
        owners=definition_owners({'pkg1':package})
        display=(command.encode()[:57]+b'...').decode()
        item=report('2026-11-01 12:00:00 INF running command cmd='+display)
        state={'packages':[{'id':'pkg1','status':'unknown'}]};record_report(state,item,owners)
        self.assertEqual(state['reports'][0]['definition_owner']['component'],'prepare')
        self.assertEqual(state['packages'][0]['status'],'unknown')
        self.assertEqual(action_labels({'pkg1':package})[item['action_id']],'Pre-deploy action')
        # Two resources with the same SDK-truncated display remain ambiguous.
        other={'metadata':{'name':'pkg2'},'components':[{'name':'different','actions':{'onDeploy':{'before':[{'cmd':command+' && true'}]}}}]}
        state={};record_report(state,item,definition_owners({'pkg1':package,'pkg2':other}))
        self.assertNotIn('definition_owner',state['reports'][0])
    def test_report_links_declared_resources_without_claiming_runtime_identity(self):
        owners=definition_owners({'actual-alias':self.package})
        item=report('2026-11-01 12:00:00 INF performing Helm install chart=podinfo')
        state={'packages':[{'id':'actual-alias','status':'unknown'}]};record_report(state,item,owners)
        self.assertEqual(state['reports'][0]['definition_owner'],dict(package='actual-alias',component='actual-component',evidence='artifact-definition'))
        self.assertNotIn('package_id',state['reports'][0])
        self.assertEqual(state['packages'][0]['status'],'unknown')
        other=json.loads(json.dumps(self.package));other['metadata']['name']='other'
        state={};record_report(state,item,definition_owners({'actual-alias':self.package,'second-alias':other}))
        self.assertNotIn('definition_owner',state['reports'][0])
    def test_macos_full_path_truncated_comm_is_detected_without_other_users(self):
        uid=os.getuid()
        output=('101 {0} /opt/homebrew/bi /opt/homebrew/bin/uds deploy /tmp/bundle.tar.zst --packages=pkg2\n'
                '102 {0} zarf zarf package deploy /tmp/package.tar.zst\n'
                '103 {0} /different/path /opt/homebrew/bin/uds deploy /tmp/bundle.tar.zst\n'
                '104 {1} uds uds deploy /tmp/other-user.tar.zst\n'
                '105 {0} uds uds inspect /tmp/bundle.tar.zst\n').format(uid,uid+1).encode()
        with patch('uds_deploy.native.subprocess.check_output',return_value=output):found=processes()
        self.assertEqual([(p['pid'],p['tool']) for p in found],[(101,'uds'),(102,'zarf')])
    def test_packaged_yaml_keeps_full_values_in_memory_without_reopening(self):
        self.definition.update(kind='UDSBundle',build={'architecture':'arm64'},variables=[{'name':'PASSWORD','default':'bundle-private-canary'}])
        self.definition['packages'][0]['ref']='1@sha256:'+'a'*64
        self.package.update(kind='ZarfPackageConfig',build={'architecture':'arm64'})
        self.package['components'][0]['charts'][0]['version']='6.17.0'
        self.package['variables']=[{'name':'TOKEN','default':'package-private-canary'}]
        self.refresh();state=self.reader.list()[0];run=state['id']
        self.assertEqual(state['artifact_info']['architecture'],'arm64')
        self.assertTrue(state['artifact_info']['has_yaml'])
        self.assertEqual(state['packages'][0]['artifact_info']['digest'],'sha256:'+'a'*64)
        component=state['packages'][0]['attempts'][0]['execution']['components'][0]
        self.assertEqual(component['artifact_info']['charts'][0]['version'],'6.17.0')
        bundle=self.reader.definition(run);package=self.reader.definition(run,'actual-alias')
        self.assertEqual(bundle['filename'],'uds-bundle.yaml');self.assertEqual(package['filename'],'zarf.yaml')
        self.assertNotIn('private-canary',json.dumps(state),'Raw artifact values belong in the explicit YAML view, not every state response')
        self.assertIn('bundle-private-canary',bundle['yaml']);self.assertIn('package-private-canary',package['yaml'])
        self.assertFalse(bundle['values_hidden']);self.assertFalse(package['values_hidden'])
        self.definition['metadata']['name']='changed-after-attach'
        self.assertIn('actual-bundle',self.reader.definition(run)['yaml'])
        self.assertNotIn('changed-after-attach',self.reader.definition(run)['yaml'])
        with self.assertRaises(KeyError):self.reader.definition(run,'not-selected')
    def test_image_progress_is_per_image_cli_data_not_completion(self):
        item=report('2026-11-01 20:35:08 INF image push in progress name=registry/image:12.0 complete=43.0% remaining=161.83 MBs')
        self.assertEqual(item['kind'],'images.push');self.assertEqual(item['resource'],'registry/image:12.0')
        self.assertEqual(item['image_percent'],43.0);self.assertEqual(item['status'],'reported')
        self.assertNotIn('image_percent',report(json.dumps(dict(msg='image push in progress',complete='43.0%'))))
        state={};record_report(state,item);record_report(state,report(json.dumps(dict(msg='pushing image',name=item['resource']))))
        self.assertNotIn('image_percent',state['reports'][0],'A new transfer must not inherit an old percentage')
        full=report(json.dumps(dict(msg='image push in progress',name='registry/image:12.0',complete='100.0%')))
        self.assertEqual(full['image_percent'],100.0);self.assertEqual(full['message'],'image push in progress')
        for bad in ['101%','-1%','NaN%','all done',None]:
            self.assertNotIn('image_percent',report(json.dumps(dict(msg='image push in progress',name='registry/image:12.0',complete=bad))))
    def test_batch_image_completion_requires_explicit_component_scope_and_pushes(self):
        second=dict(metadata={'name':'second-package'},components=[dict(name='second-component',images=['example/second:1'])])
        owners=definition_owners({'actual-alias':self.package,'second-alias':second});state={'reports':[]}
        def add(message):return record_report(state,report('2026-11-01 18:00:00 INF '+message),owners)
        add('deploying component name=actual-component');add('pushing image name=example/image:1.0.0');add('image push in progress name=example/image:1.0.0 complete=100.0% remaining=0 B')
        first=add('done pushing images count=1')
        self.assertEqual(first['definition_owner']['package'],'actual-alias')
        self.assertEqual(first['scope_evidence'],'explicit-cli-component-start-and-image-pushes')
        add('deploying component name=second-component');add('pushing image name=example/second:1')
        last=add('done pushing images count=1')
        self.assertEqual(last['definition_owner']['package'],'second-alias')
        self.assertEqual(len([r for r in state['reports'] if r['message']=='done pushing images']),2,'Do not overwrite the earlier package completion with the later aggregate')
        missing={'reports':[]};record_report(missing,report('2026-11-01 18:00:00 INF pushing image name=example/image:1.0.0'),owners)
        record_report(missing,report('2026-11-01 18:00:00 INF performing Helm upgrade chart=podinfo'),owners)
        unknown=record_report(missing,report('2026-11-01 18:00:00 INF done pushing images count=1'),owners)
        self.assertNotIn('definition_owner',unknown,'Do not infer an image completion owner from advancing to Helm')
        reset={'reports':[]}
        for message in ['deploying component name=actual-component','pushing image name=example/image:1.0.0','starting deploy package=second-package','done pushing images count=1']:result=record_report(reset,report('2026-11-01 18:00:00 INF '+message),owners)
        self.assertNotIn('definition_owner',result,'A new package boundary must invalidate the previous component scope')
    def test_task_console_requires_same_user_uds_ancestor_and_combined_regular_file(self):
        uid=os.getuid();pid=self.process['pid']
        rows='{} 123 {} /bin/uds uds deploy bundle.tar.zst\n123 1 {} /opt/homebrew/bi /opt/homebrew/bin/uds run bundle-deploy-specific-packages\n'.format(pid,uid,uid)
        with patch('uds_deploy.native.subprocess.check_output',return_value=rows.encode()):
            sources=native.task_console(pid);self.assertEqual({r['fd'] for r in sources},{'1','2'})
        with patch('uds_deploy.native.subprocess.check_output',return_value=rows.replace('123 1 '+str(uid),'123 1 '+str(uid+1)).encode()):self.assertEqual(native.task_console(pid),[])
        with patch('uds_deploy.native.subprocess.check_output',return_value=rows.replace('uds run bundle-deploy-specific-packages','uds deploy other.tar.zst').encode()):self.assertEqual(native.task_console(pid),[])
        with patch('uds_deploy.native.subprocess.check_output',return_value=rows.encode()),patch('uds_deploy.native.open_files',return_value=[dict(fd='1',type='FIFO',path='pipe'),dict(fd='2',type='CHR',path='/dev/ttys000')]):self.assertEqual(native.task_console(pid),[])
    def test_stock_terminal_action_error_is_reported_without_fabricating_exit(self):
        self.package['components'][0]['name']='real-component'
        action=self.package['components'][0]['actions']['onDeploy']['before'][0]
        action['description']='Deliberate test action'
        owners=native.definition_owners({'actual-alias':self.package});state={'reports':[],'status':'deploying'}
        line='     ERROR:  failed to deploy bundle: unable to deploy component "real-component": unable to run component before action: command "Deliberate test action" failed after 0 retries'
        item=native.report(line);self.assertEqual(item['message'],'action failed')
        self.assertEqual(native.report('\x1b[96mWaiting for task\x1b[0m\r\x1b[K\r     '+line),item,'A task spinner prefix must not swallow the final CLI error')
        native.record_report(state,item,owners)
        self.assertEqual(state['reports'][0]['definition_owner']['component'],'real-component')
        self.assertIn('failed after 0 retries',state['reports'][0]['error'])
        self.assertEqual(state['status'],'deploying');self.assertNotIn('exit_code',state)
        wrong=native.report(line.replace('"real-component"','"another-component"'))
        other={'reports':[]};native.record_report(other,wrong,owners)
        self.assertNotIn('definition_owner',other['reports'][0],'A mismatched component must not borrow an action owner')
        generic=native.report('ERROR: failed to deploy bundle: unable to load package')
        self.assertEqual(generic['kind'],'deployment.error');self.assertIsNone(generic['action_id'])
        validation=native.report('ERROR: failed to validate bundle: arch amd64 does not match cluster arch, [arm64]')
        self.assertEqual(validation['kind'],'deployment.error');self.assertIn('arch amd64',validation['error'])
        self.assertIsNone(native.report('An application wrote ERROR but this is not a stock terminal error'))
    def test_sdk_action_error_fields_recover_and_ambiguous_delimiters_stay_unassigned(self):
        self.package['components'][0]['name']='real-component'
        self.package['components'][0]['actions']['onDeploy']['before']=[{'cmd':'echo test'}]
        owners=native.definition_owners({'actual-alias':self.package});state={'reports':[]}
        failed=native.report('2026-11-01 18:00:00 WRN action failed cmd=echo test err=command failed: exit status 7')
        native.record_report(state,failed,owners)
        self.assertEqual(state['reports'][0]['definition_owner']['component'],'real-component')
        self.assertIn('exit status 7',state['reports'][0]['error'])
        native.record_report(state,native.report('2026-11-01 18:00:01 INF action succeeded cmd=echo test'),owners)
        self.assertEqual(len(state['reports']),1);self.assertEqual(state['reports'][0]['message'],'action succeeded');self.assertIsNone(state['reports'][0]['error'])
        ambiguous=native.report('2026-11-01 18:00:00 WRN action failed cmd=echo test err=part of the command err=real failure')
        other={'reports':[]};native.record_report(other,ambiguous,owners)
        self.assertNotIn('definition_owner',other['reports'][0],'Do not match a command prefix across ambiguous err fields')
    def test_missing_process_start_is_unknown_not_attach_time(self):
        import subprocess
        with patch('uds_deploy.native.subprocess.check_output',side_effect=subprocess.CalledProcessError(1,['ps'])):self.refresh()
        self.assertIsNone(self.reader.list()[0]['started_at'])
    def test_task_owned_processes_are_not_double_attached(self):
        self.reader.excluded={os.getpid()};self.refresh();self.assertEqual(self.reader.list(),[])
    def test_exact_cluster_connection_reports_remain_cli_claims(self):
        waiting=native.report('2026-11-02 11:48:00 INF waiting for cluster connection')
        ready=native.report('2026-11-02 11:48:01 DBG done waiting for cluster, connected duration=1s')
        self.assertEqual(waiting['kind'],'cluster.connect')
        self.assertEqual(ready['kind'],'cluster.connected')
        self.assertEqual(ready['status'],'reported')
        self.assertIsNone(native.report('application says connected to cluster'))
    def test_reports_preserve_first_log_position_when_updated(self):
        state={'reports':[]}
        started=native.report('2026-11-01 18:00:00 INF running command cmd=echo test')
        started['log_id']=7;record_report(state,started)
        finished=native.report('2026-11-01 18:00:01 INF action succeeded cmd=echo test')
        finished['log_id']=29;record_report(state,finished)
        self.assertEqual(len(state['reports']),1)
        self.assertEqual(state['reports'][0]['first_log_id'],7)
        self.assertEqual(state['reports'][0]['log_id'],29)
        record_report(state,dict(state['reports'][0]))
        self.assertEqual(state['reports'][0]['first_log_id'],7)
    def test_report_memory_is_bounded_and_does_not_mutate_package_results(self):
        state={'reports':[],'packages':[dict(status='waiting')]}
        for index in range(2100):record_report(state,dict(kind='helm.install',label='Helm install',resource='chart-'+str(index),evidence='cli-report',status='reported'))
        self.assertEqual(len(state['reports']),2048)
        self.assertEqual(state['packages'][0]['status'],'waiting')


if __name__=='__main__':unittest.main()
