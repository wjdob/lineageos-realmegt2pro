"""Verify historical audit bytes survive Git without relaxing real whitespace checks."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
GIT = shutil.which('git')


@unittest.skipUnless(GIT, 'Git unavailable; attribute behavior checks blocked')
class AuditAttributesTests(unittest.TestCase):
    def check(self, content, *, path='docs/AUDIT.md', autocrlf='true'):
        scratch = ROOT/'tmp/audit-attribute-tests'
        scratch.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as name:
            root = Path(name)
            args = [GIT, '-C', str(root), '-c', 'core.autocrlf='+autocrlf]
            subprocess.run([*args, 'init', '--quiet'], check=True, capture_output=True)
            shutil.copyfile(ROOT/'.gitattributes', root/'.gitattributes')
            target = root/path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            subprocess.run([*args, 'add', '--', path], check=True, capture_output=True)
            staged = subprocess.check_output([*args, 'show', ':'+path])
            result = subprocess.run([*args, 'diff', '--cached', '--no-ext-diff', '--check', '--', path],
                                    capture_output=True)
            return staged, result

    def test_mixed_line_endings_and_non_utf8_history_stay_byte_exact(self):
        content = b'historical prefix\xff\nnew historical line\r\nlast line\n'
        for autocrlf in ['true', 'false']:
            with self.subTest(autocrlf=autocrlf):
                staged, result = self.check(content, autocrlf=autocrlf)
                self.assertEqual(staged, content)
                self.assertEqual(result.returncode, 0, result.stdout+result.stderr)

    def test_real_trailing_space_before_crlf_is_still_rejected(self):
        staged, result = self.check(b'historical\ntrailing space \r\n')
        self.assertEqual(staged, b'historical\ntrailing space \r\n')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b'trailing whitespace', result.stdout)

    def test_ordinary_source_file_whitespace_checks_remain_enabled(self):
        _, result = self.check(b'value = 1 \n', path='normal.py')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b'trailing whitespace', result.stdout)


if __name__ == '__main__':
    unittest.main()
