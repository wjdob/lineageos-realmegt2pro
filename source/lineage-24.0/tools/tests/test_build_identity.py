from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from build_identity import METADATA, check, make_identity, validate_identity


class BuildIdentityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.identity = make_identity('candidate-fixture-11', 1793136000,
                                      {'post-timestamp': '1793075648',
                                       'post-build-incremental': '1793075648'})

    def archives(self, *, timestamp=None, incremental=None, stale_system=False):
        timestamp = str(self.identity['build_datetime']) if timestamp is None else timestamp
        incremental = self.identity['build_number'] if incremental is None else incremental
        ota, target = self.root / 'ota.zip', self.root / 'target.zip'
        with zipfile.ZipFile(ota, 'w') as archive:
            archive.writestr(METADATA, 'post-timestamp=' + timestamp +
                             '\npost-build-incremental=' + incremental + '\n')
        if stale_system:
            timestamp, incremental = '1793075648', '1793075648'
        with zipfile.ZipFile(target, 'w') as archive:
            archive.writestr('SYSTEM/build.prop',
                'ro.build.date.utc=' + timestamp + '\nro.system.build.date.utc=' + timestamp +
                '\nro.build.version.incremental=' + incremental +
                '\nro.system.build.version.incremental=' + incremental + '\n')
        return ota, target

    def test_distinct_runs_in_same_second_change_normal_build_dependency(self):
        other = make_identity('candidate-fixture-12', self.identity['build_datetime'])
        self.assertNotEqual(other['build_number'], self.identity['build_number'])
        self.assertFalse(self.identity['build_number'].startswith('eng.'))
        self.assertEqual(validate_identity(self.identity)['build_number'], self.identity['build_number'])

    def test_current_clock_must_advance_previous_without_clamping(self):
        for timestamp in (1793075647, 1793075648):
            with self.assertRaisesRegex(ValueError, 'does not advance'):
                make_identity('candidate-fixture', timestamp, {'post-timestamp': '1793075648'})

    def test_invalid_run_epoch_and_previous_timestamp_fail(self):
        for run in ('candidate-name;id', 'other-name', 'candidate-a\n'):
            with self.assertRaises(ValueError):
                make_identity(run, 1793136000)
        for timestamp in (True, '1793136000', 0, -1, 2**32):
            with self.assertRaises(ValueError):
                make_identity('candidate-fixture', timestamp)
        with self.assertRaises(ValueError):
            make_identity('candidate-fixture', 1793136000, {'post-timestamp': 'bad'})

    def test_fresh_metadata_and_actual_system_properties_pass(self):
        self.assertTrue(check(*self.archives(), self.identity)['pass'])

    def test_cached_09b_10b_identity_fails_even_with_valid_zip(self):
        with self.assertRaisesRegex(ValueError, 'cached properties'):
            check(*self.archives(timestamp='1793075648', incremental='1793075648'), self.identity)

    def test_fresh_ota_metadata_cannot_hide_stale_system_image_properties(self):
        with self.assertRaisesRegex(ValueError, 'system properties'):
            check(*self.archives(stale_system=True), self.identity)

    def test_timestamp_and_incremental_each_must_match(self):
        for kwargs in ({'timestamp': '1793136001'}, {'incremental': 'other-run'}):
            with self.assertRaises(ValueError):
                check(*self.archives(**kwargs), self.identity)

    def test_changed_run_binding_is_rejected(self):
        changed = dict(self.identity, run='candidate-other-run')
        with self.assertRaisesRegex(ValueError, 'binding differs'):
            check(*self.archives(), changed)

    def test_duplicate_metadata_identity_field_is_rejected(self):
        ota, target = self.archives()
        with zipfile.ZipFile(ota, 'w') as archive:
            archive.writestr(METADATA, 'post-timestamp=1\npost-timestamp=2\npost-build-incremental=x\n')
        with self.assertRaisesRegex(ValueError, 'duplicate identity'):
            check(ota, target, self.identity)

    def test_missing_system_property_is_rejected(self):
        ota, target = self.archives()
        with zipfile.ZipFile(target, 'w') as archive:
            archive.writestr('SYSTEM/build.prop', 'ro.build.date.utc=1793136000\n')
        with self.assertRaisesRegex(ValueError, 'system properties'):
            check(ota, target, self.identity)

    @unittest.skipUnless(shutil.which('bash'), 'Bash is required to verify build environment transport')
    def test_real_wrapper_exports_recorded_values_before_build(self):
        (self.root / '.realme-next-isolated.json').write_text('{}')
        release = self.root / 'vendor/lineage/vars/aosp_target_release'
        release.parent.mkdir(parents=True)
        release.write_text('aosp_target_release=bp4a\n')
        env = self.root / 'build/envsetup.sh'
        env.parent.mkdir()
        env.write_text('m() { printf "%s\\n%s\\n" "$BUILD_NUMBER" "$BUILD_DATETIME" > observed-env; }\n')
        wrapper = Path(__file__).resolve().parents[1] / 'build/build_candidate.sh'
        command = ['bash', str(wrapper), 'nothing', '1', 'unused',
                   self.identity['build_number'], str(self.identity['build_datetime']), 'inputs.json']
        subprocess.run(command, cwd=self.root, check=True, capture_output=True)
        self.assertEqual((self.root / 'observed-env').read_text().splitlines(),
                         [self.identity['build_number'], str(self.identity['build_datetime'])])
        (self.root / 'observed-env').unlink()
        command[-2] = '1793136001'
        self.assertNotEqual(subprocess.run(command, cwd=self.root, capture_output=True).returncode, 0)
        self.assertFalse((self.root / 'observed-env').exists())
