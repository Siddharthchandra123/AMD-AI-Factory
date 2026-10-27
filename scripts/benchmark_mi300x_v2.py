#!/usr/bin/env python3
"""MI300X experimental benchmark for AMD AI Factory Mission Control v0.3.

Uses existing Windows FastAPI control plane. Requires no local GPU or extra packages.
Does not restart services, reset queues, or silently fall back to simulation.
Preserves all prior evidence by generating unique output folders.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import statistics
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def api(base, path, method='GET', body=None, timeout=15):
    payload = json.dumps(body).encode('utf-8') if body is not None else None
    req = Request(base.rstrip('/') + path, data=payload, method=method,
                  headers={'Content-Type': 'application/json'} if payload else {})
    try:
        with urlopen(req, timeout=timeout) as result:
            return json.load(result)
    except (HTTPError, URLError) as error:
        raise RuntimeError(f'{method} {path} failed: {error}') from error


def pct(values, fraction):
    values = sorted(float(v) for v in values if isinstance(v, (int, float)))
    if not values:
        return None
    k = (len(values) - 1) * fraction
    i = int(k)
    return round(values[i] * (1 - (k-i)) + values[min(i+1, len(values)-1)] * (k-i), 4)


def seconds_between(start, end):
    if not start or not end:
        return None
    try:
        d0 = datetime.fromisoformat(start.replace('Z', '+00:00'))
        d1 = datetime.fromisoformat(end.replace('Z', '+00:00'))
        return round((d1 - d0).total_seconds(), 4)
    except (TypeError, ValueError):
        return None


def validate(cluster, runtime):
    if cluster.get('mode') != 'mi300x' or runtime.get('mode') != 'mi300x':
        raise RuntimeError('Real mode not active; refusing to submit simulation jobs')
    if int(runtime.get('connected_workers') or 0) < 1:
        raise RuntimeError('No connected MI300X inference workers')
    if runtime.get('agent_errors'):
        raise RuntimeError(f'Agent errors: {runtime["agent_errors"]}')
    if cluster.get('summary', {}).get('queued_jobs') or cluster.get('summary', {}).get('running_jobs'):
        raise RuntimeError('Cluster is busy; run benchmarks only with an idle queue')
    eligible = [n for n in cluster.get('nodes', [])
                if n.get('source') == 'amd_smi'
                and n.get('ready') is True
                and n.get('health') in ('healthy', 'high_load')
                and isinstance(n.get('memory_total_gb'), (int, float))
                and n['memory_total_gb'] > 0
                and isinstance(n.get('memory_used_gb'), (int, float))
                and n['memory_used_gb'] >= 0]
    if not eligible:
        raise RuntimeError('No healthy AMD SMI worker with valid HBM telemetry. Fix telemetry before benchmarking.')
    if all(n.get('health') == 'high_load' for n in eligible):
        raise RuntimeError('All workers already high-load; refusing to add benchmark requests')
    return eligible


def save_csv(path, records):
    if not records:
        return
    cols = list(dict.fromkeys(k for row in records for k in row))
    with path.open('w', newline='', encoding='utf-8') as out:
        writer = csv.DictWriter(out, fieldnames=cols)
        writer.writeheader()
        writer.writerows(records)


def run(base, count, model, prompt, output_tokens, poll, timeout, out):
    # Preflight each step; do not mix in other user jobs.
    eligible = validate(api(base, '/api/cluster'), api(base, '/api/runtime'))
    available_models = [m.get('id') for m in api(base, '/api/models').get('models', []) if m.get('id')]
    if not available_models:
        raise RuntimeError('No ready vLLM model discovered by Mission Control')
    if model is None:
        model = available_models[0]
    if model not in available_models:
        raise RuntimeError(f'Model {model!r} is not served by any ready MI300X worker')
    start = time.monotonic()
    created = api(base, '/api/jobs/batch', method='POST', body={
        'model':model, 'prompt':prompt, 'priority':'normal',
        'prompt_tokens':512, 'output_tokens':output_tokens, 'count':count
    })['jobs']
    submitted_elapsed = round(time.monotonic() - start, 4)
    if len(created) != count:
        raise RuntimeError(f'Only {len(created)} of {count} jobs returned by submission API')
    wanted = {j['id'] for j in created}
    last_jobs = []
    samples = []
    while True:
        state = api(base, '/api/cluster')
        if state.get('mode') != 'mi300x':
            raise RuntimeError('Mission Control left mi300x mode during the benchmark')
        now = datetime.now(timezone.utc).isoformat()
        for node in state.get('nodes', []):
            if node.get('source') == 'amd_smi':
                samples.append({
                    'polled_utc': now,
                    'endpoint':node.get('id'),
                    'health':node.get('health'),
                    'ready':node.get('ready'),
                    'last_seen_seconds':node.get('last_seen_seconds'),
                    'gpu_util_percent':node.get('utilization_percent'),
                    'hbm_total_gib':node.get('memory_total_gb'),
                    'hbm_used_gib':node.get('memory_used_gb'),
                    'temperature_c':node.get('temperature_c'),
                    'power_w':node.get('power_watts'),
                    'endpoint_running_jobs':node.get('active_jobs'),
                    'cluster_running_jobs':state.get('summary',{}).get('running_jobs'),
                    'cluster_queued_jobs':state.get('summary',{}).get('queued_jobs'),
                })
        all_jobs = api(base, '/api/jobs?limit=500')['jobs']
        last_jobs = [j for j in all_jobs if j.get('id') in wanted]
        if len(last_jobs) == count and all(j['status'] in ('completed', 'failed') for j in last_jobs):
            break
        if time.monotonic() - start > timeout:
            raise TimeoutError(f'Jobs not finished within {timeout}s; inspect controller before any retry')
        time.sleep(poll)
    observed_elapsed = round(time.monotonic() - start, 4)
    records = []
    for job in last_jobs:
        records.append({
            'id':job['id'], 'model':job.get('model'), 'status':job.get('status'),
            'execution_mode':job.get('execution_mode'), 'gpu_id':job.get('gpu_id'),
            'created_at':job.get('created_at'), 'started_at':job.get('started_at'),
            'completed_at':job.get('completed_at'),
            'queue_wait_seconds':job.get('queue_wait_seconds'),
            'execution_seconds':job.get('duration_seconds'),
            'end_to_end_seconds':seconds_between(job.get('created_at'), job.get('completed_at')),
            'completion_tokens':job.get('completion_tokens_actual'),
            'error':job.get('error_message'),
        })
    completed = [r for r in records if r['status']=='completed' and r['execution_mode']=='mi300x']
    completed_tokens = sum(r['completion_tokens'] or 0 for r in completed)
    created_ts = [datetime.fromisoformat(r['created_at'].replace('Z','+00:00')) for r in records if r['created_at']]
    completed_ts = [datetime.fromisoformat(r['completed_at'].replace('Z','+00:00')) for r in records if r['completed_at']]
    lifecycle_span = round((max(completed_ts) - min(created_ts)).total_seconds(), 4) if created_ts and len(completed_ts)==count else None
    job_durations = [r['execution_seconds'] for r in completed]
    waits = [r['queue_wait_seconds'] for r in completed]
    e2e = [r['end_to_end_seconds'] for r in completed]
    mem = [r['hbm_used_gib'] for r in samples if isinstance(r['hbm_used_gib'], (int,float)) and r['health']!='stale']
    summary = {
        'source':'real_vllm', 'mode':'mi300x', 'model':model,
        'requested_jobs':count, 'completed':len(completed), 'failed':count-len(completed),
        'unique_serving_endpoints':sorted({r['gpu_id'] for r in records if r['gpu_id']}),
        'configured_max_concurrent_jobs':{n['id']:n.get('max_concurrent_jobs') for n in eligible},
        'submission_seconds':submitted_elapsed,
        'controller_lifecycle_span_seconds':lifecycle_span,
        'client_observed_wall_seconds':observed_elapsed,
        'p50_queue_wait_seconds':pct(waits, .5), 'p95_queue_wait_seconds':pct(waits, .95),
        'p50_inference_seconds':pct(job_durations,.5), 'p95_inference_seconds':pct(job_durations,.95),
        'p50_end_to_end_seconds':pct(e2e,.5), 'p95_end_to_end_seconds':pct(e2e,.95),
        'completion_tokens':completed_tokens,
        'controller_lifecycle_tokens_per_second':round(completed_tokens/lifecycle_span,3) if lifecycle_span and lifecycle_span>0 else None,
        'observed_client_tokens_per_second':round(completed_tokens/observed_elapsed,3) if observed_elapsed>0 else None,
        'gpu_poll_rows':len(samples), 'peak_polled_hbm_gib':max(mem) if mem else None,
        'warning':'GPU poll rows are snapshots, NOT necessarily unique hardware samples. '
                  'Individual inference seconds measure agent-to-vLLM response only; '
                  'client wall time includes dispatch, network, queue and polling. '
                  'One serving endpoint cannot validate placement policies.'
    }
    out.mkdir(parents=True, exist_ok=False)
    save_csv(out/'jobs.csv', records)
    save_csv(out/'telemetry_polls.csv', samples)
    (out/'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    return summary


def main(argv=None):
    ap=argparse.ArgumentParser(description='Preserved MI300X real-inference benchmark with guarded telemetry')
    ap.add_argument('--api',default='http://localhost:8000')
    ap.add_argument('--jobs',type=int,default=8)
    ap.add_argument('--model', default=None, help='Use a model advertised by /api/models (first model by default)')
    ap.add_argument('--output-tokens',type=int,default=96)
    ap.add_argument('--prompt',default='Describe a practical GPU scheduling strategy in two sentences.')
    ap.add_argument('--poll',type=float,default=0.5)
    ap.add_argument('--timeout',type=int,default=240)
    ap.add_argument('--out',default=None,help='Unique directory (generated if omitted)')
    args=ap.parse_args(argv)
    if not 1<=args.jobs<=20 or not 1<=args.output_tokens<=512 or not .25<=args.poll<=5:
        ap.error('jobs=1..20, output-tokens=1..512, poll=0.25..5')
    prefix = Path('results/mi300x/v2_' + datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f'))
    out = Path(args.out) if args.out else prefix
    if out.exists():
        ap.error(f'Output directory already exists: {out} (refusing to overwrite evidence)')
    try:
        result=run(args.api, args.jobs, args.model, args.prompt, args.output_tokens, args.poll, args.timeout, out)
    except Exception as exc:
        # We intentionally do not auto-retry real inference requests: outcomes may be uncertain.
        print(f'Benchmark STOPPED: {exc}',file=sys.stderr)
        return 1
    print(json.dumps(result,indent=2))
    print(f'Saved NEW evidence to: {out}')
    return 0 if result['failed']==0 else 2


if __name__=='__main__':
    raise SystemExit(main())
