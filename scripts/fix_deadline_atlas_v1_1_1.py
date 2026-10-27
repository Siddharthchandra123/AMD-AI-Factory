#!/usr/bin/env python3
"""Fix not-applicable empty Scheduler Lab deadline charts in Benchmark Atlas v1.1.

Usage from the project root:
    python scripts/fix_deadline_atlas_v1_1_1.py
    python scripts/fix_deadline_atlas_v1_1_1.py --apply
Creates a timestamped backup. No benchmark evidence is modified.
"""
from __future__ import annotations
import argparse
from pathlib import Path
from datetime import datetime, timezone

OLD = "            bar(f'17_{slug}_policy_deadlines.svg','Synthetic deadline completion - '+scenario,lab,[('Deadline met %',[x.get('deadline_met_pct') for x in rows])],'%')"
NEW = """            # Only chart deadlines where the workload assigned at least one.
            deadline_vals = [x.get('deadline_met_pct') for x in rows]
            if any(v is not None for v in deadline_vals):
                bar(f'17_{slug}_policy_deadlines.svg','Synthetic deadline completion - '+scenario,lab,[('Deadline met %',deadline_vals)],'%')"""

# When every policy genuinely achieved 0%, annotate that separately from no deadline data.
OLD_ZERO = "    s=svg_start(w,h,title)\n    if subtitle:s+=svg_text(30,62,subtitle,12,'#94a3b8')"
NEW_ZERO = """    s=svg_start(w,h,title)
    if subtitle:s+=svg_text(30,62,subtitle,12,'#94a3b8')
    values = [v for _, arr in series for v in arr if v is not None]
    if values and all(v == 0 for v in values):
        s+=svg_text(w/2,T+ht/2,'All recorded values are 0 (valid results)',19,'#cbd5e1','middle')"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--project', default='.')
    args = ap.parse_args()
    target=Path(args.project).resolve()/'scripts'/'generate_benchmark_atlas.py'
    if not target.is_file():
        raise SystemExit(f'NOT FOUND: {target}')
    content=target.read_text(encoding='utf-8')
    if 'deadline_vals = [x.get(\'deadline_met_pct\') for x in rows]' in content:
        print('ALREADY FIXED: deadline chart applicable-data guard exists')
        return 0
    if OLD not in content:
        raise SystemExit('STOPPED: expected Benchmark Atlas v1.1 code not found. File unchanged.')
    if OLD_ZERO not in content:
        raise SystemExit('STOPPED: expected chart renderer section not found. File unchanged.')
    candidate=content.replace(OLD,NEW).replace(OLD_ZERO,NEW_ZERO,1)
    compile(candidate,str(target),'exec')
    if not args.apply:
        print('COMPATIBLE: Atlas v1.1 supports this fix. Run again with --apply.')
        return 0
    timestamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup=target.with_name(target.name+'.backup_'+timestamp)
    backup.write_text(content,encoding='utf-8')
    target.write_text(candidate,encoding='utf-8')
    print('FIX APPLIED:',target)
    print('Backup:',backup)
    print('Only deadline-chart generation changed; original benchmark evidence untouched.')
    return 0

if __name__=='__main__':
    raise SystemExit(main())
