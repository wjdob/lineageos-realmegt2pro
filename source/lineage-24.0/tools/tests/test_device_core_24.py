"""Compile real RRO fixtures and catch the observed profile/geometry omissions.

Run with AAPT2_FOR_TESTS and ANDROID_JAR_FOR_TESTS pointing at the reviewed
native tool/current SDK. Unavailable native integration checks are skipped.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO/'tools'))
from device_core_24 import check_package

AAPT2 = os.environ.get('AAPT2_FOR_TESTS')
ANDROID_JAR = os.environ.get('ANDROID_JAR_FOR_TESTS')


@unittest.skipUnless(AAPT2 and ANDROID_JAR, 'requires native aapt2 and current SDK integration inputs')
class DeviceCorePackageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.work = Path(cls.temporary.name)
        cls.contract = json.loads((REPO/'configs/device-core-24.0.json').read_text())
        cls.profile = (REPO/'overlays/lineage-24.0/ferrari/media/media_profiles_V1_0.xml').read_bytes()
        cls.apks = {}
        for name, family, target in (
                ('OPlusFrameworksResTarget', 'framework', 'android'),
                ('OPlusSystemUIResTarget', 'systemui', 'com.android.systemui')):
            cls.apks[name+'.apk'] = cls.compile_overlay(name, family, target)
        cls.bad_qhd = cls.compile_overlay('OPlusSystemUIResTarget', 'systemui', 'com.android.systemui', bad_qhd=True)

    @classmethod
    def compile_overlay(cls, name, family, target, bad_qhd=False):
        work = cls.work/(name+('-bad' if bad_qhd else '-good'))
        work.mkdir()
        resources = work/'res'
        for mode in ('values-port-2412x1080', 'values-port-3216x1440'):
            directory = resources/mode
            directory.mkdir(parents=True)
            data = (REPO/'overlays/lineage-24.0/ferrari'/family/mode/'dimens.xml').read_text()
            if bad_qhd and mode == 'values-port-3216x1440':
                if '>166px<' not in data:
                    raise AssertionError('expected QHD row fixture absent')
                data = data.replace('>166px<', '>125px<')
            (directory/'dimens.xml').write_text(data)
        manifest = work/'AndroidManifest.xml'
        manifest.write_text('<manifest xmlns:android="http://schemas.android.com/apk/res/android" '
                            'package="test.overlay.'+family+'"><overlay android:isStatic="true" '
                            'android:targetPackage="'+target+'" /></manifest>')
        flat, apk = work/'compiled.zip', work/'overlay.apk'
        subprocess.run([AAPT2, 'compile', '--dir', str(resources), '-o', str(flat)],
                       check=True, capture_output=True)
        subprocess.run([AAPT2, 'link', '--manifest', str(manifest), '-I', ANDROID_JAR,
                        '-o', str(apk), str(flat)], check=True, capture_output=True)
        return apk.read_bytes()

    def fixture(self, *, omit_profile=False, shadow_profile=False, variant=None,
                bad_profile=False, bad_qhd=False, omit_overlay=False):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        directory = Path(temporary.name)
        package = directory/'target.zip'
        with zipfile.ZipFile(package, 'w') as archive:
            if not omit_profile:
                archive.writestr(self.contract['profile']['member'],
                                 self.profile+b'\n' if bad_profile else self.profile)
            if shadow_profile:
                archive.writestr('PRODUCT/etc/media_profiles_V1_0.xml', '<MediaSettings/>')
            if variant:
                archive.writestr('SYSTEM/build.prop', 'ro.media.xml_variant.profiles='+variant+'\n')
            for name, data in self.apks.items():
                if omit_overlay and name == 'OPlusSystemUIResTarget.apk':
                    continue
                if bad_qhd and name == 'OPlusSystemUIResTarget.apk':
                    data = self.bad_qhd
                archive.writestr('ODM/overlay/'+name, data)
        return package, directory

    def result(self, **kwargs):
        package, scratch = self.fixture(**kwargs)
        return check_package(package, self.contract, AAPT2, scratch)

    def test_native_compiled_geometry_and_selected_profile_pass(self):
        result = self.result()
        self.assertTrue(result['device_core_pass'], result['issues'])
        self.assertEqual(len(result['overlays']), 2)

    def test_fhd_height_reused_at_qhd_is_rejected(self):
        result = self.result(bad_qhd=True)
        self.assertFalse(result['device_core_pass'])
        self.assertTrue(any('compiled dimension differs' in value for value in result['issues']))

    def test_missing_profile_rejects_camera0_fallback(self):
        self.assertFalse(self.result(omit_profile=True)['device_core_pass'])

    def test_earlier_product_profile_cannot_silently_preempt_device(self):
        self.assertFalse(self.result(shadow_profile=True)['device_core_pass'])

    def test_variant_that_ignores_reviewed_profile_is_rejected(self):
        self.assertFalse(self.result(variant='_unreviewed')['device_core_pass'])

    def test_changed_profile_or_missing_overlay_is_rejected(self):
        self.assertFalse(self.result(bad_profile=True)['device_core_pass'])
        self.assertFalse(self.result(omit_overlay=True)['device_core_pass'])


if __name__ == '__main__':
    unittest.main()
