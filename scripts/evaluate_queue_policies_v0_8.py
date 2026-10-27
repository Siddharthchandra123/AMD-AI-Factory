#!/usr/bin/env python3
"""CPU-only, event-driven and reproducible queue-policy evaluation.

This imports the REAL backend/app/scheduler.py rank_queue() implementation; it
never opens HTTP connections or changes Docker, DB, Redis, or GPU settings.
Synthetic service times are assumptions and are NOT MI300X measurements.
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import heapq
import importlib.util
import json
import math
from pathlib import Path
import random
import statistics
import sys
from collections import defaultdict

ROOT = Path.cwd()
SCENARIOS = {
    'mixed_burst': 'Mixed job sizes and priorities; jobs arrive in dense bursts.',
    'tenant_contention': 'Unbalanced tenant arrivals; evaluate waiting-time disparities.',
    'deadline_pressure': 'Tight, heterogeneous deadlines; assess completion before deadline.',
    'steady_stream': 'Staggered arrivals at a rate exceeding two synthetic slots.',
}

@dataclass(frozen=True)
class Job:
    id: str
    arrival: float
    service: float
    estimate: float
    priority: str
    tenant: str
    deadline: float | None


def load_policy(project: Path):
    path = project / 'backend/app/scheduler.py'
    if not path.is_file():
        raise RuntimeError(f'Missing actual scheduler module: {path}. Run from your project root.')
    spec = importlib.util.spec_from_file_location('mission_scheduler_v08', str(path))
    if spec is None or spec.loader is None:
        raise RuntimeError('Failed to load project scheduler module.')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses expects an importable module
    spec.loader.exec_module(module)
    required = {'fcfs', 'shortest_job_first', 'priority_fifo', 'priority_aging',
                'earliest_deadline_first', 'fair_share'}
    found = set(module.QUEUE_POLICIES)
    if not required <= found:
        raise RuntimeError(f'Scheduler queue policies do not match expected API: {sorted(found)}')
    return module, path


def workload(scenario: str, count: int, seed: int) -> list[Job]:
    r = random.Random(f'v08:{scenario}:{seed}:{count}')
    jobs: list[Job] = []
    for i in range(count):
        # Rounded values reduce floating-point event-tie instability.
        if scenario == 'mixed_burst':
            arrival = round((i // 8) * 0.9 + r.random() * 0.16, 3)
            service = round(r.choice([0.2, 0.4, 0.9, 1.3, 2.1, 3.5]), 3)
            priority = r.choices(['high', 'normal', 'low'], weights=[2, 5, 3])[0]
            tenant = r.choice(['alpha', 'beta', 'gamma'])
            deadline = None
        elif scenario == 'tenant_contention':
            arrival = round((i // 9) * 0.45 + r.random() * 0.1, 3)
            service = round(r.choice([0.35, 0.7, 1.0, 2.5]), 3)
            priority = r.choices(['high', 'normal', 'low'], weights=[2, 6, 2])[0]
            tenant = r.choices(['alpha', 'beta', 'gamma'], weights=[8, 2, 1])[0]
            deadline = None
        elif scenario == 'deadline_pressure':
            arrival = round((i // 6) * 0.65 + r.random() * 0.12, 3)
            service = round(r.choice([0.35, 0.55, 1.1, 2.0, 2.7]), 3)
            priority = r.choice(['high', 'normal', 'low'])
            tenant = r.choice(['alpha', 'beta', 'gamma'])
            deadline = round(arrival + service + r.uniform(0.7, 5.0), 3)
        elif scenario == 'steady_stream':
            arrival = round(i * 0.22 + r.random() * 0.1, 3)
            service = round(r.choice([0.35, 0.55, 0.8, 1.7, 2.4]), 3)
            priority = r.choices(['high', 'normal', 'low'], weights=[1, 7, 2])[0]
            tenant = r.choice(['alpha', 'beta', 'gamma'])
            deadline = None
        else:
            raise ValueError(f'Unknown workload scenario: {scenario}')
        # Estimated service time is deliberately imperfect (but constant for all policies).
        estimate = round(max(0.1, service * r.uniform(0.7, 1.3)), 3)
        jobs.append(Job(f'job-{i:03d}', arrival, service, estimate, priority, tenant, deadline))
    jobs.sort(key=lambda j: (j.arrival, j.id))
    return jobs


def quantile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    a = sorted(values)
    index = (len(a) - 1) * q
    low = int(index)
    high = min(low + 1, len(a) - 1)
    return a[low] * (high - index) + a[high] * (index - low)


def simulate(jobs: list[Job], policy: str, slots: int, seed: int, scheduler):
    if slots < 1:
        raise ValueError('Slots must be >=1')
    now = 0.0
    waiting: list[Job] = []
    running: list[tuple[float, str, Job, float]] = []
    finish_rows: list[dict] = []
    rng = random.Random(f'policy:{policy}:seed:{seed}')
    idx = 0
    while idx < len(jobs) or waiting or running:
        # Jump to the next scheduled arrival or completion if there are no
        # dispatchable jobs (no arbitrary scheduler tick/polling is modeled).
        if (not waiting) or len(running) >= slots:
            next_arrival = jobs[idx].arrival if idx < len(jobs) else math.inf
            next_finish = running[0][0] if running else math.inf
            now = min(next_arrival, next_finish)
            if math.isinf(now):
                raise RuntimeError('Event stream stalled')
        while running and running[0][0] <= now + 1e-9:
            completed, _, job, start = heapq.heappop(running)
            finish_rows.append({
                'job_id': job.id, 'priority': job.priority, 'tenant': job.tenant,
                'arrival_s': job.arrival, 'started_s': round(start, 6),
                'completed_s': round(completed, 6), 'service_s': job.service,
                'estimate_s': job.estimate, 'deadline_s': job.deadline,
                'queue_wait_s': round(start - job.arrival, 6),
                'turnaround_s': round(completed - job.arrival, 6),
                'deadline_met': None if job.deadline is None else completed <= job.deadline + 1e-9,
            })
        while idx < len(jobs) and jobs[idx].arrival <= now + 1e-9:
            waiting.append(jobs[idx])
            idx += 1
        while waiting and len(running) < slots:
            active = defaultdict(int)
            for _, _, active_job, _ in running:
                active[active_job.tenant] += 1
            ranked = scheduler.rank_queue(
                [scheduler.QueueCandidate(
                    id=j.id, priority=j.priority, created_timestamp=j.arrival,
                    estimated_seconds=j.estimate, tenant=j.tenant,
                    deadline_timestamp=j.deadline
                ) for j in waiting], policy, now_timestamp=now,
                active_by_tenant=dict(active), rng=rng
            )
            selected = next(j for j in waiting if j.id == ranked[0].id)
            waiting.remove(selected)
            heapq.heappush(running, (now + selected.service, selected.id, selected, now))
        # Crucial: if there are remaining free slots, they are now filled; any
        # remaining jobs must wait for next completion, not next arrival.
    if len(finish_rows) != len(jobs):
        raise AssertionError('Every job must complete exactly once')
    return sorted(finish_rows, key=lambda row: row['job_id'])


def metrics(rows: list[dict], starvation_s: float) -> dict:
    waits = [j['queue_wait_s'] for j in rows]
    turns = [j['turnaround_s'] for j in rows]
    finishes = [j['completed_s'] for j in rows]
    arrivals = [j['arrival_s'] for j in rows]
    by_tenant: dict[str, list[float]] = defaultdict(list)
    for job in rows:
        by_tenant[job['tenant']].append(job['queue_wait_s'])
    means = {t: statistics.mean(ws) for t, ws in sorted(by_tenant.items())}
    deadlines = [j for j in rows if j['deadline_met'] is not None]
    highs = [j['queue_wait_s'] for j in rows if j['priority'] == 'high']
    makespan = max(finishes) - min(arrivals)
    return {
        'completed': len(rows),
        'mean_wait_s': round(statistics.mean(waits), 4),
        'p50_wait_s': round(quantile(waits, .5), 4),
        'p95_wait_s': round(quantile(waits, .95), 4),
        'max_wait_s': round(max(waits), 4),
        'p95_turnaround_s': round(quantile(turns, .95), 4),
        'mean_turnaround_s': round(statistics.mean(turns), 4),
        'high_priority_p95_wait_s': round(quantile(highs, .95), 4) if highs else None,
        'deadline_jobs': len(deadlines),
        'deadline_met_pct': round(100 * sum(j['deadline_met'] for j in deadlines) / len(deadlines), 3) if deadlines else None,
        'tenant_mean_wait_gap_s': round(max(means.values()) - min(means.values()), 4),
        'tenant_mean_wait_s': means,
        'starvation_proxy_count': sum(w >= starvation_s for w in waits),
        'throughput_jobs_per_s': round(len(rows) / makespan, 4) if makespan else 0,
        'makespan_s': round(makespan, 4),
    }


def write_csv(path: Path, rows: list[dict], fields: list[str]):
    with path.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)


def run(project: Path, trials: int, count: int, slots: int, seed: int, starvation_s: float, destination: Path) -> Path:
    scheduler, scheduler_file = load_policy(project)
    policies = list(scheduler.QUEUE_POLICIES)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    folder = destination / f'lab_{stamp}'
    folder.mkdir(parents=True, exist_ok=False)
    run_rows: list[dict] = []
    job_rows: list[dict] = []
    examples: dict[str, list[dict]] = {}
    traces: dict[str, str] = {}
    for scenario in SCENARIOS:
        for trial in range(trials):
            trace = workload(scenario, count, seed + trial)
            fingerprint = hashlib.sha256(json.dumps([asdict(j) for j in trace], sort_keys=True).encode()).hexdigest()
            traces[f'{scenario}/{trial+1}'] = fingerprint
            for policy in policies:
                executed = simulate(trace, policy, slots, seed + trial, scheduler)
                m = metrics(executed, starvation_s)
                run_rows.append({'scenario': scenario, 'trial': trial + 1, 'policy': policy,
                                 'trace_sha256': fingerprint, **m})
                for j in executed:
                    job_rows.append({'scenario': scenario, 'trial': trial + 1, 'policy': policy, **j})
                if trial == 0:
                    examples[f'{scenario}:{policy}'] = executed[:min(count, 64)]
    measure_keys = ['mean_wait_s','p50_wait_s','p95_wait_s','max_wait_s',
                    'p95_turnaround_s','mean_turnaround_s','high_priority_p95_wait_s',
                    'deadline_met_pct','tenant_mean_wait_gap_s','starvation_proxy_count',
                    'throughput_jobs_per_s','makespan_s']
    aggregates: list[dict] = []
    for scenario in SCENARIOS:
        for policy in policies:
            subset = [r for r in run_rows if r['scenario']==scenario and r['policy']==policy]
            row: dict = {'scenario':scenario, 'policy':policy,'trials':trials,'completed':count,
                         'deadline_jobs':subset[0]['deadline_jobs']}
            for metric in measure_keys:
                values = [r[metric] for r in subset if r[metric] is not None]
                row[metric] = round(statistics.mean(values), 4) if values else None
                if metric in ('p95_wait_s','p95_turnaround_s','deadline_met_pct'):
                    row[metric+'_sd'] = round(statistics.stdev(values),4) if len(values)>1 else 0.0 if values else None
            aggregates.append(row)
    manifest = {
        'tool': 'AMD AI Factory Scheduler Lab v0.8',
        'kind': 'CPU-only discrete-event simulation (NOT MI300X benchmark)',
        'timestamp_utc': stamp,
        'scheduler_sha256': hashlib.sha256(scheduler_file.read_bytes()).hexdigest(),
        'scheduler_module': 'backend/app/scheduler.py',
        'evaluation_policy_count': len(policies),
        'trials_per_scenario_policy': trials,
        'jobs_per_scenario_trial': count,
        'synthetic_slots': slots,
        'seed': seed,
        'starvation_proxy_threshold_s': starvation_s,
        'scenarios': SCENARIOS,
        'workload_sha256': traces,
        'notes': [
            'Identical arrival/service/deadline traces are reused across policies for each trial.',
            'rank_queue() is imported directly from the existing project scheduler module.',
            'The simulation assumes zero agent/network/database/scheduler tick overhead and known synthetic service-time estimates.',
            'Policies are non-preemptive; this is a queue-order comparison, not GPU placement or physical throughput.',
            'Deadline completion means simulated completion <= absolute deadline. No-deadline jobs are excluded.',
            'Fair-share behavior is based on the currently-active tenant counts, as implemented in rank_queue().',
            'Tenant wait-gap is max minus min of tenant mean queue waits; it is not a comprehensive fairness guarantee.',
            'Starvation proxy counts jobs waiting >= configured threshold; it does not prove starvation freedom.',
        ],
    }
    payload = {'manifest':manifest,'policies':scheduler.QUEUE_POLICIES,'aggregates':aggregates,
               'sample_jobs':examples}
    (folder / 'summary.json').write_text(json.dumps(payload, indent=2), encoding='utf-8')
    (folder / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    numeric_cols = ['scenario','trial','policy','trace_sha256', 'completed'] + measure_keys + ['deadline_jobs']
    write_csv(folder / 'runs.csv', run_rows, numeric_cols)
    write_csv(folder / 'summary.csv', aggregates, ['scenario','policy','trials','completed','deadline_jobs']+measure_keys)
    write_csv(folder / 'jobs.csv', job_rows,
              ['scenario','trial','policy','job_id','priority','tenant','arrival_s','started_s','completed_s',
               'service_s','estimate_s','deadline_s','queue_wait_s','turnaround_s','deadline_met'])
    destination.mkdir(parents=True, exist_ok=True)
    (destination / 'latest.json').write_text(json.dumps({'folder':folder.name}, indent=2),encoding='utf-8')
    print('Completed synthetic evaluation:', len(run_rows), 'runs;', len(job_rows), 'job records')
    print('Scheduling policies:', len(policies), ' | scenarios:', len(SCENARIOS), '| trials:', trials)
    print('Source: ACTUAL backend/app/scheduler.py | GPU used: NO')
    print('Saved:', folder)
    print('Example results for mixed_burst:')
    print(f'{"Policy":30s} {"P95 wait":>10s} {"P95 E2E":>10s} {"Jobs/s":>10s}')
    for m in sorted((a for a in aggregates if a['scenario']=='mixed_burst'), key=lambda a:a['p95_wait_s']):
        print(f'{m["policy"]:30s} {m["p95_wait_s"]:10.3f} {m["p95_turnaround_s"]:10.3f} {m["throughput_jobs_per_s"]:10.3f}')
    return folder


def main():
    parser = argparse.ArgumentParser(description='Run offline CPU-only Mission Control queue policy evaluation')
    parser.add_argument('--trials', type=int, default=3)
    parser.add_argument('--jobs', type=int, default=32)
    parser.add_argument('--slots', type=int, default=2)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--starvation-threshold', type=float, default=10.0)
    parser.add_argument('--output', default='results/scheduler-lab')
    a = parser.parse_args()
    if not (1 <= a.trials <= 50 and 8 <= a.jobs <= 200 and 1 <= a.slots <= 16 and a.starvation_threshold > 0):
        parser.error('Limits: trials 1..50; jobs 8..200; slots 1..16; starvation threshold >0')
    run(ROOT, a.trials, a.jobs, a.slots, a.seed, a.starvation_threshold, ROOT/a.output)


if __name__=='__main__':
    main()
