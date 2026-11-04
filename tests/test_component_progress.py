"""Isolated fixtures: sequential shared charts and packaged optional selection."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from uds_deploy.native import NativeReader,definition_owners,record_report,report,unselected_components


def packages():
    return {'core':{'kind':'ZarfPackageConfig','metadata':{'name':'packaged-core'},'components':[
        {'name':name,'required':required,'charts':[{'name':'gateway'},{'name':'uds-istio-config'}]}
        for name,required in [('admin',True),('tenant',True),('passthrough',False)]
    ]}}


def state():
    return {'reports':[],'mode':'observed','source':{'kind':'stock-process','output_complete':True},'packages':[]}


def add(target,owners,message,**fields):
    item=report(json.dumps(dict(msg=message,**fields)))
    item['log_id']=len(target['reports'])+1
    return record_report(target,item,owners)


class SharedChartTests(unittest.TestCase):
    def test_shared_charts_keep_each_explicit_component_scope_and_log_identity(self):
        owners=definition_owners(packages());target=state()
        for component in ('admin','tenant'):
            boundary=add(target,owners,'deploying component',name=component)
            for chart in ('gateway','uds-istio-config'):
                for message in ('processing Helm chart','performing Helm upgrade','running health checks'):
                    item=add(target,owners,message,chart=chart)
                    self.assertEqual(item['definition_owner']['component'],component)
                    self.assertEqual(item['scope_evidence'],'explicit-sequential-cli-component-start')
                    self.assertEqual(item['scope_log_id'],boundary['log_id'])
        helm=[r for r in target['reports'] if r['kind'].startswith('helm.') or r['kind']=='health.wait']
        self.assertEqual(len(helm),12,'Repeated chart names must not overwrite the previous component reports')
        self.assertEqual(len({r['id'] for r in helm}),12)
        self.assertTrue(all(r['status']=='reported' and 'inferred_complete' not in r for r in helm))
        self.assertEqual({r['definition_owner']['component'] for r in helm},{'admin','tenant'})

    def test_shared_images_do_not_lose_component_batch_completions(self):
        definitions=packages()
        for component in definitions['core']['components']:
            component['images']=['example/shared:1','example/'+component['name']+':1']
        owners=definition_owners(definitions);target=state()
        for component in ('admin','tenant'):
            add(target,owners,'deploying component',name=component)
            shared=add(target,owners,'pushing image',name='example/shared:1')
            self.assertEqual(shared['definition_owner']['component'],component)
            add(target,owners,'pushing image',name='example/'+component+':1')
            done=add(target,owners,'done pushing images',count=2)
            self.assertEqual(done['definition_owner']['component'],component)
            self.assertEqual(done['scope_evidence'],'explicit-cli-component-start-and-image-pushes')
        self.assertEqual(len([r for r in target['reports'] if r['message']=='done pushing images']),2)
        self.assertEqual(len([r for r in target['reports'] if r['resource']=='example/shared:1']),2)
        missing=state();add(missing,owners,'deploying component',name='admin')
        self.assertNotIn('definition_owner',add(missing,owners,'done pushing images',count=2),'A component boundary alone is not image batch completion proof')
        for field,value in [('output_complete',False),('single_cli',False)]:
            limited=state();limited['source'][field]=value
            add(limited,owners,'deploying component',name='admin')
            self.assertNotIn('definition_owner',add(limited,owners,'pushing image',name='example/shared:1'))
            self.assertNotIn('definition_owner',add(limited,owners,'done pushing images',count=2))

    def test_incomplete_concurrent_or_shared_task_streams_do_not_scope_reused_charts(self):
        variants=[]
        for field,value in [('output_complete',False),('activity_available',False),('single_cli',False)]:
            target=state();target['source'][field]=value;variants.append(target)
        for mode in ('parallel','concurrent'):
            target=state();target['mode']=mode;variants.append(target)
        target=state();target['packages']=[{'status':'deploying'},{'status':'deploying'}];variants.append(target)
        owners=definition_owners(packages())
        for target in variants:
            with self.subTest(source=target['source'],mode=target['mode']):
                add(target,owners,'deploying component',name='admin')
                self.assertNotIn('definition_owner',add(target,owners,'running health checks',chart='gateway'))

    def test_missing_unknown_and_package_boundaries_do_not_borrow_component_scope(self):
        owners=definition_owners(packages())
        for boundary in (None,('starting deploy',{'package':'packaged-core'}),('deploying component',{'name':'unknown-component'})):
            target=state()
            if boundary:
                add(target,owners,'deploying component',name='admin')
                add(target,owners,boundary[0],**boundary[1])
            self.assertNotIn('definition_owner',add(target,owners,'running health checks',chart='gateway'))
        duplicated=packages();duplicated['other']=copy.deepcopy(duplicated['core'])
        target=state();owners=definition_owners(duplicated)
        self.assertNotIn('definition_owner',add(target,owners,'deploying component',name='admin'))
        self.assertNotIn('definition_owner',add(target,owners,'running health checks',chart='gateway'))


class OptionalSelectionTests(unittest.TestCase):
    def test_required_default_and_requested_components_remain_expected(self):
        package={'components':[
            {'name':'required','required':True},{'name':'default','default':True},
            {'name':'metrics-server'},{'name':'passthrough','required':False},
            {'name':'unset-required'},{'name':'grouped','group':'choice'}]}
        selected=unselected_components({'kind':'UDSBundle'},{'optionalComponents':['metrics-server']},package)
        self.assertEqual(selected,{'passthrough','unset-required'})
        self.assertEqual(unselected_components({'kind':'UDSBundle'},{},package),{'metrics-server','passthrough','unset-required'})
        self.assertEqual(unselected_components({'kind':'ZarfPackageConfig'},{},package),set(),'Do not guess selection for direct interactive/native package deploys')
        self.assertEqual(unselected_components({'kind':'UDSBundle'},{},dict(package,apiVersion='unknown/v9')),set(),'Unknown schema defaults must not hide expected work')
        for unknown in ('metrics-server',['*'],['!passthrough'],[None]):
            self.assertEqual(unselected_components({'kind':'UDSBundle'},{'optionalComponents':unknown},package),set())

    def test_v1beta1_required_default_is_not_the_legacy_alpha_default(self):
        package={'apiVersion':'zarf.dev/v1beta1','components':[
            {'name':'required'},{'name':'optional','optional':True},{'name':'default','optional':True,'default':True}]}
        self.assertEqual(unselected_components({'kind':'UDSBundle'},{},package),{'optional'})

    def test_reader_projects_selection_without_changing_packaged_yaml_or_runtime_outcome(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'console.log';path.write_bytes(b'')
            packaged=packages();bundle={'kind':'UDSBundle','metadata':{'name':'fixture'},'packages':[{'name':'core','optionalComponents':[]}]}
            process={'pid':os.getpid(),'tool':'uds','args':['uds','deploy','fixture.tar.zst'],'kind':'deployment process'}
            files=[{'fd':fd,'type':'REG','path':str(path)} for fd in ('1','2')]
            files.append({'fd':'cwd','type':'DIR','path':directory})
            reader=NativeReader();self.addCleanup(reader.close)
            with patch('uds_deploy.native.open_files',return_value=files),patch('uds_deploy.native.metadata',return_value=(bundle,packaged)),patch.dict(os.environ,{'KUBECONFIG':''}):
                reader.attach(process)
            session=next(iter(reader.sessions.values()));target=session['state']
            components=target['packages'][0]['attempts'][0]['execution']['components']
            skipped=next(c for c in components if c['id']=='passthrough')
            self.assertEqual(skipped['selection'],'not-selected');self.assertFalse(skipped['expected'])
            self.assertEqual(skipped['status'],'pending');self.assertFalse(skipped['observed'])
            self.assertTrue(all(c['expected'] for c in components if c['id']!='passthrough'))
            self.assertNotIn('selection',packaged['core']['components'][-1])
            self.assertIn('passthrough',reader.definition(target['id'],'core')['yaml'])
            add(target,definition_owners(packaged),'deploying component',name='passthrough')
            self.assertTrue(skipped['expected']);self.assertEqual(skipped['selection'],'observed','Actual CLI evidence overrides packaged optional selection')
            self.assertEqual(skipped['status'],'pending','Do not fabricate lifecycle callbacks')


if __name__=='__main__':unittest.main()
