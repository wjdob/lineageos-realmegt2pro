"""Exercise collection when vendor_boot exists only in target-files."""
from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'build'))
from run_candidate_24 import required_artifacts
from run_build import execute


class ArtifactCollection(unittest.TestCase):
    def setUp(self):
        directory = Path(__file__).resolve().parents[2]/'tmp'
        directory.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='candidate-artifacts24-', dir=directory)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def collect(self, omit=None, target='otapackage'):
        paths = required_artifacts(target)
        script = self.root/'build.py'
        script.write_text('''from pathlib import Path
import sys,zipfile
for name in sys.argv[1:]:
    path=Path(name);path.parent.mkdir(parents=True,exist_ok=True)
    if path.suffix=='.zip':
        with zipfile.ZipFile(path,'w') as archive:
            archive.writestr('IMAGES/vendor_boot.img',b'VNDRBOOT-packaged-fixture')
    else:path.write_bytes(b'current-build-fixture')
''')
        command = [sys.executable, str(script), *[path for path in paths if not path.endswith(omit or '/never')]]
        return execute(command, self.root, paths, self.root/'records', min_free=0,
                       space_path=self.root, poll=.01)

    def test_packaged_vendor_boot_without_loose_image_collects(self):
        result = self.collect()
        self.assertEqual(result['state'], 'success', result)
        self.assertEqual(len(result['artifacts']), 7)
        self.assertFalse((self.root/'out/target/product/ferrari/vendor_boot.img').exists())
        target = next(row for row in result['artifacts'] if row['path'].endswith('/lineage_ferrari-target_files.zip'))
        with zipfile.ZipFile(target['collected']) as archive:
            self.assertTrue(archive.read('IMAGES/vendor_boot.img').startswith(b'VNDRBOOT'))

    def test_missing_target_files_remains_failure(self):
        result = self.collect(omit='lineage_ferrari-target_files.zip')
        self.assertEqual(result['state'], 'failed')
        self.assertIn('missing/empty output', result['error'])

    def test_missing_recovery_remains_failure(self):
        result = self.collect(omit='recovery.img')
        self.assertEqual(result['state'], 'failed')
        self.assertIn('missing/empty output', result['error'])

    def test_other_targets_remain_scoped(self):
        self.assertEqual(required_artifacts('nothing'), [])
        self.assertEqual(required_artifacts('check-elf-files'), [])
        self.assertEqual(required_artifacts('codec2-provider'),
                         ['out/target/product/ferrari/vendor/lib64/libcodec2_hidl@1.0.so'])
        with self.assertRaises(ValueError):
            required_artifacts('arbitrary-path')

    def test_first_stage_probe_collects_actual_binary(self):
        result = self.collect(target='init-diagnostic')
        self.assertEqual(result['state'], 'success', result)
        self.assertEqual(len(result['artifacts']), 2)
        self.assertTrue(result['artifacts'][0]['path'].endswith('/ramdisk/init'))

    def test_missing_second_stage_probe_fails(self):
        result = self.collect(omit='system/bin/init', target='init-diagnostic')
        self.assertEqual(result['state'], 'failed', result)
        self.assertIn('missing/empty output', result['error'])

    def test_other_init_binary_path_is_refused_before_command(self):
        result = execute([sys.executable, '-c', "from pathlib import Path;Path('started').touch()"],
                         self.root, ['out/target/product/ferrari/ramdisk/init-other'],
                         self.root/'records', min_free=0, space_path=self.root, poll=.01)
        self.assertEqual(result['state'], 'failed', result)
        self.assertFalse((self.root/'started').exists())


if __name__ == '__main__':
    unittest.main()
