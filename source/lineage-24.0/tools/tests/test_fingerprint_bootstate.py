"""Exercise the real pinned vendor init implementation, including unsafe regressions."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fingerprint_bootstate import REPO, SOURCE, check_source


@unittest.skipUnless(Path('/build/lineage/.repo').exists() and shutil.which('c++'),
                     'requires pinned WSL source checkout and host C++ compiler')
class FingerprintBootstateTests(unittest.TestCase):
    def setUp(self):
        recipe = json.loads((REPO/'tools/build/recipe-23.2.json').read_text())
        row = next(item for item in recipe['files'] if item['path'] == SOURCE)
        base = subprocess.check_output(['git', '-C', '/build/lineage/'+row['project'],
                                        'show', row['revision']+':'+row['relative']])
        self.assertEqual(hashlib.sha256(base).hexdigest(), row['base_sha256'])
        self.directory = tempfile.TemporaryDirectory(prefix='bootstate-regression-', dir=REPO/'tmp')
        self.addCleanup(self.directory.cleanup)
        self.scratch = Path(self.directory.name)
        self.path = self.scratch/row['relative']
        self.path.parent.mkdir(parents=True)
        self.path.write_bytes(base)
        self.base = base
        patch = next(item for item in recipe['actions']
                     if item.get('file', '').endswith('0036-ferrari-report-missing-bootloader-state.patch'))
        data = (REPO/patch['file']).read_bytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(), patch['sha256'])
        subprocess.run(['patch', '--batch', '--fuzz=0', '-p1'], input=data,
                       cwd=self.scratch, capture_output=True, check=True)
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), row['canonical_sha256'])

    def test_real_corrected_source_passes_nineteen_state_cases(self):
        self.assertEqual(check_source(self.path)['cases_passed'], 19)

    def test_original_source_reproduces_the_missing_state_failure(self):
        self.path.write_bytes(self.base)
        with self.assertRaisesRegex(ValueError, 'behavioral guard failed'):
            check_source(self.path)

    def test_regressions_cannot_change_other_devices_or_supplied_or_nonorange_state(self):
        corrected = self.path.read_text()
        for expression in (
                'prjname == 21631',
                'GetProperty("ro.boot.vbmeta.device_state", "").empty()',
                'GetProperty("ro.boot.verifiedbootstate", "") == "orange"'):
            with self.subTest(removed_guard=expression):
                self.assertEqual(corrected.count(expression), 1)
                self.path.write_text(corrected.replace(expression, 'true'))
                with self.assertRaisesRegex(ValueError, 'behavioral guard failed'):
                    check_source(self.path)


if __name__ == '__main__':
    unittest.main()
