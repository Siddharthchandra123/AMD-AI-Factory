#!/usr/bin/env python3
"""Read-only timing diagnosis for AMD AI Factory Mission Control v0.3/v0.5.

Sends a small number of REAL MI300X inference requests by three paths:
  Windows -> SSH -> vLLM
  Windows -> SSH -> agent -> vLLM
  Windows -> Mission Control -> SSH -> agent -> vLLM

Does not update models, driver settings, scheduler policies or live code.
The agent token is prompted without echo if not present in the environment.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import getpass
import json
import os
from pathlib import Path
import statistics
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def request_json(url: str, *, method='GET', body=None, headers=None, timeout=30):
    data = json.dumps(body).encode('utf-8') if body is not None else None
    h = dict(headers or {})
    if data is not None:
        h['Content-Type'] = 'application/json'
    request = Request(url, data=data, headers=h, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except HTTPError as error:
        # Avoid printing authorization headers, request body, or agent token.
        raise RuntimeError(f'{url.split("/v1/")[0]} returned HTTP {error.code}') from None
    except URLError as error:
        raise RuntimeError(f'Cannot connect to {url.split("/v1/")[0]}: {error.reason}') from None


def iso_seconds(left, right):
    if not left or not right:
        return None
    start = datetime.fromisoformat(left.replace('Z', '+00:00'))
    end = datetime.fromisoformat(right.replace('Z', '+00:00'))
    return round((end-start).total_seconds(), 4)


def percentiles(values, fraction):
    values = sorted(float(x) for x in values if x is not None)
    if not values:
        return None
    loc = fraction * (len(values) - 1)
    i = int(loc)
    return round(values[i] + (values[min(i+1, len(values)-1)] - values[i]) * (loc - i), 4)


def timed_request(url: str, **kwargs):
    start = time.perf_counter()
    result = request_json(url, **kwargs)
    return result, round(time.perf_counter() - start, 4)


def wait_for_job(api: str, job_id: str, seconds: int):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        jobs = request_json(api + '/api/jobs?limit=100').get('jobs', [])
        job = next((x for x in jobs if x.get('id') == job_id), None)
        if job and job.get('status') in ('completed', 'failed'):
            return job
        time.sleep(0.15)
    raise RuntimeError('Controller job not completed within timeout; check Mission Control before retrying')


def save_csv(path, rows):
    with path.open('w', newline='', encoding='utf-8') as fh:
        writer = csv.DictWriter(fh, fieldnames=['trial','path','client_seconds','vllm_reported_seconds',
            'agent_overhead_seconds','controller_queue_seconds','controller_poststart_extra_seconds',
            'controller_lifecycle_seconds','completion_tokens','status'])
        writer.writeheader()
        writer.writerows(rows)


def diagnose(args, token: str):
    api = args.api.rstrip('/')
    agent = args.agent.rstrip('/')
    vllm = args.vllm.rstrip('/')
    runtime = request_json(api + '/api/runtime')
    cluster = request_json(api + '/api/cluster')
    if runtime.get('mode') != 'mi300x' or cluster.get('mode') != 'mi300x':
        raise RuntimeError('Mission Control is not in real MI300X mode')
    summary = cluster.get('summary', {})
    if summary.get('queued_jobs', 0) or summary.get('running_jobs', 0):
        raise RuntimeError('Queue is not idle; stopping to avoid mixing timing experiments with other work')
    nodes = [n for n in cluster.get('nodes', []) if n.get('ready') and
             n.get('source') == 'amd_smi' and n.get('health') in ('healthy', 'high_load') and
             n.get('memory_total_gb', 0) > 0]
    if len(nodes) != 1:
        raise RuntimeError(f'Expected one healthy MI300X serving endpoint, found {len(nodes)}')
    node_id = nodes[0]['id']
    worker_id = node_id.split('/', 1)[1]
    models = set(nodes[0].get('models', []))
    if args.model not in models:
        raise RuntimeError(f'Model {args.model} is not advertised by ready worker')

    # Also verify agent token before charging GPU time.
    state = request_json(agent + '/v1/state', headers={'X-Mission-Token': token})
    if state.get('source') != 'amd_smi':
        raise RuntimeError('Agent is not providing genuine AMD SMI data')
    requests = []
    print(f'Real MI300X: {node_id}; model={args.model}; tokens={args.output_tokens}; trials={args.trials}')
    print('Only one request runs at a time; no changes to the server, scheduler or GPU settings.\n')
    for trial in range(1, args.trials + 1):
        prompt = f'Explain GPU scheduling in one sentence. Test sample {trial}.'
        # Equal prompt and output-token ceiling on every route.
        direct, elapsed = timed_request(vllm + '/v1/completions', method='POST', timeout=args.timeout,
            body={'model': args.model, 'prompt':prompt, 'temperature':0, 'max_tokens':args.output_tokens})
        if not direct.get('choices'):
            raise RuntimeError('Direct vLLM returned no choices')
        d = {'trial':trial,'path':'direct_vllm','client_seconds':elapsed,'vllm_reported_seconds':None,
             'agent_overhead_seconds':None,'controller_queue_seconds':None,
             'controller_poststart_extra_seconds':None,'controller_lifecycle_seconds':None,
             'completion_tokens':(direct.get('usage') or {}).get('completion_tokens'),'status':'completed'}
        requests.append(d)
        print(f'Trial {trial} direct vLLM: {elapsed:.4f}s')
        via, elapsed = timed_request(agent + '/v1/infer', method='POST', timeout=args.timeout,
            headers={'X-Mission-Token':token},
            body={'worker_id':worker_id,'model':args.model,'prompt':prompt,'max_tokens':args.output_tokens})
        if via.get('source') != 'real_vllm':
            raise RuntimeError('Agent inference is not confirmed as real_vllm')
        infer_seconds = via.get('duration_seconds')
        extra = round(elapsed - infer_seconds, 4) if isinstance(infer_seconds, (float,int)) else None
        requests.append({'trial':trial,'path':'agent_vllm','client_seconds':elapsed,
           'vllm_reported_seconds':infer_seconds,'agent_overhead_seconds':extra,
           'controller_queue_seconds':None,'controller_poststart_extra_seconds':None,
           'controller_lifecycle_seconds':None,'completion_tokens':via.get('completion_tokens'),'status':'completed'})
        print(f'Trial {trial} via agent:   {elapsed:.4f}s (agent-recorded vLLM: {infer_seconds}s; extra: {extra}s)')
        begin = time.perf_counter()
        submitted = request_json(api + '/api/jobs', method='POST', timeout=args.timeout,
            body={'model':args.model,'prompt':prompt,'output_tokens':args.output_tokens,'priority':'normal'})
        job = wait_for_job(api, submitted['id'], args.timeout)
        observed = round(time.perf_counter() - begin, 4)
        if job.get('status') != 'completed' or job.get('execution_mode') != 'mi300x':
            raise RuntimeError(f'Controller job {job["id"]} did not complete in real mode; status={job.get("status")}; error={job.get("error_message")}')
        stage = iso_seconds(job.get('started_at'), job.get('completed_at'))
        infer = job.get('duration_seconds')
        extra = round(stage - infer, 4) if stage is not None and isinstance(infer, (int,float)) else None
        lifecycle = iso_seconds(job.get('created_at'), job.get('completed_at'))
        requests.append({'trial':trial,'path':'mission_control','client_seconds':observed,
            'vllm_reported_seconds':infer,'agent_overhead_seconds':None,
            'controller_queue_seconds':job.get('queue_wait_seconds'),
            'controller_poststart_extra_seconds':extra,'controller_lifecycle_seconds':lifecycle,
            'completion_tokens':job.get('completion_tokens_actual'),'status':job.get('status')})
        print(f'Trial {trial} controller:  {observed:.4f}s (queue={job.get("queue_wait_seconds")}s; poststart-extra={extra}s)')
    by_path = {}
    for label in ('direct_vllm','agent_vllm','mission_control'):
        subset = [r for r in requests if r['path']==label]
        by_path[label] = {
            'n':len(subset),
            'median_client_seconds':percentiles([r['client_seconds'] for r in subset],0.5),
            'p95_client_seconds':percentiles([r['client_seconds'] for r in subset],0.95),
            'median_agent_overhead_seconds':percentiles([r['agent_overhead_seconds'] for r in subset],0.5),
            'median_controller_queue_seconds':percentiles([r['controller_queue_seconds'] for r in subset],0.5),
            'median_controller_poststart_extra_seconds':percentiles([r['controller_poststart_extra_seconds'] for r in subset],0.5),
        }
    output = {'timestamp_utc':datetime.now(timezone.utc).isoformat(),
              'hardware_source':'amd_smi','model':args.model,'serving_endpoint':node_id,
              'trials_per_path':args.trials,'results':by_path,
              'caution':'The three paths are run sequentially over Windows SSH forwarding. Numbers include network and client overhead; not standalone MI300X GPU throughput. Warm caches, token variability, and shared-cloud noise may affect comparisons.'}
    out = Path(args.out) if args.out else Path('results/mi300x/latency_diag_v06_' + datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f'))
    if out.exists():
        raise RuntimeError('Output exists; refusing to overwrite prior evidence')
    out.mkdir(parents=True)
    save_csv(out/'requests.csv',requests)
    (out/'summary.json').write_text(json.dumps(output, indent=2), encoding='utf-8')
    print('\n' + json.dumps(output,indent=2))
    print(f'\nSaved diagnostics to {out}')
    return output


def main(argv=None):
    ap = argparse.ArgumentParser(description='Compare real MI300X request paths without changing running services')
    ap.add_argument('--trials',type=int,default=3)
    ap.add_argument('--output-tokens',type=int,default=96)
    ap.add_argument('--model',default='Qwen/Qwen3-0.6B')
    ap.add_argument('--api',default='http://127.0.0.1:8000')
    ap.add_argument('--agent',default='http://127.0.0.1:9877')
    ap.add_argument('--vllm',default='http://127.0.0.1:8002')
    ap.add_argument('--timeout',type=int,default=90)
    ap.add_argument('--out',default=None)
    args=ap.parse_args(argv)
    if args.trials < 1 or args.trials > 10 or args.output_tokens < 1 or args.output_tokens > 256:
        ap.error('trials must be 1..10; output-tokens 1..256')
    token = os.environ.get('MISSION_AGENT_TOKEN') or getpass.getpass('MI300X agent token (hidden): ')
    if not token:
        ap.error('Agent token is required')
    try:
        diagnose(args,token)
    except Exception as exc:
        print(f'DIAGNOSTIC STOPPED: {exc}',file=sys.stderr)
        return 1
    return 0


if __name__=='__main__':
    raise SystemExit(main())
