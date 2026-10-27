#!/usr/bin/env python3
"""Conservative source patch for AMD AI Factory v0.3 on Windows.

Split blocking MI300X discovery from scheduler dispatch; add a faster dispatch cadence.
Does not modify DB, containers, telemetry agent, SSH settings, or vLLM.
"""
from __future__ import annotations
import argparse
import ast
from datetime import datetime, timezone
from pathlib import Path
import shutil
import sys

OLD_LOOP = '''async def worker_loop():
    while True:
        try:
            await live.refresh()
            if get_mode() == 'simulation':
                sim_tick()
            else:
                real_tick()
            update_metrics()
        except Exception as exc:
            print(f'worker loop error: {exc}', flush=True)
        await asyncio.sleep(1.5)
'''

NEW_LOOP = '''async def discovery_loop():
    """Refresh real endpoint and GPU telemetry without delaying queued jobs."""
    while True:
        try:
            await live.refresh()
            update_metrics()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f'agent discovery error: {exc}', flush=True)
        await asyncio.sleep(1.5)


async def worker_loop():
    """Dispatch queued work independently of remote GPU agent polling."""
    while True:
        try:
            if get_mode() == 'simulation':
                sim_tick()
            else:
                real_tick()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f'worker loop error: {exc}', flush=True)
        # Fast only while queued work exists; idle mode uses a relaxed cadence.
        await asyncio.sleep(0.25 if pending_count() else 0.5)
'''

OLD_START = '''    await live.refresh()
    task = asyncio.create_task(worker_loop())
    try:
        yield
    finally:
        task.cancel()
        if loadtest_task:
            loadtest_task.cancel()
        for real in list(active_tasks):
            real.cancel()
        await asyncio.gather(task, *list(active_tasks), *([loadtest_task] if loadtest_task else []), return_exceptions=True)
'''

NEW_START = '''    await live.refresh()
    task = asyncio.create_task(worker_loop())
    telemetry_task = asyncio.create_task(discovery_loop())
    try:
        yield
    finally:
        task.cancel()
        telemetry_task.cancel()
        if loadtest_task:
            loadtest_task.cancel()
        for real in list(active_tasks):
            real.cancel()
        await asyncio.gather(task, telemetry_task, *list(active_tasks), *([loadtest_task] if loadtest_task else []), return_exceptions=True)
'''


def target(root: Path) -> Path:
    # Script lives at <project>/scripts; project is parent of scripts.
    return root / 'backend' / 'app' / 'main.py'


def patch_text(before: str) -> str:
    if NEW_LOOP in before and NEW_START in before:
        return before
    replacements = [(OLD_LOOP, NEW_LOOP), (OLD_START, NEW_START)]
    for old, new in replacements:
        count = before.count(old)
        if count != 1:
            raise ValueError(f'Unexpected code version: matching anchor occurs {count} times. No changes made.')
    after = before
    for old, new in replacements:
        after = after.replace(old, new, 1)
    ast.parse(after)
    return after


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description='Safely patch v0.3 scheduler polling on Windows')
    p.add_argument('--apply', action='store_true', help='Write changes after creating a timestamped backup')
    p.add_argument('--project', type=Path, default=Path(__file__).resolve().parents[1], help='Project root')
    args = p.parse_args(argv)
    path = target(args.project)
    if not path.is_file():
        print(f'ERROR: Missing {path}. Make sure the patch script is inside the main project scripts directory.', file=sys.stderr)
        return 2
    original = path.read_text(encoding='utf-8')
    if NEW_LOOP in original and NEW_START in original:
        print('Already patched: discovery and scheduling run independently.')
        return 0
    try:
        revised = patch_text(original)
    except (ValueError, SyntaxError) as e:
        print(f'ERROR: {e}', file=sys.stderr)
        return 2
    if not args.apply:
        print('Patch compatible. No changes made. Use --apply to back up and install the fix.')
        return 0
    now = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup = path.with_suffix(f'.py.before_latency_v05_{now}.bak')
    shutil.copy2(path, backup)
    try:
        path.write_text(revised, encoding='utf-8')
        ast.parse(path.read_text(encoding='utf-8'))
    except Exception:
        shutil.copy2(backup, path)
        raise
    print(f'PATCHED: {path}')
    print(f'BACKUP:  {backup}')
    print('GPU telemetry refresh: separate task, every ~1.5 s')
    print('Job dispatch: ~0.25 s while queue nonempty, ~0.5 s when idle')
    print('Rebuild Windows Docker backend after patch. Do not restart with jobs in flight.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
