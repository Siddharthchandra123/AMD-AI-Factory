#!/usr/bin/env python3
"""Read-only inspection of a prior Phase 10 restart drill and current local jobs."""
from __future__ import annotations
import argparse
import http.client
import json
from pathlib import Path
import urllib.error
import urllib.request


def get(url: str):
    with urllib.request.urlopen(url, timeout=8) as response:
        return json.load(response)


def main():
    p=argparse.ArgumentParser(description='Inspect Phase 10 restart evidence without changing running services')
    p.add_argument('--folder',required=True,help='Path to restart_<timestamp> evidence folder')
    p.add_argument('--url',default='http://127.0.0.1:8000')
    args=p.parse_args()
    if not args.url.startswith(('http://127.0.0.1:','http://localhost:')):
        p.error('Only local controller URLs are supported')
    path=Path(args.folder)/'report.json'
    if not path.exists():
        p.error('Report not found: '+str(path))
    report=json.loads(path.read_text(encoding='utf-8'))
    print('SAVED DRILL:',json.dumps({k:report.get(k) for k in ('status','error','failed_phase','checks','jobs')},indent=2))
    ids=set(report.get('job_ids',[]))
    for endpoint in ('/health','/api/cluster','/api/hardening/status'):
        try:
            value=get(args.url+endpoint)
            if endpoint=='/api/cluster':
                value={'mode':value.get('mode'),'summary':value.get('summary'),
                       'nodes':[{k:n.get(k) for k in ('id','health','draining','active_jobs')} for n in value.get('nodes',[])]}
            if endpoint=='/api/hardening/status':
                value={'recovery':value.get('recovery')}
            print(endpoint+': '+json.dumps(value,indent=2)[:5000])
        except (urllib.error.URLError,http.client.HTTPException,OSError,ValueError) as exc:
            print(endpoint+' unavailable: '+str(exc))
    if ids:
        try:
            jobs=get(args.url+'/api/jobs?limit=500').get('jobs',[])
            matched=[{'id':j.get('id'),'status':j.get('status'),'mode':j.get('execution_mode'),
                      'error':j.get('error_message') or j.get('error')} for j in jobs if j.get('id') in ids]
            print('PRIOR DRILL JOB STATES:',json.dumps({'matched':len(matched),'expected':len(ids),'jobs':matched},indent=2))
        except (urllib.error.URLError,http.client.HTTPException,OSError,ValueError) as exc:
            print('Cannot inspect prior drill jobs:',exc)

if __name__=='__main__':
    main()
