#!/usr/bin/env python3
"""Fix two Windows-only pytest fixture problems in AMD AI Factory Mission Control.

Affects only tests/test_phase11_release.py and tests/test_scheduler_lab.py.
It does NOT modify source, runtime, data, or agent code.

Usage from project root:
    python fix_amd_factory_windows_test_fixtures.py --check
    python fix_amd_factory_windows_test_fixtures.py --apply
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import shutil
import sys

MARKER = '        # Test-fixture normalization: start before Scheduler Lab install.\n'


def phase11_fixed(src: str) -> str:
    old = "        path.write_text(content, encoding='utf8')"
    new = '        path.write_bytes(content.encode("utf-8"))'
    if new in src:
        return src
    if old not in src:
        raise ValueError("Phase 11 test fixture differs from expected version; no changes applied")
    return src.replace(old, new, 1)


def scheduler_fixed(src: str) -> str:
    if MARKER in src:
        return src
    anchor = "        for rel in ('frontend/src/app/scheduler-lab/page.tsx'"
    if src.count(anchor) != 1:
        raise ValueError("Scheduler Lab fixture differs from expected version; no changes applied")
    addition = (
        MARKER
        + "        # The developer's source project may *already* have this feature installed.\n"
        + "        # Strip only the installed markers from copied temporary fixtures,\n"
        + "        # so the installer is actually tested in an uninstalled state.\n"
        + "        compose_file = tmp / 'docker-compose.yml'\n"
        + "        compose_content = compose_file.read_text(encoding='utf-8')\n"
        + "        compose_content = ''.join(\n"
        + "            line for line in compose_content.splitlines(keepends=True)\n"
        + "            if 'SCHEDULER_LAB_RESULTS_DIR' not in line\n"
        + "            and './results/scheduler-lab:/app/scheduler-lab-evidence:ro' not in line\n"
        + "        )\n"
        + "        compose_file.write_text(compose_content, encoding='utf-8')\n"
        + "        home_file = tmp / 'frontend/src/app/page.tsx'\n"
        + "        home_content = home_file.read_text(encoding='utf-8')\n"
        + "        home_content = ''.join(\n"
        + "            line for line in home_content.splitlines(keepends=True)\n"
        + "            if 'href=\"/scheduler-lab\"' not in line\n"
        + "        )\n"
        + "        home_file.write_text(home_content, encoding='utf-8')\n"
    )
    return src.replace(anchor, addition + anchor, 1)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument('--check', action='store_true')
    group.add_argument('--apply', action='store_true')
    args = p.parse_args()

    root = Path.cwd().resolve()
    paths = [
        (root / 'tests' / 'test_phase11_release.py', phase11_fixed),
        (root / 'tests' / 'test_scheduler_lab.py', scheduler_fixed),
    ]
    planned = []
    try:
        for path, modify in paths:
            if not path.is_file():
                raise FileNotFoundError(f'Missing {path.relative_to(root)}')
            original = path.read_text(encoding='utf-8')
            changed = modify(original)
            if changed != original:
                planned.append((path, changed))
    except (ValueError, OSError) as err:
        print('STOPPED:', err)
        return 2

    if not planned:
        print('Already fixed; no files changed.')
        return 0
    print('Planned test-only changes:')
    for path, _ in planned:
        print(' -', path.relative_to(root))
    if args.check:
        print('Dry run: no files modified. Use --apply to make the changes.')
        return 0

    backup = root / 'backups' / ('pytest_fixtures_' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    backup.mkdir(parents=True, exist_ok=False)
    for path, _ in planned:
        shutil.copy2(path, backup / path.name)
    try:
        for path, content in planned:
            with path.open('w', encoding='utf-8', newline='\n') as f:
                f.write(content)
    except OSError:
        for path, _ in planned:
            shutil.copy2(backup / path.name, path)
        raise

    print('Applied. Original tests backed up to', backup)
    print('Run: python -m pytest -q -o "pythonpath=backend agent" --import-mode=importlib')
    return 0

if __name__ == '__main__':
    sys.exit(main())
