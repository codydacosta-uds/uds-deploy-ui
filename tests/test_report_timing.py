"""SDK clocks are presentation evidence, never lifecycle or capture changes."""
import datetime
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from uds_deploy.native import record_report,report


class ReportTimingTests(unittest.TestCase):
    def test_sdk_json_and_legacy_local_clocks(self):
        stamp=datetime.datetime(2026,1,2,12,tzinfo=datetime.timezone.utc).timestamp()
        for clock in ('2026-01-02T12:00:00Z','2026-01-02T14:00:00+02:00'):
            item=report(json.dumps({'msg':'running command','cmd':'example','time':clock}))
            self.assertEqual(item['source_timestamp'],stamp)
            self.assertEqual(item['status'],'reported')
        item=report('2026-01-02 12:00:00 INF running health checks chart=app')
        self.assertEqual(item['source_timestamp'],datetime.datetime(2026,1,2,12).timestamp())
        self.assertEqual(item['resource'],'app')

    def test_missing_or_invalid_clocks_are_not_fabricated(self):
        for clock in (None,1,True,'yesterday','2026-99-02T12:00:00Z','2026-01-02T99:00:00Z'):
            item=report(json.dumps({'msg':'running command','cmd':'example','time':clock}))
            self.assertNotIn('source_timestamp',item)
        self.assertNotIn('source_timestamp',report('ERROR: failed to deploy bundle: example'))

    def action(self,target,message,clock,log_id):
        item=report(json.dumps({'msg':message,'cmd':'example','time':clock}))
        item['log_id']=log_id
        return record_report(target,item,{})

    def target(self):
        return {'reports':[],'packages':[],'mode':'observed','source':{'kind':'stock-process','output_complete':True}}

    def test_late_ingestion_keeps_sdk_interval_without_changing_order_or_status(self):
        target=self.target()
        with patch('uds_deploy.native.time.time',side_effect=[100000,100000.001]):
            first=self.action(target,'running command','2026-01-02T12:00:00Z',1)
            identity=first['id']
            last=self.action(target,'action succeeded','2026-01-02T12:03:00Z',2)
        self.assertEqual(len(target['reports']),1)
        self.assertEqual(last['id'],identity)
        self.assertEqual(last['first_log_id'],1)
        self.assertEqual(last['log_id'],2)
        self.assertAlmostEqual(last['timestamp'],100000.001)
        self.assertEqual(last['source_timestamp']-last['first_source_timestamp'],180)
        self.assertEqual(last['message'],'action succeeded')
        self.assertEqual(last['status'],'reported')
        self.assertNotIn('inferred_complete',last)
        self.assertNotIn('timing_uncertain',last)

    def test_a_timestamp_missing_at_either_boundary_stays_unavailable(self):
        target=self.target()
        self.action(target,'running command','2026-01-02T12:00:00Z',1)
        last=self.action(target,'action succeeded',None,2)
        self.assertNotIn('source_timestamp',last,'Do not reuse a start clock as the success clock')
        self.assertIn('first_source_timestamp',last)
        target=self.target()
        self.action(target,'running command',None,1)
        last=self.action(target,'action succeeded','2026-01-02T12:03:00Z',2)
        self.assertTrue(last['timing_uncertain'],'A success clock does not recover the missing start')

    def test_repeated_start_flags_only_timing_not_native_result(self):
        target=self.target()
        self.action(target,'running command','2026-01-02T12:00:00Z',1)
        retry=self.action(target,'running command','2026-01-02T12:02:00Z',2)
        self.assertTrue(retry['timing_uncertain'])
        last=self.action(target,'action failed','2026-01-02T12:03:00Z',3)
        self.assertTrue(last['timing_uncertain'])
        self.assertEqual(last['message'],'action failed')
        self.assertEqual(last['status'],'reported')


if __name__=='__main__':unittest.main()
