"""Exercise the release workflow's shell gates without publishing to GitHub."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


WORKFLOW = Path(__file__).resolve().parents[1] / '.github/workflows/desktop-cross-platform.yml'


def workflow_script(step_name):
    lines = WORKFLOW.read_text().splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == f'- name: {step_name}')
    start = next(i for i in range(start, len(lines)) if lines[i].strip() == 'run: |') + 1
    end = start
    while end < len(lines) and (not lines[end].strip() or lines[end].startswith('          ')):
        end += 1
    return '\n'.join(line[10:] for line in lines[start:end]) + '\n'


class DesktopReleaseWorkflowTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = dict(os.environ, GITHUB_OUTPUT=str(self.root / 'output'))

    def run_script(self, name, **env):
        return subprocess.run(['bash', '-c', workflow_script(name)], cwd=self.root,
                              env=dict(self.env, **env), capture_output=True, text=True)

    def git(self, *args):
        return subprocess.check_output(['git', *args], cwd=self.root, stderr=subprocess.DEVNULL, text=True).strip()

    def init_branches(self):
        self.git('init', '-b', 'main')
        self.git('config', 'user.email', 'test@example.org')
        self.git('config', 'user.name', 'Release Test')
        self.git('commit', '--allow-empty', '-m', 'base')
        self.git('update-ref', 'refs/remotes/origin/main', 'HEAD')
        self.git('checkout', '-b', 'beta')
        self.git('commit', '--allow-empty', '-m', 'A/B variant')
        self.git('update-ref', 'refs/remotes/origin/beta', 'HEAD')

    def test_channel_and_ancestry(self):
        self.init_branches()
        name = 'Validate release tag and source branch'
        result = self.run_script(name, RELEASE_TAG='v0.3.0-beta-test.1')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.root / 'output').read_text(), 'version=0.3.0-beta-test.1\nprerelease=true\n')
        self.assertNotEqual(self.run_script(name, RELEASE_TAG='v0.3.0').returncode, 0)
        self.git('checkout', 'main')
        (self.root / 'output').write_text('')
        result = self.run_script(name, RELEASE_TAG='v0.2.0')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.root / 'output').read_text(), 'version=0.2.0\nprerelease=false\n')

    def test_reject_malformed_tags(self):
        name = 'Validate release tag and source branch'
        for tag in ['v0.3.0-beta.1', 'v01.2.3', 'v1.2.3-beta-test.0', 'v1.2', 'v1.2.3; echo injected']:
            with self.subTest(tag=tag):
                result = self.run_script(name, RELEASE_TAG=tag)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('Expected vX.Y.Z', result.stderr)

    def prepare_publish(self):
        assets = self.root / 'built-installers'
        assets.mkdir()
        (assets / 'ResearcherOS Setup 0.3.0.exe').write_bytes(b'windows')
        (assets / 'ResearcherOS-0.3.0.AppImage').write_bytes(b'linux')
        bin_dir = self.root / 'bin'
        bin_dir.mkdir()
        gh = bin_dir / 'gh'
        gh.write_text('#!/usr/bin/env python3\nimport json, pathlib, sys\npathlib.Path("gh-args.json").write_text(json.dumps(sys.argv[1:]))\n')
        gh.chmod(0o755)
        self.env['PATH'] = str(bin_dir) + os.pathsep + self.env['PATH']
        self.env.update(SOURCE_SHA='abc123', BUILD_RUN_URL='https://example.org/build/1')

    def test_publish_flags_checksums_and_provenance(self):
        self.prepare_publish()
        for prerelease, tag in [('true', 'v0.3.0-beta-test.1'), ('false', 'v0.3.0')]:
            with self.subTest(prerelease=prerelease):
                result = self.run_script('Publish verified installers to GitHub Releases',
                                         PRERELEASE=prerelease, RELEASE_TAG=tag)
                self.assertEqual(result.returncode, 0, result.stderr)
                args = json.loads((self.root / 'gh-args.json').read_text())
                self.assertEqual(args[:3], ['release', 'create', tag])
                self.assertIn('--verify-tag', args)
                self.assertEqual('--prerelease' in args, prerelease == 'true')
                self.assertEqual('--latest=false' in args, prerelease == 'true')
                self.assertIn('built-installers/ResearcherOS Setup 0.3.0.exe', args)
                notes = (self.root / 'release-notes.md').read_text()
                self.assertIn('abc123', notes)
                self.assertIn('https://example.org/build/1', notes)
                assets = self.root / 'built-installers'
                for line in (assets / 'SHA256SUMS.txt').read_text().splitlines():
                    digest, filename = line.split('  ', 1)
                    self.assertEqual(digest, hashlib.sha256((assets / filename).read_bytes()).hexdigest())

    def test_missing_platform_prevents_publication(self):
        self.prepare_publish()
        (self.root / 'built-installers/ResearcherOS-0.3.0.AppImage').unlink()
        result = self.run_script('Publish verified installers to GitHub Releases',
                                 PRERELEASE='false', RELEASE_TAG='v0.3.0')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root / 'gh-args.json').exists())


if __name__ == '__main__':
    unittest.main()
