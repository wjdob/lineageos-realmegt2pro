import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'build'))
from verify_vendor_24 import check,member


class VendorPackageTests(unittest.TestCase):
    def fixture(self, actual=b'prepared', symlink=False):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        package=Path(temp.name)/'target.zip'
        with zipfile.ZipFile(package,'w') as archive:
            info=zipfile.ZipInfo('ODM/lib64/libcamera.so')
            info.external_attr=(0o120777 if symlink else 0o100644)<<16
            archive.writestr(info,actual)
            archive.writestr('VENDOR/lib64/libtinyxml2-v34.so',b'versioned provider')
        rows=[dict(path='proprietary/odm/lib64/libcamera.so',bytes=8,
                   sha256=hashlib.sha256(b'prepared').hexdigest())]
        return package,rows

    def test_exact_selected_vendor_bytes_pass(self):
        self.assertTrue(check(*self.fixture())['vendor_package_pass'])

    def test_wrong_selected_provider_fails(self):
        result=check(*self.fixture(b'wrong'))
        self.assertFalse(result['vendor_package_pass'])
        self.assertIn('differs',result['issues'][0])

    def test_symlink_cannot_substitute_for_verified_blob(self):
        self.assertFalse(check(*self.fixture(symlink=True))['vendor_package_pass'])

    def test_escaping_package_mapping_refused(self):
        with self.assertRaises(ValueError):member('proprietary/odm/../../elsewhere')


if __name__=='__main__':
    unittest.main()
