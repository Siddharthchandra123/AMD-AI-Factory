#!/usr/bin/env python3
"""Safely patch the Phase 10 controller restart DRILL only (no backend changes)."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
from pathlib import Path
import py_compile
import shutil
import sys

TARGET = Path('scripts/test_phase10_restart.py')


def apply_changes(original: str) -> tuple[str, list[str]]:
    src = original
    changed = []
    # urllib.request can raise http.client.RemoteDisconnected directly, not as URLError.
    old = "import json\n"
    new = "import http.client\nimport json\n"
    if 'import http.client\n' not in src:
        if old not in src:
            raise ValueError('Expected JSON import not found; no patch applied.')
        src = src.replace(old, new, 1)
        changed.append('http exception imports')

    old = 'except (urllib.error.URLError, TimeoutError, ValueError): pass'
    new = ('except (urllib.error.URLError, http.client.HTTPException, '
           'OSError, TimeoutError, ValueError): pass')
    if old in src:
        src = src.replace(old, new, 1)
        changed.append('retry transient backend disconnects')
    elif new not in src:
        raise ValueError('Unexpected polling handler; no patch applied.')

    old = "        status=call(base,'/api/hardening/status')\n"
    new = ("        status=poll(base,lambda:call(base,'/api/hardening/status'),"
           "timeout_s=30,interval=.5)\n"
           "        if not status:\n"
           "            raise RuntimeError('Recovery endpoint unavailable 30s after health check')\n")
    if old in src:
        src = src.replace(old, new, 1)
        changed.append('retry recovery API after restart')
    elif new not in src:
        raise ValueError('Unexpected status request; no patch applied.')

    old = "    out=Path('results/hardening')/('restart_'+"
    # Add precise phase context to any failure, without altering test side effects.
    marker = "    try:\n        batch=call(base,'/api/jobs/batch'"
    replacement = "    phase='submit_test_batch'\n    try:\n        batch=call(base,'/api/jobs/batch'"
    if replacement in src:
        pass
    elif marker in src:
        src = src.replace(marker, replacement, 1)
        changed.append('failure-phase recording')
    else:
        raise ValueError('Unexpected trial structure; no patch applied.')

    transitions = [
        ("        before=poll(base,has_running_and_queued,timeout_s=20)",
         "        phase='wait_for_running_and_queued'\n        before=poll(base,has_running_and_queued,timeout_s=20)"),
        ("        cp=subprocess.run(['docker','compose','restart','backend']",
         "        phase='docker_restart'\n        cp=subprocess.run(['docker','compose','restart','backend']"),
        ("        ready=poll(base,lambda:call(base,'/health')",
         "        phase='wait_for_health'\n        ready=poll(base,lambda:call(base,'/health')"),
        ("        status=poll(base,lambda:call(base,'/api/hardening/status')",
         "        phase='wait_for_recovery_record'\n        status=poll(base,lambda:call(base,'/api/hardening/status')"),
        ("        found=poll(base,finished,timeout_s=args.timeout,interval=1)",
         "        phase='wait_for_terminal_jobs'\n        found=poll(base,finished,timeout_s=args.timeout,interval=1)"),
    ]
    for needle, replacement in transitions:
        if replacement in src:
            continue
        if needle not in src:
            raise ValueError('Expected restart stage not found: '+needle)
        src=src.replace(needle,replacement,1)

    old = "        report['error']=str(e)[:600]\n"
    new = ("        report['error']=str(e)[:600]\n"
           "        report['failed_phase']=phase\n"
           "        # Best-effort diagnostics; never restart or re-submit during failure handling.\n"
           "        try:\n"
           "            report['post_failure_cluster']=call(base,'/api/cluster',timeout=3)\n"
           "        except (urllib.error.URLError, http.client.HTTPException, OSError, TimeoutError, ValueError) as diag:\n"
           "            report['post_failure_cluster_error']=type(diag).__name__+': '+str(diag)[:160]\n"
           "        try:\n"
           "            report['post_failure_recovery']=call(base,'/api/hardening/status',timeout=3)\n"
           "        except (urllib.error.URLError, http.client.HTTPException, OSError, TimeoutError, ValueError) as diag:\n"
           "            report['post_failure_recovery_error']=type(diag).__name__+': '+str(diag)[:160]\n")
    if new in src:
        pass
    elif old in src:
        src=src.replace(old,new,1)
        changed.append('failure diagnostics')
    else:
        raise ValueError('Unexpected exception handler; no patch applied.')

    if src==original and not ('http.client.HTTPException' in src and "report['failed_phase']" in src):
        raise ValueError('Patch validation failed')
    return src,changed


def main() -> int:
    parser=argparse.ArgumentParser(description='Fix transient disconnection handling in the Phase 10 restart test')
    parser.add_argument('--apply', action='store_true')
    args=parser.parse_args()
    if not TARGET.is_file():
        print('ERROR: Expected scripts/test_phase10_restart.py in project root.',file=sys.stderr)
        return 2
    original=TARGET.read_text(encoding='utf-8')
    try:
        updated, changes=apply_changes(original)
        compile(updated,str(TARGET),'exec')
    except (ValueError,SyntaxError) as exc:
        print('STOPPED: incompatible test script:',exc,file=sys.stderr)
        return 2
    if not changes:
        print('ALREADY PATCHED: Phase 10 restart test v1.0.1')
        return 0
    if not args.apply:
        print('COMPATIBLE: can safely patch the restart test. Run with --apply.')
        print('Planned corrections: '+', '.join(changes))
        return 0
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup=TARGET.with_name(TARGET.name+'.bak_'+stamp)
    shutil.copy2(TARGET,backup)
    TARGET.write_text(updated,encoding='utf-8')
    print('PATCH APPLIED:',TARGET)
    print('BACKUP:',backup)
    print('FIXES:',', '.join(changes))
    print('No Docker rebuild required; only the local test harness was changed.')
    return 0

if __name__=='__main__':
    sys.exit(main())
