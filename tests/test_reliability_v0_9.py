import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

MODULE_PATH = Path(__file__).resolve().parents[1] / 'scripts' / 'test_reliability_v0_9.py'
spec = importlib.util.spec_from_file_location('reliability_v09', MODULE_PATH)
lab = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lab)


class TestReliabilityV09(unittest.TestCase):
    def test_wait_until(self):
        counter = {'n': 0}
        def condition():
            counter['n'] += 1
            return 'ok' if counter['n'] == 3 else None
        with patch.object(lab.time, 'sleep', lambda _: None):
            self.assertEqual(lab.wait_until(condition, 1), 'ok')

    def test_restore_original_flags_and_remove_temporary_node(self):
        nodes = {'gpu-a': {'id': 'gpu-a', 'draining': True, 'active_jobs': 0},
                 'gpu-b': {'id': 'gpu-b', 'draining': True, 'active_jobs': 0},
                 'temp': {'id': 'temp', 'draining': False, 'active_jobs': 0}}
        calls = []
        def mock_api(base, method, path, body=None, timeout=10):
            calls.append((method, path, body))
            if path == '/api/runtime':
                return {'mode': 'simulation'}
            if path == '/api/cluster':
                return {'nodes': list(nodes.values())}
            if method == 'PUT' and '/drain' in path:
                node_id = path.split('/')[3]
                nodes[node_id]['draining'] = body['draining']
                return {}
            if method == 'DELETE' and path.endswith('/temp'):
                nodes.pop('temp')
                return {}
            raise AssertionError((method, path))
        with tempfile.TemporaryDirectory() as d, patch.object(lab, 'api', side_effect=mock_api):
            path = Path(d) / 'recovery.json'
            state = {'original_nodes': {'gpu-a': False, 'gpu-b': True},
                     'temporary_node': 'temp', 'restored': False}
            self.assertEqual(lab.safe_restore('http://localhost:8000', state, path), [])
            self.assertFalse(nodes['gpu-a']['draining'])
            self.assertTrue(nodes['gpu-b']['draining'])
            self.assertNotIn('temp', nodes)
            self.assertTrue(json.loads(path.read_text())['restored'])

    def test_refuse_deletion_if_temporary_has_active_jobs(self):
        nodes = [{'id': 'gpu-a', 'draining': False, 'active_jobs': 0},
                 {'id': 'temp', 'draining': False, 'active_jobs': 1}]
        def mock_api(base, method, path, body=None, timeout=10):
            if path == '/api/runtime':
                return {'mode': 'simulation'}
            if path == '/api/cluster':
                return {'nodes': nodes}
            raise AssertionError('Should not touch an active temporary node')
        with tempfile.TemporaryDirectory() as d, patch.object(lab, 'api', side_effect=mock_api):
            path = Path(d) / 'recovery.json'
            state = {'original_nodes': {'gpu-a': False}, 'temporary_node': 'temp'}
            errors = lab.safe_restore('http://localhost:8000', state, path)
            self.assertEqual(len(errors), 1)
            self.assertIn('active jobs', errors[0])
            self.assertFalse(json.loads(path.read_text())['restored'])

    def test_safe_abort_on_wrong_mode(self):
        with tempfile.TemporaryDirectory() as d, patch.object(lab, 'api', side_effect=lambda base,method,path,body=None,timeout=10: {'mode': 'mi300x'} if path == '/api/runtime' else {'nodes': []}):
            path = Path(d) / 'recovery.json'
            state = {'original_nodes': {'gpu-a': False}, 'temporary_node': 'temp'}
            errors = lab.safe_restore('http://localhost:8000', state, path)
            self.assertEqual(len(errors), 1)
            self.assertIn('not in simulation mode', errors[0])

    def test_cannot_activate_without_run(self):
        self.assertEqual(lab.main([]), 0)
        with patch.object(lab, 'run') as run:
            self.assertEqual(lab.main(['--jobs', '3']), 0)
            run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
