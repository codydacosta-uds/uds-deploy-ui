"""Private optional grouping, identity binding and conservative runner outcomes."""
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from uds_deploy.runs import RunReader, publish, run_home, validate
from uds_deploy.server import WatcherStore


def record():
    now=time.time()
    return dict(schema_version=1,id='a'*32,label='Concurrent fixture',started_at=now,completed_at=None,exit_code=None,
                layers=[dict(id='prepare',label='Prepare'),dict(id='parallel',label='Parallel jobs')],
                jobs=[dict(id=name,label=name,layer=layer,packages=[name],dependencies=deps,pid=None,started_at=None,completed_at=None,exit_code=None)
                      for name,layer,deps in [('first','prepare',[]),('second','parallel',['first'])]])


class RunTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name);self.rows={100:dict(parent=1,start='fixture owner'),101:dict(parent=100,start='wrapper'),201:dict(parent=101,start='native')}
        for context in [patch.dict(os.environ,UDS_DEPLOY_RUNTIME_DIR=str(self.root/'runtime')),patch('uds_deploy.runs.process_table',side_effect=lambda:self.rows),patch('uds_deploy.runs.os.getppid',return_value=100)]:
            context.start();self.addCleanup(context.stop)
        self.data=record();self.reader=RunReader()
    def refresh(self,children=None):
        self.reader.scanned=0;self.reader.refresh(children or {})
    def state(self):return self.reader.get('matrix-'+self.data['id'])
    def start(self,index=0,pid=101):
        self.data['jobs'][index].update(pid=pid,started_at=time.time());publish(self.data)
    def finish(self,index=0,code=0):
        self.data['jobs'][index].update(completed_at=time.time(),exit_code=code);publish(self.data)

    def test_private_atomic_records_and_no_unrelated_fields(self):
        publish(self.data);path=run_home()/(self.data['id']+'.json')
        self.assertEqual(path.stat().st_mode&0o777,0o600)
        self.assertEqual(run_home().stat().st_mode&0o777,0o700)
        self.assertEqual(json.loads(path.read_text())['pid'],100)
        self.assertEqual(list(run_home().glob('.snapshot-*')),[])
        for field in ('environment','config','kubeconfig','command'):
            with self.subTest(field=field),self.assertRaises(ValueError):publish(dict(self.data,**{field:'fixture value'}))

    def test_native_link_requires_runner_ancestry_and_exact_selection(self):
        self.start()
        child={'pid':201,'state':{'id':'native-fixture','packages':[{'id':'first'}],'source':{'single_cli':True}}}
        for mutate in ('unrelated','selection','shared'):
            bad=deepcopy(child)
            if mutate=='unrelated':self.rows[101]['parent']=999
            if mutate=='selection':bad['state']['packages']=[{'id':'other'}]
            if mutate=='shared':bad['state']['source']['single_cli']=False
            self.refresh({'child':bad});self.assertEqual(self.reader.child_ids(),set());self.rows[101]['parent']=100
        ambiguous=deepcopy(child);ambiguous.update(pid=202);ambiguous['state']['id']='another-native'
        self.rows[202]=dict(parent=101,start='second native')
        self.refresh({'first':child,'second':ambiguous});self.assertEqual(self.reader.child_ids(),set(),'An ambiguous launcher cannot pick an arbitrary log stream')
        self.rows.pop(202)
        self.refresh({'child':child});self.assertEqual(self.reader.child_ids(),{'native-fixture'})
        self.assertEqual(self.state()['matrix']['jobs'][0]['child_run_id'],'native-fixture')
        self.assertNotIn('status',child['state'],'Raw native state must not be rewritten')
        self.assertNotIn('pid',self.state()['matrix']['jobs'][0],'Process metadata is not UI job content')

    def test_process_disappearance_or_partial_results_never_mean_done(self):
        self.start();self.refresh();self.assertEqual(self.state()['status'],'deploying')
        self.rows.pop(100);self.refresh();self.assertEqual(self.state()['status'],'unknown')
        self.assertEqual(self.state()['matrix']['jobs'][0]['status'],'unknown')
        self.assertEqual(self.state()['matrix']['jobs'][1]['status'],'not-started')
        fresh=RunReader();fresh.refresh({});self.assertEqual(fresh.list(),[],'No saved run discovery after owner exit')

    def test_all_jobs_and_explicit_runner_result_required_for_done(self):
        self.start();self.finish();self.refresh();self.assertEqual(self.state()['status'],'deploying')
        self.start(1,102);self.finish(1);self.refresh();self.assertEqual(self.state()['status'],'deploying')
        self.data.update(completed_at=time.time(),exit_code=0);publish(self.data);self.refresh()
        self.assertEqual(self.state()['status'],'completed')
        self.rows.pop(100);self.refresh();self.assertEqual(self.state()['status'],'completed')
        self.assertEqual([j['exit_code'] for j in self.state()['matrix']['jobs']],[0,0])

    def test_parent_exit_zero_without_child_results_stays_unconfirmed(self):
        self.data.update(completed_at=time.time(),exit_code=0);publish(self.data);self.refresh()
        self.assertEqual(self.state()['status'],'unknown')

    def test_child_failure_and_blocked_work(self):
        self.start();self.finish(code=7)
        self.data.update(completed_at=time.time(),exit_code=1);publish(self.data);self.refresh()
        self.assertEqual(self.state()['status'],'failed')
        self.assertEqual([j['status'] for j in self.state()['matrix']['jobs']],['failed','not-started'])
        self.assertIsNone(self.state()['matrix']['jobs'][1]['started_at'])

    def test_invalid_records_permissions_and_symlinks_are_ignored(self):
        publish(self.data);path=run_home()/(self.data['id']+'.json')
        path.chmod(0o644);self.refresh();self.assertEqual(self.reader.list(),[])
        path.chmod(0o600);target=self.root/'outside';path.rename(target);path.symlink_to(target)
        self.refresh();self.assertEqual(self.reader.list(),[])
        with self.assertRaises(ValueError):publish(self.data)

    def test_pid_reuse_cannot_attach_old_record(self):
        publish(self.data);self.rows[100]['start']='another process'
        self.refresh();self.assertEqual(self.reader.list(),[])
        with self.assertRaises(ValueError):publish(self.data)

    def test_immutable_plan_terminal_results_and_cyclic_graphs(self):
        self.start();self.finish();self.refresh()
        for change in ('drop','dependency','rewrite'):
            bad=deepcopy(self.data)
            if change=='drop':bad['jobs'].pop()
            if change=='dependency':bad['jobs'][1]['dependencies']=[]
            if change=='rewrite':bad['jobs'][0]['exit_code']=7
            with self.subTest(change=change),self.assertRaises(ValueError):publish(bad)
        # A file changed outside the publisher still cannot shrink known selected work.
        path=run_home()/(self.data['id']+'.json');stored=json.loads(path.read_text());stored['jobs'].pop();path.write_text(json.dumps(stored))
        self.refresh();self.assertEqual(len(self.state()['matrix']['jobs']),2)
        bad=record();bad['jobs'][0]['dependencies']=['second']
        with self.assertRaises(ValueError):validate(bad)
        bad=record();bad['jobs'][1]['packages']=['first']
        with self.assertRaises(ValueError):validate(bad)

    def test_normal_store_path_unchanged_without_records(self):
        store=WatcherStore();self.addCleanup(store.close)
        with patch('uds_deploy.native.processes',return_value=[]):
            self.assertEqual(store.list(),[])
        self.assertFalse((self.root/'runtime').exists(),'Viewer startup must not create producer records')


if __name__=='__main__':unittest.main()
