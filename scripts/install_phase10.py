#!/usr/bin/env python3
"""Unified, conservative Phase 10 installer for AMD AI Factory Mission Control.

Run from the root of the Windows local repository. Default is dry run;
--apply makes backups and edits only known anchors. --restore can reverse it.
No Docker data volumes, MI300X files, or benchmark evidence are modified.
"""
from __future__ import annotations
import argparse
import ast
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys

ROOT = Path.cwd()
SRC_MAIN = ROOT / 'backend/app/main.py'
SRC_COMPOSE = ROOT / 'docker-compose.yml'
SRC_HOME = ROOT / 'frontend/src/app/page.tsx'
SRC_SCHED = ROOT / 'frontend/src/app/scheduler-lab/page.tsx'
BACKEND_MODULE = ROOT / 'backend/app/hardening.py'
SOURCES = [
    BACKEND_MODULE,
    ROOT / 'frontend/src/app/hardening/page.tsx',
    ROOT / 'frontend/src/app/hardening/hardening.css',
    ROOT / 'frontend/src/app/api/hardening/route.ts',
]

OLD_START = '''    # Simulation can be retried, but an interrupted real vLLM request must NEVER
    # be silently resubmitted (could generate duplicate processing/billing).
    with SessionLocal.begin() as db:
        records = db.scalars(select(InferenceJob).where(InferenceJob.status.in_(['queued', 'running']))).all()
        for job in records:
            if job.execution_mode == 'mi300x' and job.status == 'running':
                job.status = 'failed'
                job.error_message = 'Controller restarted while real inference was in flight; outcome unknown, not retried.'
                job.completed_at = now_utc()
                cache.lrem(queue_names[job.priority], 0, job.id)
                continue
            job.status = 'queued'
            job.gpu_id = None
            job.started_at = None
            cache.lrem(queue_names[job.priority], 0, job.id)
            cache.lpush(queue_names[job.priority], job.id)
'''
NEW_START = '''    # PHASE10: reconcile DB and Redis from durable jobs before dispatch begins.
    summary = reconcile_pending_jobs(SessionLocal, InferenceJob, cache, queue_names, now_utc)
    print('Phase 10 recovery:', json.dumps(summary), flush=True)
'''
IMPORT = '''from .hardening import (reconcile_pending_jobs, read_recovery_status,
                        worker_health_summary, authorized_write_request)
'''
APPEND = '''

# PHASE10: optional local-only write protection and defense-in-depth headers.
# This does NOT protect read APIs or the SSE feed; keep controller on loopback.
@app.middleware('http')
async def phase10_write_guard(request, call_next):
    from fastapi.responses import JSONResponse
    configured = os.getenv('MISSION_CONTROL_WRITE_TOKEN', '')
    supplied = request.headers.get('X-Mission-Api-Key', '')
    if not authorized_write_request(request.method, request.url.path, supplied, configured):
        return JSONResponse({'detail': 'Missing or invalid Mission Control write token'}, status_code=401)
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
    if request.url.path.startswith('/api/jobs') or request.url.path.startswith('/api/hardening'):
        response.headers['Cache-Control'] = 'no-store'
    return response


@app.get('/api/hardening/status')
def phase10_hardening_status():
    return {
        'phase': '10.1-10.4',
        'recovery': read_recovery_status(cache),
        'workers': worker_health_summary(get_mode(), get_snapshots()),
        'security': {
            'write_token_enabled': bool(os.getenv('MISSION_CONTROL_WRITE_TOKEN', '')),
            'note': 'Optional token protects mutations only, not read APIs. Bind locally or use an authenticated reverse proxy.',
        },
    }
'''


def patch_main(value: str) -> str:
    if '# PHASE10: reconcile DB and Redis' not in value:
        if value.count(OLD_START) != 1:
            raise RuntimeError('Unsupported lifespan recovery block; no changes made. Your main.py may differ from v0.3/v0.5.')
        value = value.replace(OLD_START, NEW_START, 1)
    if IMPORT not in value:
        if value.count('from .simulator import RuntimeJob, VirtualCluster, VirtualGPU, now_utc\n') != 1:
            raise RuntimeError('Cannot locate main.py import anchor')
        value = value.replace('from .simulator import RuntimeJob, VirtualCluster, VirtualGPU, now_utc\n',
                              'from .simulator import RuntimeJob, VirtualCluster, VirtualGPU, now_utc\n' + IMPORT, 1)
    if '# PHASE10: optional local-only write protection' not in value:
        value += APPEND
    ast.parse(value)
    return value


def patch_compose(value: str) -> str:
    # Restrict edits to the two known services, preserving already added Phase 7/8 mounts.
    start = value.find('  backend:\n')
    middle = value.find('  frontend:\n')
    end = value.find('  prometheus:\n')
    if min(start,middle,end) < 0 or not start < middle < end:
        raise RuntimeError('Unexpected compose layout; no changes made')
    b = value[start:middle]
    f = value[middle:end]
    if '      MISSION_AGENT_TOKEN:' not in b:
        raise RuntimeError('Backend environment anchor not found')
    write_token = '      MISSION_CONTROL_WRITE_TOKEN: ${MISSION_CONTROL_WRITE_TOKEN:-}\n'
    if write_token not in b:
        anchor = next((s for s in b.splitlines(keepends=True) if '      MISSION_AGENT_TOKEN:' in s), None)
        b = b.replace(anchor, anchor + write_token, 1)
    env = '      RELIABILITY_RESULTS_DIR: /app/reliability-evidence\n'
    mount = '      - ./results/reliability:/app/reliability-evidence:ro\n'
    if '      NEXT_PUBLIC_API_URL:' not in f:
        raise RuntimeError('Frontend environment anchor not found')
    if env not in f:
        anchor = next((s for s in f.splitlines(keepends=True) if '      NEXT_PUBLIC_API_URL:' in s), None)
        f = f.replace(anchor, anchor + env, 1)
    if mount not in f:
        if '    volumes:\n' in f:
            f = f.replace('    volumes:\n', '    volumes:\n' + mount, 1)
        elif '    networks:' in f:
            f = f.replace('    networks:', '    volumes:\n' + mount + '    networks:', 1)
        else:
            raise RuntimeError('Frontend volume/network anchor not found')
    return value[:start] + b + f + value[end:]


