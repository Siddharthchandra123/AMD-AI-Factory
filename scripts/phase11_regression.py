#!/usr/bin/env python3
"""Non-disruptive Phase 11 regression checks. No submissions or restarts."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


def check(name: str, status: str, detail: str, checks: list) -> None:
    checks.append({'name': name, 'status': status, 'detail': detail})
    print(f'[{status:4}] {name}: {detail}')


def get_json(url: str, timeout: float = 6):
    with urlopen(url, timeout=timeout) as response:
        return json.loads(response.read(3_000_000).decode('utf-8'))


def get_status(url: str, timeout: float = 10):
    with urlopen(url, timeout=timeout) as response:
        response.read(16)
        return response.status


def latest_json(folder: Path, glob: str):
    items = sorted(folder.glob(glob), key=lambda p: p.stat().st_mtime, reverse=True)
    for item in items:
        try:
            return item, json.loads(item.read_text(encoding='utf-8'))
        except (OSError, ValueError, UnicodeError):
            continue
    return None, None


def run(root: Path, backend: str, frontend: str, offline: bool, compose: bool):
    root = root.resolve()
    checks = []
    for name in ['docker-compose.yml', 'backend/app/main.py', 'agent/server.py',
                 'frontend/package.json', 'frontend/src/app/page.tsx']:
        check('source/' + name, 'PASS' if (root / name).is_file() else 'FAIL',
              'Present' if (root / name).is_file() else 'Missing required source file', checks)

    for name, rel in [
        ('benchmark analytics page', 'frontend/src/app/benchmarks/page.tsx'),
        ('scheduler lab page', 'frontend/src/app/scheduler-lab/page.tsx'),
        ('hardening page', 'frontend/src/app/hardening/page.tsx'),
        ('phase 10 restart script', 'scripts/test_phase10_restart.py'),
        ('phase 8 synthetic evaluation', 'scripts/evaluate_queue_policies_v0_8.py'),
    ]:
        exists = (root / rel).is_file()
        check(name, 'PASS' if exists else 'WARN', 'Installed' if exists else 'Not present locally', checks)

    example = root / '.env.example'
    if example.exists():
        try:
            text = example.read_text(encoding='utf-8')
            # security audit has a more comprehensive check; do not print any values.
            import re
            unsafe = any(m.group(1).strip().strip('"\'') for m in
                         re.finditer(r'(?m)^\s*MISSION_AGENT_TOKEN\s*=\s*([^\r\n#]*)', text))
            check('example agent token empty', 'FAIL' if unsafe else 'PASS',
                  'Credential may be embedded' if unsafe else 'No populated MISSION_AGENT_TOKEN', checks)
        except (OSError, UnicodeError):
            check('example agent token empty', 'WARN', 'Could not read example file', checks)
    else:
        check('example agent token empty', 'WARN', '.env.example not found', checks)

    audit_file = root / 'results' / 'hardening' / 'security_audit.json'
    if audit_file.is_file():
        try:
            audit = json.loads(audit_file.read_text(encoding='utf-8'))
            ok = audit.get('status') == 'pass' and all(c.get('passed') for c in audit.get('checks', []))
            check('latest security audit', 'PASS' if ok else 'FAIL',
                  'All audit checks passed' if ok else 'Audit contains failed/review-needed checks', checks)
        except (ValueError, OSError):
            check('latest security audit', 'WARN', 'Malformed audit report', checks)
    else:
        check('latest security audit', 'WARN', 'No local results/hardening/security_audit.json found', checks)

    restpath, restart = latest_json(root / 'results' / 'hardening', 'restart_*/report.json')
    if restart is not None:
        check('restart drill evidence', 'PASS' if restart.get('status') == 'passed' else 'WARN',
              f'{restart.get("status", "unknown")} ({restpath.parent.name})', checks)
    else:
        check('restart drill evidence', 'WARN', 'No readable restart drill report.json', checks)

    relpath, rel = latest_json(root / 'results' / 'reliability', 'reliability_*/report.json')
    if rel is not None:
        check('worker drain drill evidence', 'PASS' if rel.get('status') == 'passed' else 'WARN',
              f'{rel.get("status", "unknown")} ({relpath.parent.name})', checks)
    else:
        check('worker drain drill evidence', 'WARN', 'No readable reliability report.json', checks)

    real_archive = root / 'results' / 'mi300x'
    have_real = any(real_archive.glob('v2_*/summary.json')) if real_archive.is_dir() else False
    check('archived real MI300X benchmark summaries', 'PASS' if have_real else 'WARN',
          'Found timestamped benchmark summaries' if have_real else 'No local v2 summary.json archive found', checks)

    if compose:
        try:
            p = subprocess.run(['docker', 'compose', 'config', '-q'], cwd=root,
                               text=True, capture_output=True, timeout=25)
            check('Docker Compose config', 'PASS' if p.returncode == 0 else 'FAIL',
                  'Compose configuration valid' if p.returncode == 0 else 'Invalid Compose configuration; run docker compose config manually', checks)
        except (OSError, subprocess.TimeoutExpired):
            check('Docker Compose config', 'WARN', 'Docker Compose not available or timed out', checks)

    if not offline:
        for label, url in [
            ('backend health', f'{backend.rstrip("/")}/health'),
            ('frontend home', f'{frontend.rstrip("/")}/'),
            ('frontend benchmarks', f'{frontend.rstrip("/")}/benchmarks'),
            ('frontend scheduler lab', f'{frontend.rstrip("/")}/scheduler-lab'),
            ('frontend hardening', f'{frontend.rstrip("/")}/hardening'),
        ]:
            try:
                status = get_status(url)
                check(label, 'PASS' if status == 200 else 'FAIL', f'HTTP {status}', checks)
            except (URLError, HTTPError, TimeoutError, OSError, ValueError) as ex:
                check(label, 'FAIL', f'Not reachable ({type(ex).__name__})', checks)
        try:
            rt = get_json(f'{backend.rstrip("/")}/api/runtime')
            mode = rt.get('mode', 'unknown')
            check('runtime mode', 'PASS' if mode == 'simulation' else 'WARN',
                  f'{mode}; local release smoke test expects simulation', checks)
        except (URLError, HTTPError, TimeoutError, OSError, ValueError) as ex:
            check('runtime mode', 'FAIL', f'Not reachable ({type(ex).__name__})', checks)
        try:
            state = get_json(f'{backend.rstrip("/")}/api/cluster')
            summary = state.get('summary') or {}
            waiting = summary.get('queued_jobs', 'unknown')
            running = summary.get('running_jobs', 'unknown')
            check('idle controller', 'PASS' if waiting == 0 and running == 0 else 'WARN',
                  f'queued={waiting}, running={running}', checks)
        except (URLError, HTTPError, TimeoutError, OSError, ValueError) as ex:
            check('idle controller', 'FAIL', f'Not reachable ({type(ex).__name__})', checks)
        try:
            hard = get_json(f'{backend.rstrip("/")}/api/hardening/status')
            available = (hard.get('recovery') or {}).get('available')
            healthy = (hard.get('workers') or {}).get('counts', {}).get('healthy')
            check('controller recovery status', 'PASS' if available is True else 'WARN',
                  f'recovery_available={available}', checks)
            check('sim worker health', 'PASS' if isinstance(healthy, int) and healthy > 0 else 'WARN',
                  f'healthy_workers={healthy}', checks)
        except (URLError, HTTPError, TimeoutError, OSError, ValueError) as ex:
            check('controller recovery status', 'FAIL', f'Not reachable ({type(ex).__name__})', checks)

    counts = {key: sum(c['status'] == key for c in checks) for key in ['PASS','WARN','FAIL']}
    overall = 'fail' if counts['FAIL'] else ('pass_with_warnings' if counts['WARN'] else 'pass')
    report = {'timestamp_utc': datetime.now(timezone.utc).isoformat(), 'status': overall,
              'mode': 'offline' if offline else 'read_only_live', 'checks': checks, 'counts': counts,
              'scope': 'Non-disruptive local release verification; not physical GPU validation, security penetration test, or crash-recovery drill'}
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(description='Phase 11 read-only local release regression')
    ap.add_argument('--root', default='.')
    ap.add_argument('--backend', default='http://127.0.0.1:8000')
    ap.add_argument('--frontend', default='http://127.0.0.1:3000')
    ap.add_argument('--offline', action='store_true', help='Skip all HTTP checks')
    ap.add_argument('--compose', action='store_true', help='Also validate docker compose config')
    ap.add_argument('--output', default=None)
    a = ap.parse_args(argv)
    root = Path(a.root).resolve()
    report = run(root, a.backend, a.frontend, a.offline, a.compose)
    outfile = Path(a.output).resolve() if a.output else root / 'results' / 'release' / 'phase11_regression_latest.json'
    outfile.parent.mkdir(parents=True, exist_ok=True)
    outfile.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(f'RESULT: {report["status"]} {report["counts"]} | Saved {outfile}')
    return 1 if report['status'] == 'fail' else 0

if __name__ == '__main__':
    raise SystemExit(main())
