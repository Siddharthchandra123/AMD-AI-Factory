#!/usr/bin/env python3
"""Phase 9.1: diagnostic API-level SIMULATION reliability exercise for AMD AI Factory.

Creates one disposable synthetic worker, temporarily drains original synthetic
workers, verifies single-slot queue backpressure and drain/recovery, restores
original drain flags, and deletes the disposable worker. No GPU required.

Never represents simulation results as MI300X hardware evidence.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


class APIError(RuntimeError):
    pass


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def api(base: str, method: str, path: str, body=None, timeout=10):
    headers = {'Accept': 'application/json'}
    data = None
    if body is not None:
        headers['Content-Type'] = 'application/json'
        data = json.dumps(body).encode('utf-8')
    request = urllib.request.Request(base.rstrip('/') + path, method=method, data=data, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read().decode('utf-8')
            return json.loads(payload) if payload else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode('utf-8')[:500]
        raise APIError(f'{method} {path} HTTP {exc.code}: {detail}') from exc
    except urllib.error.URLError as exc:
        raise APIError(f'{method} {path}: {exc.reason}') from exc


def save_json(path: Path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    tmp.replace(path)


def retrieve_jobs(base: str, ids: list[str]):
    records = api(base, 'GET', '/api/jobs?limit=500')['jobs']
    by_id = {item['id']: item for item in records}
    return {id_: by_id[id_] for id_ in ids if id_ in by_id}


def wait_until(predicate, seconds: float, interval: float = .25):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    return None


def drain(base: str, node_id: str, value: bool):
    return api(base, 'PUT', '/api/nodes/' + node_id + '/drain', {'draining': value})


def safe_restore(base: str, state: dict, path: Path, *, cleanup: bool = True):
    """Best-effort cleanup; preserve state if any item could not be restored."""
    errors = []
    initial = state.get('original_nodes', {})
    if not initial:
        state['restored'] = True
        save_json(path, state)
        return errors
    try:
        current = {n['id']: n for n in api(base, 'GET', '/api/cluster')['nodes']}
        if api(base, 'GET', '/api/runtime')['mode'] != 'simulation':
            errors.append('Controller is not in simulation mode; refusing to restore in wrong mode')
            state['restore_errors'] = errors
            save_json(path, state)
            return errors
    except Exception as exc:
        state['restore_errors'] = [str(exc)]
        save_json(path, state)
        return [str(exc)]
    # Restore every original worker to its exact original drain state.
    for node_id, was_draining in initial.items():
        if node_id not in current:
            errors.append('Original node missing: ' + node_id)
            continue
        try:
            if bool(current[node_id].get('draining')) != bool(was_draining):
                drain(base, node_id, bool(was_draining))
        except Exception as exc:
            errors.append('Cannot restore ' + node_id + ': ' + str(exc))
    temporary = state.get('temporary_node')
    if temporary and cleanup:
        try:
            current = {n['id']: n for n in api(base, 'GET', '/api/cluster')['nodes']}
            if temporary in current:
                # Never delete a node that still has active jobs.
                if int(current[temporary].get('active_jobs', 0)):
                    errors.append('Temporary node has active jobs; retry --restore when idle: ' + temporary)
                else:
                    api(base, 'DELETE', '/api/simulator/nodes/' + temporary)
        except Exception as exc:
            errors.append('Cannot remove temporary node ' + str(temporary) + ': ' + str(exc))
    state['restore_errors'] = errors
    state['restored'] = not errors
    state['restore_at_utc'] = utc_now()
    save_json(path, state)
    return errors



def diagnostic_snapshot(base: str, job_ids: list[str], temporary_node: str | None) -> dict:
    """Best-effort, read-only diagnostic context for a failed drill.

    No credentials or secret configuration values are collected.
    """
    result: dict = {'observed_at_utc': utc_now(), 'submitted_job_ids': job_ids}
    for name, path in [('runtime', '/api/runtime'), ('cluster', '/api/cluster'),
                       ('policies', '/api/policies')]:
        try:
            payload = api(base, 'GET', path)
            if name == 'runtime':
                result['mode'] = payload.get('mode')
            elif name == 'cluster':
                result['summary'] = payload.get('summary')
                result['test_node'] = next((n for n in payload.get('nodes', [])
                                            if n.get('id') == temporary_node), None)
                result['other_node_count'] = sum(n.get('id') != temporary_node for n in payload.get('nodes', []))
            else:
                result['placement_policy'] = payload.get('active_placement')
                result['queue_policy'] = payload.get('active_queue')
        except Exception as exc:
            result[name + '_read_error'] = str(exc)
    try:
        jobs = retrieve_jobs(base, job_ids)
        result['found_jobs'] = len(jobs)
        result['jobs'] = [{key: job.get(key) for key in
                          ('id', 'status', 'gpu_id', 'created_at', 'started_at', 'completed_at',
                           'queue_wait_seconds', 'error', 'error_message')}
                          for job in jobs.values()]
    except Exception as exc:
        result['jobs_read_error'] = str(exc)
    return result


def run(args):
    base = args.api_url.rstrip('/')
    runtime = api(base, 'GET', '/api/runtime')
    if runtime.get('mode') != 'simulation':
        raise APIError('Mode is not simulation. Switch to simulation mode before running this CPU-only test.')
    cl = api(base, 'GET', '/api/cluster')
    summary = cl.get('summary', {})
    if int(summary.get('queued_jobs', -1)) != 0 or int(summary.get('running_jobs', -1)) != 0:
        raise APIError('Existing queued or running jobs detected. Wait until the cluster is idle.')
    existing = cl['nodes']
    if not existing or len(existing) >= 32:
        raise APIError('Need 1..31 existing simulator nodes to add one temporary worker.')
    original = {n['id']: bool(n.get('draining')) for n in existing}
    models = api(base, 'GET', '/api/models')['models']
    candidates = sorted((m for m in models if m.get('memory_gb') is not None and float(m['memory_gb']) <= 180),
                        key=lambda m: float(m['memory_gb']))
    if not candidates:
        raise APIError('No simulation model profile fits the temporary 192-GiB worker.')
    model = next((m['id'] for m in candidates if m['id'] == 'model-7b'), candidates[0]['id'])

    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '_' + uuid4().hex[:6]
    out = Path(args.output_dir) / ('reliability_' + stamp)
    state_path = out / 'restore_state.json'
    state = {
        'kind': 'synthetic_simulator_api_reliability_test', 'created_at_utc': utc_now(),
        'api_url': base, 'original_nodes': original, 'temporary_node': None, 'restored': False,
        'warning': 'SIMULATION evidence only. This does not establish real MI300X agent failure recovery.'
    }
    save_json(state_path, state)
    print('Recovery file:', state_path, flush=True)
    print('Run python scripts/test_reliability_v0_9_1.py --restore --state "' + str(state_path) +
          '" if this test is interrupted.', flush=True)
    report = {'kind': 'synthetic_simulator_api_reliability_test', 'start_utc': utc_now(),
              'status': 'in_progress', 'model': model, 'requested_jobs': args.jobs, 'output_tokens_per_job': args.output_tokens,
              'checks': {}, 'events': [], 'disclaimer': 'All jobs and nodes are synthetic. No MI300X GPU involved.'}
    job_ids = []
    phase = 'initialize'
    try:
        created = api(base, 'POST', '/api/simulator/nodes', {'memory_total_gb': 192, 'max_concurrent_jobs': 1})
        target = created['id']
        state['temporary_node'] = target
        save_json(state_path, state)
        report['temporary_node'] = target
        report['events'].append({'event': 'temporary_node_created', 'at_utc': utc_now(), 'node': target})
        # Isolation: only our new single-slot node is eligible for routing.
        for node_id, was_drained in original.items():
            if not was_drained:
                drain(base, node_id, True)
        assert all(n['draining'] for n in api(base, 'GET', '/api/cluster')['nodes'] if n['id'] != target)
        report['checks']['original_nodes_drained_for_isolation'] = True
        phase = 'submit'
        for idx in range(args.jobs):
            job = api(base, 'POST', '/api/jobs', {
                'model': model, 'prompt': 'Synthetic reliability drill: ' + str(idx),
                'prompt_tokens': 8, 'output_tokens': args.output_tokens, 'priority': 'normal',
                'tenant': 'reliability-' + stamp[-6:]
            })
            job_ids.append(job['id'])
        report['job_ids'] = job_ids
        report['events'].append({'event': 'jobs_submitted', 'count': len(job_ids), 'at_utc': utc_now()})
        phase = 'observe_initial_backpressure'
        peak_running = 0
        def one_running_and_queued():
            nonlocal peak_running
            cl = api(base, 'GET', '/api/cluster')
            n = next(n for n in cl['nodes'] if n['id'] == target)
            peak_running = max(peak_running, int(n['active_jobs']))
            statuses = retrieve_jobs(base, job_ids)
            return statuses if len(statuses) == len(job_ids) and \
                sum(j['status'] == 'running' for j in statuses.values()) == 1 and \
                sum(j['status'] == 'queued' for j in statuses.values()) >= 1 else None
        running = wait_until(one_running_and_queued, args.timeout)
        if not running:
            raise APIError('Did not observe one running and at least one queued job; inspect controller logs.')
        report['checks']['queue_backpressure_observed'] = True
        phase = 'drain_worker'
        drain(base, target, True)
        report['events'].append({'event': 'worker_drained_during_job', 'at_utc': utc_now()})
        def running_finishes_queue_stays():
            statuses = retrieve_jobs(base, job_ids)
            if len(statuses) != len(job_ids):
                return None
            if any(j['status'] == 'failed' for j in statuses.values()):
                raise APIError('A simulation job failed unexpectedly')
            return statuses if sum(j['status'] == 'running' for j in statuses.values()) == 0 and \
                sum(j['status'] == 'queued' for j in statuses.values()) >= 1 else None
        phase = 'observe_paused_queue'
        frozen = wait_until(running_finishes_queue_stays, args.timeout)
        if not frozen:
            raise APIError('Queue did not remain paused after draining the only eligible worker.')
        report['checks']['drain_stops_new_dispatch_without_canceling_active'] = True
        report['events'].append({'event': 'queue_paused_after_drain', 'at_utc': utc_now()})
        phase = 'resume_worker'
        drain(base, target, False)
        report['events'].append({'event': 'worker_resumed', 'at_utc': utc_now()})
        def all_done():
            nonlocal peak_running
            cl = api(base, 'GET', '/api/cluster')
            n = next(n for n in cl['nodes'] if n['id'] == target)
            peak_running = max(peak_running, int(n['active_jobs']))
            statuses = retrieve_jobs(base, job_ids)
            if len(statuses) != len(job_ids):
                return None
            if any(j['status'] == 'failed' for j in statuses.values()):
                raise APIError('A job failed after worker recovery')
            return statuses if all(j['status'] == 'completed' for j in statuses.values()) else None
        phase = 'observe_completion_after_resume'
        final_jobs = wait_until(all_done, args.timeout)
        if not final_jobs:
            raise APIError('Jobs did not all complete after worker resumed.')
        assignments = {j['gpu_id'] for j in final_jobs.values()}
        report['checks']['completed_after_resume'] = len(final_jobs) == args.jobs
        report['checks']['all_jobs_on_isolated_worker'] = assignments == {target}
        report['checks']['concurrency_limit_respected_at_poll_times'] = peak_running <= 1
        report['peak_observed_concurrency'] = peak_running
        report['jobs'] = list(final_jobs.values())
        report['status'] = 'passed' if all(report['checks'].values()) else 'failed'
        report['end_utc'] = utc_now()
        save_json(out / 'report.json', report)
        print(json.dumps({'status': report['status'], 'checks': report['checks'],
                          'peak_observed_concurrency': peak_running, 'output': str(out)}, indent=2))
        return 0 if report['status'] == 'passed' else 1
    except Exception as exc:
        report['status'] = 'failed'
        report['failed_phase'] = phase
        report['error'] = str(exc)
        report['diagnostic_snapshot'] = diagnostic_snapshot(base, job_ids, state.get('temporary_node'))
        report['end_utc'] = utc_now()
        save_json(out / 'report.json', report)
        print('Reliability test failed:', exc, file=sys.stderr)
        print('Phase:', phase, file=sys.stderr)
        print('Diagnostic snapshot:', json.dumps(report['diagnostic_snapshot'], indent=2), file=sys.stderr)
        return 1
    finally:
        errors = safe_restore(base, state, state_path)
        if errors:
            print('WARNING: cleanup incomplete. Run --restore with:', state_path, file=sys.stderr)
            for err in errors:
                print(' -', err, file=sys.stderr)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--api-url', default='http://localhost:8000', help='Local Mission Control backend')
    parser.add_argument('--output-dir', default='results/reliability', help='Separate synthetic evidence directory')
    parser.add_argument('--jobs', type=int, default=3, help='At least 2 simulated jobs (default 3)')
    parser.add_argument('--output-tokens', type=int, default=256, help='Synthetic output-token workload size, default 256; does not generate real tokens')
    parser.add_argument('--timeout', type=float, default=45, help='Seconds per phase')
    parser.add_argument('--run', action='store_true', help='Required to allow temporary simulator changes')
    parser.add_argument('--restore', action='store_true', help='Restore from a previous state file')
    parser.add_argument('--state', type=Path, help='Recovery state JSON for --restore')
    args = parser.parse_args(argv)
    if args.restore:
        if not args.state or not args.state.is_file():
            parser.error('--restore requires --state path/to/restore_state.json')
        state = json.loads(args.state.read_text(encoding='utf-8'))
        base = state.get('api_url')
        if args.api_url != 'http://localhost:8000' and args.api_url != base:
            parser.error('The --api-url does not match the original recorded backend.')
        errors = safe_restore(base, state, args.state)
        if errors:
            for err in errors:
                print('RESTORE ERROR:', err, file=sys.stderr)
            return 1
        print('Simulator original drain flags restored; temporary worker removed (if idle).')
        return 0
    if not args.run:
        parser.print_help()
        print('\nDry by default. Add --run to run the SIMULATION-only reliability drill.')
        return 0
    if not 2 <= args.jobs <= 8 or not 10 <= args.timeout <= 300 or not 64 <= args.output_tokens <= 1024:
        parser.error('--jobs must be 2..8, --timeout 10..300, and --output-tokens 64..1024')
    try:
        return run(args)
    except Exception as exc:
        print('ABORTED before simulator modification:', exc, file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
