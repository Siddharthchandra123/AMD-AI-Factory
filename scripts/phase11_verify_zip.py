#!/usr/bin/env python3
"""Independent release ZIP checker. Never extracts files or runs uploaded code."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import zipfile

from phase11_release import secret_findings


def verify(path):
    with zipfile.ZipFile(path) as z:
        entries = z.namelist()
        if not entries:
            raise ValueError('Empty ZIP')
        if len(entries) != len(set(entries)):
            raise ValueError('Duplicate archive paths')
        forbidden_parts = {'node_modules', 'results', 'backups', '.git', '.venv', '.next', 'dist', 'releases'}
        for name in entries:
            parts = name.split('/')
            if '..' in parts or name.startswith('/') or '\\' in name:
                raise ValueError('Unsafe ZIP member path: ' + name)
            if (any(part in forbidden_parts for part in parts) or
                any(part == '.env' or (part.startswith('.env.') and part != '.env.example') for part in parts) or
                name.endswith(('.pem', '.key', '.prv'))):
                raise ValueError('Sensitive/runtime archive entry: ' + name)
        manifest_path = next((n for n in entries if n.endswith('/RELEASE_MANIFEST.json')), None)
        if not manifest_path:
            raise ValueError('Missing manifest')
        manifest = json.loads(z.read(manifest_path))
        checksums = manifest.get('files_sha256') or {}
        root_prefix = manifest_path[:-len('RELEASE_MANIFEST.json')]
        if not checksums:
            raise ValueError('Manifest has no checksums')
        for rel, expected in checksums.items():
            data = z.read(root_prefix + rel)
            actual = hashlib.sha256(data).hexdigest()
            if actual != expected:
                raise ValueError('Checksum mismatch: ' + rel)
            if secret_findings(rel, data):
                raise ValueError('Potential credential in archive: ' + rel)
        if len(checksums) != len(entries)-1:
            raise ValueError('Unmanifested archive files present')
        return {'zip': str(path), 'status': 'pass', 'files_verified': len(checksums), 'release': manifest.get('release')}


def main():
    p = argparse.ArgumentParser()
    p.add_argument('zipfile')
    args = p.parse_args()
    try:
        print(json.dumps(verify(Path(args.zipfile)), indent=2))
    except (ValueError, zipfile.BadZipFile, OSError, KeyError) as exc:
        print('RELEASE VERIFICATION FAILED:', exc, file=sys.stderr)
        return 2
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
