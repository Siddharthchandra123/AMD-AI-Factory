import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

BASE=Path(__file__).resolve().parents[1]/'scripts'
def load(name):
    spec=importlib.util.spec_from_file_location(name,BASE/(name+'.py'))
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    return m
b=load('benchmark_mi300x_v2')
a=load('audit_mi300x_baseline')

class BenchmarkTest(unittest.TestCase):
    def test_percentiles(self):
        self.assertEqual(b.pct([1,2,3,4], .5),2.5)
        self.assertEqual(b.pct([1,2,3,4], .95),3.85)
        self.assertIsNone(b.pct([],.95))
    def test_timing(self):
        self.assertEqual(b.seconds_between('2026-10-26T10:00:00+00:00','2026-10-26T10:00:01.5+00:00'),1.5)
    def test_fail_closed_in_sim_mode(self):
        with self.assertRaisesRegex(RuntimeError,'Real mode'):
            b.validate({'mode':'simulation'},{'mode':'simulation'})
    def test_fail_closed_zero_hbm(self):
        c={'mode':'mi300x','summary':{'running_jobs':0,'queued_jobs':0},'nodes':[{'id':'a','source':'amd_smi','ready':True,'health':'healthy','memory_total_gb':0,'memory_used_gb':0}]}
        r={'mode':'mi300x','connected_workers':1,'agent_errors':{}}
        with self.assertRaisesRegex(RuntimeError,'HBM'):
            b.validate(c,r)
    def test_true_hbm_eligible(self):
        c={'mode':'mi300x','summary':{'running_jobs':0,'queued_jobs':0},'nodes':[{'id':'a','source':'amd_smi','ready':True,'health':'healthy','memory_total_gb':191.7,'memory_used_gb':46.9}]}
        r={'mode':'mi300x','connected_workers':1,'agent_errors':{}}
        self.assertEqual(len(b.validate(c,r)),1)
    def test_complete_sampled_run(self):
        cluster={'mode':'mi300x','summary':{'running_jobs':0,'queued_jobs':0},'nodes':[
            {'id':'mi300x-host-1/vllm-mi300x-1','source':'amd_smi','ready':True,'health':'healthy',
             'memory_total_gb':191.7,'memory_used_gb':46.9,'active_jobs':0,'max_concurrent_jobs':2,
             'gpu_ids':['0'],'utilization_percent':20,'temperature_c':40,'power_watts':180,
             'last_seen_seconds':.2}]}
        runtime={'mode':'mi300x','connected_workers':1,'agent_errors':{}}
        completed_job={'id':'job1','model':'Qwen/Qwen3-0.6B','status':'completed','execution_mode':'mi300x',
            'gpu_id':'mi300x-host-1/vllm-mi300x-1',
            'created_at':'2026-10-26T10:00:00+00:00',
            'started_at':'2026-10-26T10:00:00.1+00:00',
            'completed_at':'2026-10-26T10:00:00.4+00:00',
            'queue_wait_seconds':.1,'duration_seconds':.2,'completion_tokens_actual':96}
        def fake_api(base,path,method='GET',body=None,timeout=15):
            if path=='/api/cluster':return cluster
            if path=='/api/runtime':return runtime
            if path=='/api/models':return {'models':[{'id':'Qwen/Qwen3-0.6B'}]}
            if path=='/api/jobs/batch':return {'jobs':[{'id':'job1'}]}
            if path.startswith('/api/jobs?'):return {'jobs':[completed_job]}
            raise AssertionError(path)
        with tempfile.TemporaryDirectory() as tmp, patch.object(b,'api',side_effect=fake_api):
            dest=Path(tmp)/'run'
            result=b.run('http://localhost:8000',1,None,'prompt',96,.5,60,dest)
            self.assertEqual(result['completed'],1)
            self.assertEqual(result['p50_end_to_end_seconds'],.4)
            self.assertEqual(result['p50_inference_seconds'],.2)
            self.assertTrue((dest/'jobs.csv').exists())
            self.assertTrue((dest/'summary.json').exists())
    def test_csv_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)
            (p/'real-jobs.csv').write_text('id,status,created_at,completed_at,queue_wait_seconds,duration_seconds,gpu_id\n1,completed,2026-10-26T10:00:00+00:00,2026-10-26T10:00:02+00:00,1.5,0.2,w0\n')
            (p/'real-telemetry.csv').write_text('memory_used_gb\n46.9\n')
            result=a.audit(p)
            self.assertEqual(result['database_job_lifecycle_span_s'],2)
            self.assertEqual(result['average_agent_inference_s'],0.2)
            self.assertEqual(result['telemetry_poll_rows'],1)

if __name__=='__main__':unittest.main()
