#!/usr/bin/env python3
r"""Explicit real MI300X benchmark. NEVER falls back to simulation.

PowerShell: python .\scripts\benchmark_mi300x.py --jobs 4 --placement round_robin,adaptive,auto
Collects real agent-reported GPU telemetry and completed inference job metadata.
"""
import argparse
from datetime import datetime, timezone
import csv
import json
from pathlib import Path
import statistics
import time
from urllib.request import Request, urlopen


def api(base, path, method='GET', payload=None):
    req = Request(base.rstrip('/') + path, data=json.dumps(payload).encode() if payload is not None else None,
                  method=method, headers={'Content-Type': 'application/json'} if payload is not None else {})
    with urlopen(req, timeout=15) as response:
        return json.load(response)


def percentile(values, p):
    if not values:
        return None
    values = sorted(values)
    t = (len(values)-1)*p
    n = int(t)
    return round(values[n]*(1-(t-n)) + values[min(n+1,len(values)-1)]*(t-n),4)


def idle(base, timeout=600):
    started=time.monotonic()
    while time.monotonic()-started < timeout:
        s=api(base,'/api/cluster')['summary']
        if not (s['queued_jobs'] or s['running_jobs']):
            return
        time.sleep(2)
    raise TimeoutError('Cluster did not become idle; no benchmark was started')


def run(base, policy, model, count, output_tokens, prompt, timeout):
    idle(base)
    api(base,'/api/policy','PUT',{'policy':policy})
    started=time.monotonic()
    created=api(base,'/api/jobs/batch','POST',{'model':model, 'prompt':prompt, 'output_tokens':output_tokens,
                                            'priority':'normal', 'count':count})['jobs']
    ids={r['id'] for r in created}
    samples=[]
    while True:
        cluster=api(base,'/api/cluster')
        if cluster['mode']!='mi300x':
            raise RuntimeError('Real mode disappeared; STOPPING without claiming measurements')
        for n in cluster['nodes']:
            if n.get('source')=='amd_smi' and n.get('health')!='stale':
                samples.append({
                    'sampled_at':datetime.now(timezone.utc).isoformat(), 'policy':policy,
                    'gpu_endpoint':n['id'], 'gpu_ids':'+'.join(n.get('gpu_ids',[])),
                    'utilization_percent':n.get('utilization_percent'),
                    'memory_used_gb':n.get('memory_used_gb'),
                    'temperature_c':n.get('temperature_c'),
                    'power_watts':n.get('power_watts'), 'source':'amd_smi'})
        jobs=[x for x in api(base,'/api/jobs?limit=500')['jobs'] if x['id'] in ids]
        if len(jobs)==count and all(j['status'] in ('completed','failed') for j in jobs):
            break
        if time.monotonic()-started > timeout:
            raise TimeoutError(f'Benchmark timed out for {policy}; inspect jobs manually')
        time.sleep(2)
    if not samples:
        raise RuntimeError('No real AMD SMI telemetry observed; refusing to claim a verified GPU benchmark')
    elapsed=round(time.monotonic()-started,3)
    completed=[j for j in jobs if j['status']=='completed']
    durations=[j['duration_seconds'] for j in completed if j['duration_seconds'] is not None]
    tokens=sum((j['completion_tokens_actual'] or 0) for j in completed)
    summary={'policy':policy,'mode':'mi300x','source':'real_vllm',
        'model':model,'submitted':count,'completed':len(completed),'failed':count-len(completed),
        'makespan_seconds':elapsed,'completed_jobs_per_second':round(len(completed)/elapsed,4),
        'completion_tokens_per_second':round(tokens/elapsed,3),
        'p50_job_seconds':percentile(durations,.5),'p95_job_seconds':percentile(durations,.95),
        'observed_serving_endpoints':sorted({j['gpu_id'] for j in jobs if j['gpu_id']}),
        'gpu_samples':len(samples)}
    minimal=[{k:j.get(k) for k in ('id','model','execution_mode','priority','status','gpu_id',
        'created_at','started_at','completed_at','queue_wait_seconds','duration_seconds',
        'completion_tokens_actual','error_message')} | {'test_policy':policy} for j in jobs]
    return summary,minimal,samples


def main():
    ap=argparse.ArgumentParser(description='Explicit MI300X real inference benchmark')
    ap.add_argument('--api',default='http://localhost:8000')
    ap.add_argument('--jobs',type=int,default=4)
    ap.add_argument('--placement',default='round_robin,adaptive,auto')
    ap.add_argument('--prompt',default='In two sentences explain adaptive GPU inference scheduling.')
    ap.add_argument('--output-tokens',type=int,default=96)
    ap.add_argument('--timeout',type=int,default=600)
    ap.add_argument('--out',default='results/mi300x')
    args=ap.parse_args()
    if not 1 <= args.jobs <= 20 or not 1<=args.output_tokens<=8192:
        ap.error('--jobs must be 1..20; --output-tokens 1..8192')
    if api(args.api,'/api/cluster')['mode']!='mi300x':
        raise SystemExit('Refusing benchmark: runtime mode is not mi300x')
    models=api(args.api,'/api/models')['models']
    if not models or not models[0]['id']:
        raise SystemExit('Refusing benchmark: no ready MI300X vLLM models')
    model=models[0]['id']
    available={p['id'] for p in api(args.api,'/api/policies')['placement']}
    policies=[p.strip() for p in args.placement.split(',') if p.strip()]
    if not policies or any(p not in available for p in policies):
        ap.error('Unknown placement policy')
    summaries=[]; all_jobs=[]; all_samples=[]
    for policy in policies:
        print(f'Running REAL vLLM: {model}, {args.jobs} jobs, placement={policy}',flush=True)
        summary, jobs, samples=run(args.api,policy,model,args.jobs,args.output_tokens,args.prompt,args.timeout)
        print(json.dumps(summary,indent=2),flush=True)
        summaries.append(summary); all_jobs.extend(jobs); all_samples.extend(samples)
    output=Path(args.out); output.mkdir(parents=True,exist_ok=True)
    (output/'real-summary.json').write_text(json.dumps({'created_utc':datetime.now(timezone.utc).isoformat(),
            'evidence':'AMD SMI + real_vllm, never simulation', 'results':summaries},indent=2),encoding='utf-8')
    for filename,data in [('real-jobs.csv',all_jobs),('real-telemetry.csv',all_samples)]:
        if data:
            with (output/filename).open('w',newline='',encoding='utf-8') as f:
                writer=csv.DictWriter(f,fieldnames=list(data[0]));writer.writeheader();writer.writerows(data)
    print('Saved evidence to',output)


if __name__=='__main__':
    main()
