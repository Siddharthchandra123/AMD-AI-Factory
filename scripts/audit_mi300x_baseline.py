#!/usr/bin/env python3
"""Offline audit of the previous MI300X benchmark CSVs; no GPU requests."""
import argparse
import csv
from datetime import datetime
import json
from pathlib import Path
import statistics


def read_csv(path):
    if not path.exists():
        raise FileNotFoundError(f'Missing evidence file: {path}')
    with path.open(newline='', encoding='utf-8-sig') as stream:
        return list(csv.DictReader(stream))


def float_or_none(value):
    try:
        return float(value) if value not in ('', None) else None
    except (TypeError, ValueError):
        return None


def elapsed(a,b):
    try:
        return (datetime.fromisoformat(b.replace('Z','+00:00'))-
                datetime.fromisoformat(a.replace('Z','+00:00'))).total_seconds()
    except (ValueError, AttributeError, TypeError):
        return None


def audit(folder):
    jobs=read_csv(folder/'real-jobs.csv')
    samples=read_csv(folder/'real-telemetry.csv')
    total=len(jobs)
    completed=[j for j in jobs if j.get('status')=='completed']
    queue=[float_or_none(j.get('queue_wait_seconds')) for j in completed]
    durations=[float_or_none(j.get('duration_seconds')) for j in completed]
    records=[]
    for j in jobs:
        records.append({
            'id':j.get('id'), 'status':j.get('status'),
            'queue_wait_s':float_or_none(j.get('queue_wait_seconds')),
            'inference_s':float_or_none(j.get('duration_seconds')),
            'job_lifecycle_s':elapsed(j.get('created_at'),j.get('completed_at')),
            'gpu_id':j.get('gpu_id')
        })
    def clean(seq):
        return [x for x in seq if x is not None]
    starts = [j['created_at'] for j in jobs if j.get('created_at')]
    ends = [j['completed_at'] for j in jobs if j.get('completed_at')]
    batch_span = elapsed(min(starts),max(ends)) if starts and len(ends)==len(jobs) else None
    raw_mem = [float_or_none(s.get('memory_used_gb')) for s in samples]
    return {
        'jobs_in_csv':total, 'completed':len(completed),
        'average_queue_wait_s':round(statistics.mean(clean(queue)),4) if clean(queue) else None,
        'average_agent_inference_s':round(statistics.mean(clean(durations)),4) if clean(durations) else None,
        'database_job_lifecycle_span_s':round(batch_span,4) if batch_span is not None else None,
        'telemetry_poll_rows':len(samples),
        'max_reported_hbm_gib':max(clean(raw_mem)) if clean(raw_mem) else None,
        'note':'Previous benchmark wall time contains submission + polling; '
               'job durations are not end-to-end. GPU poll rows are not guaranteed unique samples.',
        'jobs':records,
    }


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--folder',default='results/mi300x')
    args=p.parse_args()
    print(json.dumps(audit(Path(args.folder)),indent=2))

if __name__=='__main__':
    main()
