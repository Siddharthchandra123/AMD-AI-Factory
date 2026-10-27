"""Offline tests. Run at repo root: python -m unittest discover -s tests -p test_scheduler_lab.py -v"""
from __future__ import annotations
import importlib.util
from pathlib import Path
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT=Path(__file__).resolve().parents[1]
BASE=Path(__file__).resolve().parents[2]/'.phase8src/amd-ai-factory'

def load_script(name):
    spec=importlib.util.spec_from_file_location(name, str(ROOT/'scripts'/f'{name}.py'))
    mod=importlib.util.module_from_spec(spec)
    sys.modules[name]=mod
    spec.loader.exec_module(mod)
    return mod

EVAL=load_script('evaluate_queue_policies_v0_8')

class PolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if BASE.exists():
            cls.scheduler,_=EVAL.load_policy(BASE)
        else:
            # On a user's machine, run tests from the project containing scheduler.py.
            cls.scheduler,_=EVAL.load_policy(Path.cwd())

    def test_matched_workloads_are_reproducible(self):
        a=EVAL.workload('mixed_burst',24,42)
        b=EVAL.workload('mixed_burst',24,42)
        c=EVAL.workload('mixed_burst',24,43)
        self.assertEqual(a,b)
        self.assertNotEqual(a,c)

    def test_single_queue_order_uses_real_fcfs(self):
        jobs=[EVAL.Job('c',0,2,2,'normal','t',None),
              EVAL.Job('a',0,1,1,'normal','t',None),
              EVAL.Job('b',0,1,1,'normal','t',None)]
        rows=EVAL.simulate(sorted(jobs,key=lambda j:(j.arrival,j.id)),'fcfs',1,1,self.scheduler)
        self.assertEqual([r['job_id'] for r in sorted(rows,key=lambda r:r['started_s'])],['a','b','c'])
        self.assertEqual([r['queue_wait_s'] for r in sorted(rows,key=lambda r:r['started_s'])],[0,1,2])

    def test_service_slots_not_exceeded(self):
        jobs=EVAL.workload('mixed_burst',32,42)
        for policy in self.scheduler.QUEUE_POLICIES:
            rows=EVAL.simulate(jobs,policy,2,42,self.scheduler)
            self.assertEqual(len(rows),32)
            self.assertEqual(len({r['job_id'] for r in rows}),32)
            # Active slots at interval midpoints.
            pts=sorted({r['started_s'] for r in rows}|{r['completed_s'] for r in rows})
            for a,b in zip(pts,pts[1:]):
                mid=(a+b)/2
                active=sum(r['started_s']<=mid<r['completed_s'] for r in rows)
                self.assertLessEqual(active,2)
            self.assertTrue(all(r['queue_wait_s']>=0 for r in rows))

    def test_policy_influences_job_order(self):
        jobs=EVAL.workload('mixed_burst',32,42)
        fcfs=EVAL.simulate(jobs,'fcfs',2,42,self.scheduler)
        sjf=EVAL.simulate(jobs,'shortest_job_first',2,42,self.scheduler)
        seq=lambda rows:[r['job_id'] for r in sorted(rows,key=lambda r:(r['started_s'],r['job_id']))]
        self.assertNotEqual(seq(fcfs),seq(sjf))

    def test_deadlines_and_nulls(self):
        deadline_jobs=EVAL.workload('deadline_pressure',24,42)
        rows=EVAL.simulate(deadline_jobs,'earliest_deadline_first',2,42,self.scheduler)
        m=EVAL.metrics(rows,10)
        self.assertEqual(m['deadline_jobs'],24)
        self.assertGreaterEqual(m['deadline_met_pct'],0)
        self.assertLessEqual(m['deadline_met_pct'],100)
        other=EVAL.simulate(EVAL.workload('mixed_burst',24,42),'fcfs',2,42,self.scheduler)
        self.assertIsNone(EVAL.metrics(other,10)['deadline_met_pct'])

    def test_full_artifacts_and_replay(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)
            out=EVAL.run(BASE if BASE.exists() else Path.cwd(),2,16,2,47,10,p)
            self.assertTrue((out/'jobs.csv').exists())
            self.assertTrue((out/'runs.csv').exists())
            data=json.loads((out/'summary.json').read_text())
            self.assertEqual(len(data['aggregates']),len(EVAL.SCENARIOS)*len(self.scheduler.QUEUE_POLICIES))
            self.assertEqual(data['manifest']['trials_per_scenario_policy'],2)
            self.assertEqual(data['manifest']['scheduler_module'],'backend/app/scheduler.py')
            first=json.loads((p/'latest.json').read_text())
            self.assertEqual(first['folder'],out.name)
            # Every policy within a trial has identical workload fingerprint.
            import csv
            with (out/'runs.csv').open(newline="",encoding="utf-8") as f:
                runrows=list(csv.DictReader(f))
            fingerprints={(r['scenario'],r['trial']):set() for r in runrows}
            for r in runrows:
                fingerprints[r['scenario'],r['trial']].add(r['trace_sha256'])
            self.assertTrue(all(len(hashes)==1 for hashes in fingerprints.values()))