def patch_home(value: str) -> str:
    if 'href="/hardening"' in value:
        return value
    anchor = '        <a href="http://localhost:3001"'
    if value.count(anchor) != 1:
        raise RuntimeError('Sidebar anchor not found; use /hardening directly after install')
    return value.replace(anchor,
        '        <a href="/hardening"><ShieldAlert size={18}/> Reliability &amp; Hardening <ArrowRight size={13}/></a>\n' + anchor, 1)


def plan(root: Path):
    for file in (SRC_MAIN,SRC_COMPOSE,SRC_HOME,*SOURCES):
        if not file.is_file():
            raise RuntimeError(f'Missing {file.relative_to(root)}; extract ZIP into the AMD AI Factory project root first')
    updates = {
        SRC_MAIN: patch_main(SRC_MAIN.read_text(encoding='utf-8')),
        SRC_COMPOSE: patch_compose(SRC_COMPOSE.read_text(encoding='utf-8')),
        SRC_HOME: patch_home(SRC_HOME.read_text(encoding='utf-8')),
    }
    # Built-in fix for earlier v0.8 select TypeScript error; avoid a new build regression.
    if SRC_SCHED.is_file():
        old = SRC_SCHED.read_text(encoding='utf-8')
        updates[SRC_SCHED] = old.replace('onChange={e=>setMetric(e.target.value)}',
                                         'onChange={e=>setMetric(e.target.value as Metric)}')
    return {p:contents for p,contents in updates.items() if p.read_text(encoding='utf-8') != contents}


def restore(path: Path):
    manifest = json.loads((path/'manifest.json').read_text(encoding='utf-8'))
    for rec in manifest['files']:
        dest = ROOT / rec['path']
        backup = path / 'originals' / rec['path']
        if not backup.is_file():
            raise RuntimeError('Missing rollback original: ' + str(backup))
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(backup, dest)
        print('Restored', rec['path'])
    print('Source files restored. New add-on files were kept; they are inert without the integration.')


def main(argv=None):
    parser = argparse.ArgumentParser(description='Install all Phase 10 safeguards and dashboard in one operation')
    parser.add_argument('--apply', action='store_true', help='Apply compatible changes, saving original files')
    parser.add_argument('--restore', type=Path, help='Restore modified files from backup directory')
    args = parser.parse_args(argv)
    if args.restore:
        restore(args.restore)
        return 0
    changes = plan(ROOT)
    print('Phase 10 compatibility check PASS')
    print('Pending files:', *[str(p.relative_to(ROOT)) for p in changes], sep='\n - ')
    if not changes:
        print('Already installed. No file changes needed.')
        return 0
    if not args.apply:
        print('Dry run only. Apply with: python .\\scripts\\install_phase10.py --apply')
        return 0
    # Refuse to patch a busy live controller; incomplete in-flight requests may
    # otherwise be interrupted when the user rebuilds containers.
    import urllib.request
    try:
        with urllib.request.urlopen('http://127.0.0.1:8000/api/cluster', timeout=2) as reply:
            current = json.load(reply)
        summary = current.get('summary') or {}
        if int(summary.get('queued_jobs', 0)) or int(summary.get('running_jobs', 0)):
            raise RuntimeError('Controller has queued/running jobs. Wait until idle before installing/rebuilding.')
        if current.get('mode') != 'simulation':
            raise RuntimeError('Controller must be in simulation mode for this GPU-free Phase 10 install.')
    except (OSError, TimeoutError):
        print('Controller not reachable at localhost:8000; static source install permitted. Confirm no active jobs before rebuilding.')
    backup = ROOT/'backups'/('phase10_' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    backups = backup/'originals'
    backups.mkdir(parents=True,exist_ok=False)
    for path in changes:
        dest = backups/path.relative_to(ROOT)
        dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(path,dest)
    (backup/'manifest.json').write_text(json.dumps({'files':[{'path':str(p.relative_to(ROOT)).replace('\\','/')} for p in changes]},indent=2))
    try:
        for path, contents in changes.items():
            path.write_text(contents,encoding='utf-8')
            if path.suffix == '.py': ast.parse(path.read_text(encoding='utf-8'))
    except Exception:
        restore(backup)
        raise
    (ROOT/'results/reliability').mkdir(parents=True,exist_ok=True)
    print('INSTALLED Phase 10. Backups:', backup)
    print('Restart controller ONLY WHEN NO JOBS ARE ACTIVE: docker compose up -d --no-deps --build backend')
    print('Rebuild frontend: docker compose up -d --no-deps --build frontend')
    print('Open http://localhost:3000/hardening')
    return 0


if __name__ == '__main__':
    try: sys.exit(main())
    except Exception as exc:
        print('STOPPED:', exc, file=sys.stderr)
        sys.exit(2)
