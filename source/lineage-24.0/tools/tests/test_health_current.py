"""Reconstruct and exercise the reviewed health fix, including realistic regressions."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from health_current import REPO, SOURCE, check_source


@unittest.skipUnless(Path('/build/lineage/.repo').exists() and shutil.which('c++'),
                     'requires pinned WSL checkout and host compiler')
class HealthCurrentTests(unittest.TestCase):
    def setUp(self):
        recipe = json.loads((REPO/'tools/build/recipe-23.2.json').read_text())
        row = next(item for item in recipe['files'] if item['path'] == SOURCE)
        base = subprocess.check_output(['git', '-C', '/build/lineage/'+row['project'],
                                        'show', row['revision']+':'+row['relative']])
        self.assertEqual(hashlib.sha256(base).hexdigest(), row['base_sha256'])
        directory = tempfile.TemporaryDirectory(prefix='health-regression-', dir=REPO/'tmp')
        self.addCleanup(directory.cleanup)
        scratch = Path(directory.name)
        self.path = scratch/row['relative']
        self.path.parent.mkdir(parents=True)
        self.path.write_bytes(base)
        self.base = base
        patch = next(item for item in recipe['actions']
                     if item.get('file', '').endswith('0037-ferrari-health-current-units.patch'))
        data = (REPO/patch['file']).read_bytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(), patch['sha256'])
        subprocess.run(['patch', '--batch', '--fuzz=0', '-p1'], input=data,
                       cwd=scratch, check=True, capture_output=True)
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), row['canonical_sha256'])

    def test_actual_subclass_handles_both_paths_scope_and_invalid_input(self):
        self.assertEqual(check_source(self.path)['cases_passed'], 48)

    def test_original_hal_and_unused_fix_are_rejected(self):
        corrected = self.path.read_text()
        for contents in (self.base.decode(), corrected.replace('make<Rmx3301Health>', 'make<Health>')):
            self.path.write_text(contents)
            with self.assertRaises(ValueError):
                check_source(self.path)

    def test_wrong_scale_polarity_scope_and_one_path_only_are_rejected(self):
        corrected = self.path.read_text()
        mutations = [
            ('-1000LL * *value', '1000LL * *value'),
            ('-1000LL * *value', '-1LL * *value'),
            ('android::base::GetProperty("ro.boot.prjname", "") == "21631"', 'true'),
            ('if (!normalize_current_) return;', 'return;'),
            ('if (!status.isOk() || !normalize_current_) return status;', 'return status;'),
        ]
        for old, new in mutations:
            with self.subTest(regression=new):
                self.assertIn(old, corrected)
                self.path.write_text(corrected.replace(old, new))
                with self.assertRaises(ValueError):
                    check_source(self.path)


if __name__ == '__main__':
    unittest.main()