class InstallerTests(unittest.TestCase):
    def fixture(self,tmp:Path,with_v07:bool):
        src=BASE if BASE.exists() else Path.cwd()
        for rel in ('docker-compose.yml','frontend/src/app/page.tsx'):
            dest=tmp/rel
            dest.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(src/rel,dest)
        # Test-fixture normalization: start before Scheduler Lab install.
        # The developer's source project may *already* have this feature installed.
        # Strip only the installed markers from copied temporary fixtures,
        # so the installer is actually tested in an uninstalled state.
        compose_file = tmp / 'docker-compose.yml'
        compose_content = compose_file.read_text(encoding='utf-8')
        compose_content = ''.join(
            line for line in compose_content.splitlines(keepends=True)
            if 'SCHEDULER_LAB_RESULTS_DIR' not in line
            and './results/scheduler-lab:/app/scheduler-lab-evidence:ro' not in line
        )
        compose_file.write_text(compose_content, encoding='utf-8')
        home_file = tmp / 'frontend/src/app/page.tsx'
        home_content = home_file.read_text(encoding='utf-8')
        home_content = ''.join(
            line for line in home_content.splitlines(keepends=True)
            if 'href="/scheduler-lab"' not in line
        )
        home_file.write_text(home_content, encoding='utf-8')
        for rel in ('frontend/src/app/scheduler-lab/page.tsx','frontend/src/app/scheduler-lab/scheduler-lab.css',
                    'frontend/src/app/api/scheduler-lab/route.ts','scripts/evaluate_queue_policies_v0_8.py',
                    'scripts/enable_scheduler_lab_v0_8.py'):
            dest=tmp/rel;dest.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(ROOT/rel,dest)
        latest=tmp/'results/scheduler-lab/latest.json';latest.parent.mkdir(parents=True,exist_ok=True)
        latest.write_text('{"folder":"lab_20261027T000000000000Z"}')
        if with_v07:
            page=tmp/'frontend/src/app/page.tsx'
            original=page.read_text()
            original=original.replace('        <a href="http://localhost:3001"',
                '        <a href="/benchmarks"><BarChart3 size={18}/> Benchmark Analytics <ArrowRight size={13}/></a>\n        <a href="http://localhost:3001"',1)
            page.write_text(original)
            compose=tmp/'docker-compose.yml'
            content=compose.read_text()
            content=content.replace('      NEXT_PUBLIC_API_URL: http://localhost:8000\n',
                    '      NEXT_PUBLIC_API_URL: http://localhost:8000\n      BENCHMARK_RESULTS_DIR: /app/benchmark-evidence\n',1)
            content=content.replace('    networks: [internal]\n\n  prometheus:',
                    '    volumes:\n      - ./results/mi300x:/app/benchmark-evidence:ro\n    networks: [internal]\n\n  prometheus:',1)
            compose.write_text(content)

    def test_installs_on_base_and_phase7(self):
        for phase7 in (False,True):
            with self.subTest(phase7=phase7),tempfile.TemporaryDirectory() as folder:
                tmp=Path(folder)
                self.fixture(tmp,phase7)
                cmd=[sys.executable,str(tmp/'scripts/enable_scheduler_lab_v0_8.py')]
                env=lambda args: subprocess.run(cmd+args,cwd=tmp,capture_output=True,text=True)
                dry=env([])
                self.assertEqual(dry.returncode,0,dry.stderr+dry.stdout)
                applied=env(['--apply'])
                self.assertEqual(applied.returncode,0,applied.stderr+applied.stdout)
                again=env(['--apply'])
                self.assertEqual(again.returncode,0,again.stdout)
                self.assertIn('Already installed',again.stdout)
                compose=(tmp/'docker-compose.yml').read_text()
                home=(tmp/'frontend/src/app/page.tsx').read_text()
                self.assertEqual(compose.count('SCHEDULER_LAB_RESULTS_DIR'),1)
                self.assertEqual(compose.count('./results/scheduler-lab'),1)
                self.assertEqual(home.count('href="/scheduler-lab"'),1)
                if phase7:
                    self.assertIn('BENCHMARK_RESULTS_DIR',compose)
                    self.assertIn('href="/benchmarks"',home)
                backups=list((tmp/'backups').glob('scheduler_lab_v0_8_*'))
                self.assertEqual(len(backups),1)

if __name__=='__main__':unittest.main()
