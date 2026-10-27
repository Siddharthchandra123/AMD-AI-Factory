#!/usr/bin/env python3
"""Build a secret-conscious source release from the user's ACTUAL local project.

No service restarts or mutations. Only writes to dist/ (or specified --output).
All evidence from results/ is excluded by default. Curated aggregate CSVs in
 docs/phase11/evidence remain included. Never uploads files.
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys
import zipfile
from datetime import datetime, timezone

DROP_DIR_NAMES = {
    '.git', '.next', 'node_modules', '__pycache__', '.pytest_cache',
    '.mypy_cache', '.ruff_cache', '.venv', 'venv', 'env', '.tox',
    '.idea', '.vscode', 'backups', 'results', 'dist', 'release', 'releases',
    'tmp', 'temp', '.cache', 'coverage', 'htmlcov', 'data-cache',
}
EXCLUDE_EXT = {
    '.pem', '.prv', '.key', '.p12', '.pfx', '.p8', '.sqlite', '.sqlite3',
    '.db', '.log', '.zip', '.tar', '.gz', '.7z', '.rar', '.parquet', '.arrow',
    '.onnx', '.safetensors', '.bin', '.pt', '.pth', '.ckpt', '.npy', '.npz',
    '.ipynb', '.mp4', '.wav', '.mp3', '.csv', '.tsv', '.bak', '.orig',
}
TEXT_EXT = {'.py', '.md', '.json', '.yml', '.yaml', '.toml', '.ini', '.cfg',
            '.txt', '.ts', '.tsx', '.js', '.jsx', '.mjs', '.css', '.sh', '.ps1',
            '.svg', '.sql', '.xml', '.html', '.env'}
GOOD_EXT = TEXT_EXT | {'.png', '.jpg', '.jpeg', '.webp', '.gif', '.ico', '.lock', '.mmd'}
GOOD_NAMES = {'Dockerfile', '.dockerignore', '.gitignore', '.env.example', 'LICENSE',
              'Makefile', 'requirements.txt', 'package-lock.json', 'next-env.d.ts'}
SECRET_PATTERNS = [
    ('private key', re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----')),
    ('GitHub credential', re.compile(r'\b(?:ghp_|gho_|ghu_|ghs_|ghr_|github_pat_)[A-Za-z0-9_]{12,}\b')),
    ('OpenAI-style API key', re.compile(r'\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,}\b')),
    ('AWS access key', re.compile(r'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b')),
]
ASSIGNMENT_RE = re.compile(r'(?m)^\s*(?:export\s+)?(?:MISSION_AGENT_TOKEN|MISSION_CONTROL_WRITE_TOKEN)\s*=\s*([^\r\n#]+)')


def include_file(relative: Path, max_bytes: int, root: Path) -> bool:
    parts = relative.parts
    if any(part.lower() in DROP_DIR_NAMES for part in parts[:-1]):
        return False
    name = relative.name
    lname = name.lower()
    if name.startswith('.') and name not in {'.gitignore', '.dockerignore', '.env.example'}:
        return False
    if lname in {'.env', 'id_rsa', 'id_ed25519', 'credentials', 'credentials.json', 'secrets.json', 'known_hosts'}:
        return False
    if lname.startswith('.env.') and name != '.env.example':
        return False
    if any(fnmatch.fnmatch(lname, pat) for pat in ['*secret*', '*token_backup*', '*credential*', '*_private.*']):
        return False
    if lname.endswith(('.bak', '.backup')):
        return False
    if relative.suffix.lower() in EXCLUDE_EXT and not (len(parts) >= 3 and parts[:2] == ('docs','phase11') and parts[2] == 'evidence' and relative.suffix.lower() == '.csv'):
        return False
    if name not in GOOD_NAMES and relative.suffix.lower() not in GOOD_EXT and not (len(parts) >= 3 and parts[:2] == ('docs','phase11') and parts[2] == 'evidence' and relative.suffix.lower() == '.csv'):
        return False
    try:
        if relative.is_absolute() or (root / relative).is_symlink() or (root / relative).stat().st_size > max_bytes:
            return False
    except OSError:
        return False
    return True


def secret_findings(name: str, data: bytes) -> list[str]:
    if len(data) > 2_000_000 or b'\x00' in data[:2048]:
        return []
    try:
        content = data.decode('utf-8')
    except UnicodeDecodeError:
        return []
    findings = [label for label, pattern in SECRET_PATTERNS if pattern.search(content)]
    if name.endswith('.env.example'):
        for match in ASSIGNMENT_RE.finditer(content):
            val = match.group(1).strip().strip('"\'')
            if val and val not in {'${MISSION_AGENT_TOKEN}', '${MISSION_CONTROL_WRITE_TOKEN}'}:
                findings.append('nonempty token in .env.example')
    return sorted(set(findings))


def gather(root: Path, max_bytes: int = 12_000_000) -> list[Path]:
    return sorted((p.relative_to(root) for p in root.rglob('*') if p.is_file() and include_file(p.relative_to(root), max_bytes, root)), key=lambda x: x.as_posix())


def build_archive(root: Path, destination: Path, version: str, dry_run: bool = False, allow_missing: bool = False) -> dict:
    root = root.resolve()
    required = ['docker-compose.yml', 'backend/app/main.py', 'frontend/package.json', 'agent/server.py']
    missing = [x for x in required if not (root / x).is_file()]
    if missing and not allow_missing:
        raise RuntimeError('Cannot produce source release; missing: ' + ', '.join(missing))
    files = gather(root)
    # Replace the root README only IN the archive, preserving the original in a separate path.
    new_readme = root / 'docs' / 'phase11' / 'RELEASE_README.md'
    if not new_readme.is_file():
        raise RuntimeError('Missing docs/phase11/RELEASE_README.md. Extract the entire Phase 11 kit first.')
    findings = []
    for rel in files:
        detected = secret_findings(rel.as_posix(), (root / rel).read_bytes())
        if detected:
            findings.append({'file': rel.as_posix(), 'issue_types': detected})
    if findings:
        # Show paths + issue classifications only, never the matching secret itself.
        raise RuntimeError('POTENTIAL SECRET DETECTED, release blocked: ' + json.dumps(findings))
    package_name = f'AMD-AI-Factory-Mission-Control-{version}'
    out = {'version': version, 'source_root': str(root), 'file_count': len(files),
           'excluded_runtime_data': True, 'included_paths': [f.as_posix() for f in files],
           'missing_required': missing, 'dry_run': dry_run}
    if (root / 'README.md').is_file():
        original_readme = (root / 'README.md').read_bytes()
        changes = secret_findings('docs/phase11/ORIGINAL_README.md', original_readme)
        if changes:
            raise RuntimeError('Potential secret in original README; review before packaging')
    else:
        original_readme = None
    if dry_run:
        return out
    destination.parent.mkdir(parents=True, exist_ok=True)
    hashes = {}
    with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED, compresslevel=7, strict_timestamps=False) as z:
        for rel in files:
            content = new_readme.read_bytes() if rel.as_posix() == 'README.md' else (root / rel).read_bytes()
            arc = f'{package_name}/{rel.as_posix()}'
            # Fixed timestamp for reproducibility; preserve file content and simple Unix permissions.
            info = zipfile.ZipInfo(arc, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o644 << 16)
            z.writestr(info, content, compress_type=zipfile.ZIP_DEFLATED, compresslevel=7)
            hashes[rel.as_posix()] = hashlib.sha256(content).hexdigest()
        if original_readme is not None:
            legacy_path = 'docs/phase11/ORIGINAL_README.md'
            if legacy_path not in hashes:
                info = zipfile.ZipInfo(f'{package_name}/{legacy_path}', date_time=(2026, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                z.writestr(info, original_readme, compress_type=zipfile.ZIP_DEFLATED, compresslevel=7)
                hashes[legacy_path] = hashlib.sha256(original_readme).hexdigest()
        manifest = {'release': version, 'scope': 'source code + curated documentation; local data excluded',
                    'files_sha256': hashes,
                    'warnings': [
                        'GPU inference measured only on one real serving endpoint',
                        'Phase 8 experiments are CPU-simulated, not measured on real GPUs',
                        'Restart drill is local simulation only',
                        'Local security audit is not a penetration test',
                        'This archive is generated from the invoking user local folder; rebuild and test before publishing',
                    ]}
        info = zipfile.ZipInfo(f'{package_name}/RELEASE_MANIFEST.json', date_time=(2026, 1, 1, 0, 0, 0))
        z.writestr(info, json.dumps(manifest, indent=2) + '\n')
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    checksum_file = destination.with_suffix(destination.suffix + '.sha256')
    checksum_file.write_text(f'{digest}  {destination.name}\n', encoding='utf-8')
    out.update({'zip': str(destination), 'sha256': digest, 'checksum_file': str(checksum_file)})
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description='Phase 11: Create a safe, source-only GitHub release candidate ZIP')
    parser.add_argument('--root', default='.', help='Your actual amd-ai-factory folder')
    parser.add_argument('--version', default='v1.0.0-rc1')
    parser.add_argument('--output', default=None, help='Output ZIP path (default dist/...zip)')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be packaged; no file created')
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    name = f'AMD-AI-Factory-Mission-Control-{args.version}.zip'
    output = Path(args.output).resolve() if args.output else root / 'dist' / name
    try:
        result = build_archive(root, output, args.version, args.dry_run)
    except (RuntimeError, OSError) as exc:
        print('RELEASE BLOCKED:', exc, file=sys.stderr)
        return 2
    print(json.dumps({k: v for k, v in result.items() if k != 'included_paths'}, indent=2))
    print('Runtime datasets, raw benchmark traces and real .env secrets are excluded by design.')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
