import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

MODULE_PATH = Path(__file__).resolve().parents[1] / 'scripts' / 'test_reliability_v0_9_1.py'
spec = importlib.util.spec_from_file_location('reliability_v091', MODULE_PATH)
lab = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lab)


class TestReliabilityV091(unittest.TestCase):
    def test_snapshot_captures_worker_and_queue_without_secrets(self):
        def fake_api(base, method, path, body=None, timeout=10):
            if path == '/api/runtime':
                return {'mode': 'simulation', 'agent_token': 'secret'}
            if path == '/api/cluster':
                return {'summary': {'queued_jobs': 2, 'running_jobs': 1}, 'nodes': [
                    {'id': 'tmp', 'active_jobs': 1, 'draining': False},
                    {'id': 'old', 'active_jobs': 0, 'draining': True}]}
            if path == '/api/policies':
                return {'active_placement': 'round_robin', 'active_queue': 'fcfs'}
            if path == '/api/jobs?limit=500':
                return {'jobs': [{'id': 'job1', 'status': 'running', 'gpu_id': 'tmp',
                                   'prompt': 'private prompt', 'error_message': None},
                                  {'id': 'job2', 'status': 'queued', 'gpu_id': None,
                                   'prompt': 'private prompt', 'error_message': None}]}
            raise AssertionError(path)
        with patch.object(lab, 'api', side_effect=fake_api):
            snapshot = lab.diagnostic_snapshot('http://localhost:8000', ['job1','job2'], 'tmp')
        self.assertEqual(snapshot['found_jobs'], 2)
        self.assertEqual(snapshot['test_node']['active_jobs'], 1)
        self.assertEqual(snapshot['summary']['queued_jobs'], 2)
        self.assertEqual(snapshot['placement_policy'], 'round_robin')
        self.assertNotIn('secret', json.dumps(snapshot))
        self.assertNotIn('private prompt', json.dumps(snapshot))

    def test_longer_workload_and_drain_restore_flow(self):
        nodes = {'original': {'id': 'original', 'draining': False, 'active_jobs': 0}}
        jobs = {}
        calls = []
        target = 'temporary'
        def fake_api(base, method, path, body=None, timeout=10):
            calls.append((method, path, body))
            if path == '/api/runtime':
                return {'mode': 'simulation'}
            if path == '/api/cluster':
                return {'nodes': list(nodes.values()), 'summary': {
                    'queued_jobs': sum(j['status']=='queued' for j in jobs.values()),
                    'running_jobs': sum(j['status']=='running' for j in jobs.values())}}
            if path == '/api/models':
                return {'models': [{'id':'model-7b', 'memory_gb': 16}]}
            if path == '/api/jobs?limit=500':
                return {'jobs': list(jobs.values())}
            if path == '/api/policies':
                return {'active_placement':'round_robin', 'active_queue':'fcfs'}
            if method == 'POST' and path == '/api/simulator/nodes':
                nodes[target] = {'id':target,'draining':False,'active_jobs':0}
                return nodes[target]
            if method == 'PUT' and path.startswith('/api/nodes/') and path.endswith('/drain'):
                node_id = path.split('/')[3]
                nodes[node_id]['draining'] = body['draining']
                return {}
            if method == 'POST' and path == '/api/jobs':
                self.assertEqual(body['output_tokens'], 256)
                key = 'job' + str(len(jobs))
                jobs[key] = {'id':key,'status':'queued','gpu_id':None}
                return jobs[key]
            if method == 'DELETE' and path == '/api/simulator/nodes/' + target:
                nodes.pop(target)
                return {'removed':target}
            raise AssertionError((method,path))
        phases = {'n':0}
        def fake_wait(predicate, seconds, interval=.25):
            phases['n'] += 1
            if phases['n'] == 1:
                jobs['job0'].update(status='running',gpu_id=target)
                nodes[target]['active_jobs']=1
                return predicate()
            if phases['n'] == 2:
                jobs['job0']['status']='completed'
                nodes[target]['active_jobs']=0
                return predicate()
            if phases['n'] == 3:
                for j in jobs.values():
                    j.update(status='completed',gpu_id=target)
                nodes[target]['active_jobs']=0
                return predicate()
            raise AssertionError(phases)
        with tempfile.TemporaryDirectory() as d, patch.object(lab,'api',side_effect=fake_api), \
             patch.object(lab,'wait_until',side_effect=fake_wait):
            args = SimpleNamespace(api_url='http://localhost:8000', output_dir=d, jobs=3,
                                   timeout=90, output_tokens=256)
            self.assertEqual(lab.run(args),0)
            self.assertEqual(len(jobs),3)
            self.assertNotIn(target,nodes)
            self.assertFalse(nodes['original']['draining'])
            output=list(Path(d).glob('reliability_*/report.json'))
            self.assertEqual(len(output),1)
            self.assertEqual(json.loads(output[0].read_text())['status'],'passed')

    def test_restore_idempotent(self):
        node = {'id': 'old', 'draining': False, 'active_jobs': 0}
        def fake_api(base, method, path, body=None, timeout=10):
            if path == '/api/runtime':
                return {'mode':'simulation'}
            if path == '/api/cluster':
                return {'nodes':[node]}
            raise AssertionError(path)
        with tempfile.TemporaryDirectory() as d, patch.object(lab,'api',side_effect=fake_api):
            path=Path(d)/'restore.json'
            state={'original_nodes':{'old':False},'temporary_node':'temporary'}
            self.assertEqual(lab.safe_restore('http://localhost:8000',state,path),[])
            self.assertEqual(lab.safe_restore('http://localhost:8000',state,path),[])
            self.assertTrue(json.loads(path.read_text())['restored'])


if __name__ == '__main__':
    unittest.main()
