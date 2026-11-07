from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from vendor_fixup_binding import package_member


class MappingTests(unittest.TestCase):
    def test_common_and_device_files_map_to_exact_partitions(self):
        self.assertEqual(package_member('vendor/oneplus/sm8450-common/proprietary/system_ext/bin/horae'),'SYSTEM_EXT/bin/horae')
        self.assertEqual(package_member('vendor/realme/ferrari/proprietary/odm/lib64/libextensionlayer.so'),'ODM/lib64/libextensionlayer.so')

    def test_unreviewed_project_and_escape_do_not_map_to_installed_file(self):
        for path in ('vendor/other/device/proprietary/vendor/lib64/libx.so',
                     'vendor/realme/ferrari/proprietary/vendor/../../ROOT/init',
                     'vendor/realme/ferrari/proprietary/vendor\\lib64\\libx.so'):
            with self.subTest(path=path),self.assertRaises(ValueError):package_member(path)


if __name__=='__main__':unittest.main()
