import sys
from pathlib import Path
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'build'))
from vendor_ownership_24 import NAMES, select_ferrari


class OwnershipTests(unittest.TestCase):
    def fixture(self):
        bp=''.join('cc_library_shared {\n    name: "'+name+'",\n}\n' for name in sorted(NAMES))
        bp+='cc_library_shared {\n    name: "unrelated",\n    shared_libs: ["libcvp2_1", "libcamera2ndk_vendor"],\n}\n'
        mk='PRODUCT_PACKAGES += \\\n'+''.join('    '+name+' \\\n' for name in sorted(NAMES-{'libstfaceunlockocl'}))+'    unrelated\n'
        mk+='PRODUCT_COPY_FILES += \\\n    vendor/common/a:$(TARGET_COPY_OUT_VENDOR)/same \\\n    vendor/common/b:$(TARGET_COPY_OUT_VENDOR)/other\n'
        ferrari='PRODUCT_COPY_FILES += \\\n    vendor/realme/ferrari/a:$(TARGET_COPY_OUT_VENDOR)/same\n'
        return bp,mk,ferrari

    def test_common_consumers_resolve_exact_ferrari_provider(self):
        bp,mk,report=select_ferrari(*self.fixture())
        for name in NAMES:
            self.assertNotIn('name: "'+name+'"',bp)
        self.assertIn('"//vendor/realme/ferrari:libcvp2_1"',bp)
        self.assertIn('"//vendor/realme/ferrari:libcamera2ndk_realme"',bp)
        self.assertNotIn('"//vendor/realme/ferrari:libcamera2ndk_vendor"',bp)
        self.assertIn('name: "unrelated"',bp)
        self.assertNotIn('vendor/common/a:',mk)
        self.assertIn('vendor/common/b:',mk)
        self.assertEqual(report['copy_destinations'],['$(TARGET_COPY_OUT_VENDOR)/same'])

    def test_changed_common_provider_set_is_refused(self):
        bp,mk,ferrari=self.fixture()
        with self.assertRaisesRegex(ValueError,'provider set changed'):
            select_ferrari(bp.replace('name: "libcvp2_1"','name: "unexpected"'),mk,ferrari)

    def test_fresh_extraction_already_names_the_distinct_oem_library(self):
        bp,mk,ferrari=self.fixture()
        bp=bp.replace('["libcvp2_1", "libcamera2ndk_vendor"]','["libcvp2_1", "libcamera2ndk_realme"]')
        result,_,_=select_ferrari(bp,mk,ferrari)
        self.assertIn('"//vendor/realme/ferrari:libcamera2ndk_realme"',result)
        self.assertNotIn('"libcamera2ndk_realme"',result)

    def test_masc_skip_removed_without_changing_an_unrelated_module(self):
        bp,mk,ferrari=self.fixture()
        bp+='cc_prebuilt_library_shared {\n    name: "libmasc",\n    check_elf_files: false,\n}\n'
        bp+='cc_prebuilt_library_shared {\n    name: "unrelated_skip",\n    check_elf_files: false,\n}\n'
        result,_,_=select_ferrari(bp,mk,ferrari)
        self.assertIn('name: "libmasc",\n}',result)
        self.assertIn('name: "unrelated_skip",\n    check_elf_files: false,',result)

    def test_fresh_masc_metadata_keeps_standard_validation(self):
        bp,mk,ferrari=self.fixture()
        enabled='cc_prebuilt_library_shared {\n    name: "libmasc",\n}\n'
        result,_,_=select_ferrari(bp+enabled,mk,ferrari)
        self.assertIn(enabled,result)


if __name__=='__main__':
    unittest.main()
