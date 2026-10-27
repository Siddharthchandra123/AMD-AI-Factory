#!/usr/bin/env python3
"""Enable v0.7 offline evidence viewer without touching FastAPI, Postgres, or Redis.
Run in AMD AI Factory project root: python scripts/enable_offline_analytics_v0_7.py --apply
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import shutil
import sys

PROJECT = Path.cwd()
COMPOSE = PROJECT / "docker-compose.yml"
HOME = PROJECT / "frontend/src/app/page.tsx"
SOURCES = [
    PROJECT / "frontend/src/app/benchmarks/page.tsx",
    PROJECT / "frontend/src/app/benchmarks/benchmarks.css",
    PROJECT / "frontend/src/app/api/benchmarks/route.ts",
    PROJECT / "frontend/src/lib/benchmark-loader.ts",
]
NAV = '        <a href="/benchmarks"><BarChart3 size={18}/> Benchmark Analytics <ArrowRight size={13}/></a>\n'


def plan() -> tuple[str, str, bool, bool]:
    absent = [str(p.relative_to(PROJECT)) for p in SOURCES if not p.is_file()]
    if absent:
        raise RuntimeError("Missing analytics add-on files: " + ", ".join(absent) + ". Extract the ZIP first.")
    if not (PROJECT / "results/mi300x").is_dir():
        raise RuntimeError("Expected results/mi300x folder. Copy benchmark evidence here before enabling the viewer.")
    if not COMPOSE.is_file() or not HOME.is_file():
        raise RuntimeError("Run from AMD AI Factory project root (docker-compose.yml and frontend/src/app/page.tsx required).")
    compose = COMPOSE.read_text(encoding="utf-8")
    page = HOME.read_text(encoding="utf-8")
    anchor = "  frontend:\n"
    end = "  prometheus:\n"
    if compose.count(anchor) != 1 or compose.count(end) != 1:
        raise RuntimeError("Unexpected docker-compose.yml service layout; no changes made.")
    first = compose.index(anchor)
    last = compose.index(end, first + len(anchor))
    block = compose[first:last]
    if "    environment:\n" not in block or "      NEXT_PUBLIC_API_URL:" not in block:
        raise RuntimeError("Unexpected frontend environment layout; no changes made.")
    env = "      BENCHMARK_RESULTS_DIR: /app/benchmark-evidence\n"
    mount = "      - ./results/mi300x:/app/benchmark-evidence:ro\n"
    environment_needs_change = env not in block
    mount_needs_change = mount not in block
    if environment_needs_change:
        line = next((s for s in block.splitlines(keepends=True) if "NEXT_PUBLIC_API_URL:" in s), None)
        if not line:
            raise RuntimeError("Unable to locate the frontend env anchor.")
        block = block.replace(line, line + env, 1)
    if mount_needs_change:
        if "    volumes:\n" in block:
            block = block.replace("    volumes:\n", "    volumes:\n" + mount, 1)
        else:
            # Insert before `networks:` when present; otherwise append before service end.
            if "    networks:" in block:
                block = block.replace("    networks:", "    volumes:\n" + mount + "    networks:", 1)
            else:
                block += "    volumes:\n" + mount
    updated_compose = compose[:first] + block + compose[last:]
    if "href=\"/benchmarks\"" in page:
        updated_page = page
    else:
        nav_anchor = '        <a href="http://localhost:3001"'
        if page.count(nav_anchor) != 1:
            raise RuntimeError("Dashboard sidebar changed; can't insert navigation safely.")
        updated_page = page.replace(nav_anchor, NAV + nav_anchor, 1)
    return updated_compose, updated_page, updated_compose != compose, updated_page != page


def main() -> int:
    parser = argparse.ArgumentParser(description="Enable offline MI300X evidence analytics in existing Docker frontend")
    parser.add_argument("--apply", action="store_true", help="Save backup and apply checked changes")
    args = parser.parse_args()
    try:
        new_compose, new_page, change_compose, change_page = plan()
    except (OSError, RuntimeError) as exc:
        print("STOPPED:", exc)
        return 2
    print("Project:", PROJECT)
    print("Read-only evidence: results/mi300x")
    print("Docker Compose update required:", change_compose)
    print("Frontend sidebar link update required:", change_page)
    if not (change_compose or change_page):
        print("Already installed; no changes required.")
        return 0
    if not args.apply:
        print("Compatibility OK. Apply with: python .\\scripts\\enable_offline_analytics_v0_7.py --apply")
        return 0
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = PROJECT / "backups" / f"analytics_v0_7_{stamp}"
    backup.mkdir(parents=True, exist_ok=False)
    if change_compose:
        shutil.copy2(COMPOSE, backup / "docker-compose.yml")
    if change_page:
        shutil.copy2(HOME, backup / "page.tsx")
    try:
        if change_compose:
            COMPOSE.write_text(new_compose, encoding="utf-8")
        if change_page:
            HOME.write_text(new_page, encoding="utf-8")
    except Exception:
        if change_compose:
            shutil.copy2(backup / "docker-compose.yml", COMPOSE)
        if change_page:
            shutil.copy2(backup / "page.tsx", HOME)
        raise
    print("Applied. Backup:", backup)
    print("Next: docker compose up -d --build frontend")
    print("Then: http://localhost:3000/benchmarks")
    return 0


if __name__ == "__main__":
    sys.exit(main())
