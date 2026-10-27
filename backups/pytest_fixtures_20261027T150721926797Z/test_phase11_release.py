import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from phase11_release import build_archive, include_file, secret_findings
from phase11_verify_zip import verify
from phase11_regression import run


class Phase11ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.add('backend/app/main.py', '# Sample backend\n')
        self.add('agent/server.py', '# Sample GPU agent\n')
        self.add('frontend/package.json', '{"name":"demo"}\n')
        self.add('frontend/src/app/page.tsx', 'export default function Page(){return null}\n')
        self.add('docker-compose.yml', 'services: {}\n')
        self.add('README.md', '# Legacy\n')
        self.add('docs/phase11/RELEASE_README.md', '# Release readme\n')
        self.add('.env.example', 'MISSION_AGENT_TOKEN=\n')
        self.add('results/mi300x/v2_test/summary.json', '{"source":"real_vllm"}\n')
        self.add('backups/old.py', 'SECRET\n')
        self.add('node_modules/foo.js', 'pkg\n')
        self.add('.env', 'MISSION_AGENT_TOKEN=should_never_enter_archive\n')

    def add(self, name, content):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf8')

    def test_no_sensitive_filenames_packaged(self):
        outfile = self.root / 'dist' / 'candidate.zip'
        result = build_archive(self.root, outfile, 'v1.0.0-rc1')
        self.assertGreater(result['file_count'], 4)
        with ZipFile(outfile) as z:
            names = z.namelist()
            self.assertFalse(any('/results/' in name for name in names))
            self.assertFalse(any('/backups/' in name for name in names))
            self.assertFalse(any('node_modules' in name for name in names))
            self.assertFalse(any(name.endswith('/.env') for name in names))
            self.assertTrue(any(name.endswith('/.env.example') for name in names))
            self.assertEqual(z.read('AMD-AI-Factory-Mission-Control-v1.0.0-rc1/README.md'), b'# Release readme\n')
            self.assertEqual(z.read('AMD-AI-Factory-Mission-Control-v1.0.0-rc1/docs/phase11/ORIGINAL_README.md'), b'# Legacy\n')

    def test_manifest_and_sha_file(self):
        outfile = self.root / 'dist' / 'candidate.zip'
        build_archive(self.root, outfile, 'v1.0.0-rc1')
        report = verify(outfile)
        self.assertEqual(report['status'], 'pass')
        self.assertTrue(outfile.with_suffix('.zip.sha256').exists())

    def test_dry_run_no_zip_created(self):
        dest = self.root / 'dist' / 'never.zip'
        result = build_archive(self.root, dest, 'v1.0.0-rc1', dry_run=True)
        self.assertTrue(result['dry_run'])
        self.assertFalse(dest.exists())

    def test_nonempty_agent_token_blocks_release(self):
        self.add('.env.example', 'MISSION_AGENT_TOKEN=placeholder_is_still_nonempty\n')
        with self.assertRaisesRegex(RuntimeError, 'POTENTIAL SECRET'):
            build_archive(self.root, self.root/'dist'/'bad.zip', 'v1.0.0-rc1')

    def test_git_token_detection(self):
        self.add('frontend/bad.ts', 'const key = "' + 'ghp_' + ('X'*30) + '";\n')
        with self.assertRaisesRegex(RuntimeError, 'POTENTIAL SECRET'):
            build_archive(self.root, self.root/'dist'/'bad.zip', 'v1.0.0-rc1')

    def test_reject_missing_app_files(self):
        (self.root/'backend/app/main.py').unlink()
        with self.assertRaisesRegex(RuntimeError, 'missing'):
            build_archive(self.root, self.root/'dist'/'bad.zip', 'v1.0.0-rc1')

    def test_reject_symlinks_and_private_keys(self):
        self.add('agent/ssh.pem', 'private\n')
        self.add('backend/personal.key', 'private\n')
        self.assertFalse(include_file(Path('agent/ssh.pem'), 2_000_000, self.root))
        self.assertFalse(include_file(Path('backend/personal.key'), 2_000_000, self.root))

    def test_curated_aggregate_evidence_allowed(self):
        self.add('docs/phase11/evidence/aggregate.csv', 'jobs,completed\n8,8\n')
        archive = self.root / 'dist' / 'ok.zip'
        build_archive(self.root, archive, 'v1.0.0-rc1')
        with ZipFile(archive) as z:
            self.assertTrue(any(x.endswith('/docs/phase11/evidence/aggregate.csv') for x in z.namelist()))

    def test_regression_read_only_offline(self):
        result = run(self.root, 'http://127.0.0.1:8000', 'http://127.0.0.1:3000', offline=True, compose=False)
        self.assertIn(result['status'], {'pass_with_warnings','pass'})
        self.assertFalse(any(c['status'] == 'FAIL' for c in result['checks']))

    def test_literal_private_key_scanner(self):
        text = '-----BEGIN ' + 'PRIVATE KEY-----\nsecret\n'
        self.assertTrue(secret_findings('file.py', text.encode()))


if __name__ == '__main__':
    unittest.main()
