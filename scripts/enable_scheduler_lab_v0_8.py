#!/usr/bin/env python3
"""Safely mount read-only Scheduler Lab evidence in the existing Next.js frontend.
No backend/Redis/PostgreSQL/agent/GPU files are modified.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
from pathlib import Path
import shutil
import sys

PROJECT=Path.cwd()
COMPOSE=PROJECT/'docker-compose.yml'
HOME=PROJECT/'frontend/src/app/page.tsx'
SOURCES=[PROJECT/'frontend/src/app/scheduler-lab/page.tsx',
         PROJECT/'frontend/src/app/scheduler-lab/scheduler-lab.css',
         PROJECT/'frontend/src/app/api/scheduler-lab/route.ts',
         PROJECT/'scripts/evaluate_queue_policies_v0_8.py']
ENV='      SCHEDULER_LAB_RESULTS_DIR: /app/scheduler-lab-evidence\n'
MOUNT='      - ./results/scheduler-lab:/app/scheduler-lab-evidence:ro\n'
NAV='        <a href="/scheduler-lab"><Layers size={18}/> Scheduler Lab <ArrowRight size={13}/></a>\n'


def planned():
    missing=[str(x.relative_to(PROJECT)) for x in SOURCES if not x.is_file()]
    if missing:
        raise RuntimeError('Missing Phase 8 files: '+', '.join(missing)+'. Extract ZIP into project root.')
    if not (COMPOSE.is_file() and HOME.is_file()):
        raise RuntimeError('Run from project root containing docker-compose.yml and frontend/src/app/page.tsx')
    if not (PROJECT/'results/scheduler-lab/latest.json').is_file():
        raise RuntimeError('No evaluation results. Run: python .\\scripts\\evaluate_queue_policies_v0_8.py')
    compose=COMPOSE.read_text(encoding='utf-8')
    main=HOME.read_text(encoding='utf-8')
    first='  frontend:\n'
    second='  prometheus:\n'
    if compose.count(first)!=1 or compose.count(second)!=1:
        raise RuntimeError('Unexpected Docker Compose layout; no changes made')
    left=compose.index(first)
    right=compose.index(second,left+len(first))
    block=compose[left:right]
    if '    environment:\n' not in block or '      NEXT_PUBLIC_API_URL:' not in block:
        raise RuntimeError('Frontend environment structure differs; no changes made')
    if ENV not in block:
        line=next((r for r in block.splitlines(keepends=True) if '      NEXT_PUBLIC_API_URL:' in r),None)
        if not line:
            raise RuntimeError('No environment insertion point')
        block=block.replace(line,line+ENV,1)
    if MOUNT not in block:
        if '    volumes:\n' in block:
            block=block.replace('    volumes:\n','    volumes:\n'+MOUNT,1)
        elif '    networks:' in block:
            block=block.replace('    networks:','    volumes:\n'+MOUNT+'    networks:',1)
        else:
            raise RuntimeError('Unexpected frontend network layout; no changes made')
    changed_compose=compose[:left]+block+compose[right:]
    if 'href="/scheduler-lab"' not in main:
        anchor='        <a href="http://localhost:3001"'
        if main.count(anchor)!=1:
            raise RuntimeError('Unexpected sidebar navigation: unable to add link safely')
        main=main.replace(anchor,NAV+anchor,1)
    return changed_compose,main


def main() -> int:
    parser=argparse.ArgumentParser(description='Install Scheduler Lab read-only Next.js page')
    parser.add_argument('--apply',action='store_true',help='Backup and apply validated changes')
    args=parser.parse_args()
    try:
        new_compose,new_home=planned()
    except (RuntimeError,OSError) as error:
        print('STOPPED:',error)
        return 2
    updates=[(COMPOSE,new_compose),(HOME,new_home)]
    to_write=[(p,s) for p,s in updates if p.read_text(encoding='utf-8')!=s]
    print('Scheduler Lab files compatible:', True)
    print('Changes needed:', [str(p.relative_to(PROJECT)) for p,_ in to_write])
    if not to_write:
        print('Already installed. No changes required.')
        return 0
    if not args.apply:
        print('Compatibility OK. Apply with: python .\\scripts\\enable_scheduler_lab_v0_8.py --apply')
        return 0
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup=PROJECT/'backups'/('scheduler_lab_v0_8_'+stamp)
    backup.mkdir(parents=True,exist_ok=False)
    for p,_ in to_write:
        shutil.copy2(p,backup/(('docker-compose.yml' if p==COMPOSE else 'page.tsx')))
    try:
        for p,s in to_write:
            p.write_text(s,encoding='utf-8')
    except Exception:
        for p,_ in to_write:
            shutil.copy2(backup/('docker-compose.yml' if p==COMPOSE else 'page.tsx'),p)
        raise
    print('Updated frontend integration. Backups at:',backup)
    print('Next: docker compose up -d --no-deps --build frontend')
    print('Open http://localhost:3000/scheduler-lab')
    return 0

if __name__=='__main__':
    sys.exit(main())
