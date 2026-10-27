from pathlib import Path
import ast
import importlib.util
import tempfile
import unittest

PATCH = Path(__file__).resolve().parents[1] / 'scripts' / 'patch_scheduler_v0_5.py'
spec = importlib.util.spec_from_file_location('patcher', PATCH)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
BASE = Path(__file__).resolve().parents[1] / 'backend' / 'app' / 'main.py'
if not BASE.exists():  # Development kit verification when not extracted into a project
    BASE = Path('/mnt/data/amd-ai-factory-v0.3-work/backend/app/main.py')

class PatchTests(unittest.TestCase):
    def setUp(self):
        self.original = BASE.read_text(encoding='utf-8')

    def test_initial_dry_run_parse(self):
        result = mod.patch_text(self.original)
        tree = ast.parse(result)
        funcs = {n.name: n for n in tree.body if isinstance(n, ast.AsyncFunctionDef)}
        self.assertIn('discovery_loop', funcs)
        self.assertIn('worker_loop', funcs)
        self.assertIn('lifespan', funcs)

    def test_split_refresh_and_dispatch(self):
        result = mod.patch_text(self.original)
        funcs = {n.name: ast.get_source_segment(result, n) for n in ast.parse(result).body if isinstance(n, ast.AsyncFunctionDef)}
        self.assertIn('await live.refresh()', funcs['discovery_loop'])
        self.assertNotIn('await live.refresh()', funcs['worker_loop'])
        self.assertIn('real_tick()', funcs['worker_loop'])
        self.assertIn('0.25 if pending_count() else 0.5', funcs['worker_loop'])
        self.assertIn('telemetry_task.cancel()', funcs['lifespan'])

    def test_idempotent(self):
        once = mod.patch_text(self.original)
        self.assertEqual(once, mod.patch_text(once))

    def test_rejects_other_code(self):
        with self.assertRaises(ValueError):
            mod.patch_text('async def worker_loop(): pass')

    def test_changes_only_target_blocks(self):
        result = mod.patch_text(self.original)
        self.assertIn('async def perform_real(', result)
        self.assertIn('def real_tick():', result)
        self.assertIn("@app.post('/api/jobs/batch'", result)

if __name__ == '__main__':
    unittest.main()
