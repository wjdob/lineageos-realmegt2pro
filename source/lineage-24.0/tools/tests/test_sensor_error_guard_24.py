"""Reject omitted, stale and redirected sensor objects at the package boundary."""
from pathlib import Path
import hashlib,stat,sys,tempfile,unittest,warnings,zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'build'))
from verify_vendor_24 import check_sensor_error_guard, SENSOR_MEMBER

class SensorErrorGuardPackage(unittest.TestCase):
    @staticmethod
    def sensor_fixture(streaming=False, guard=True, stale_id=False):
        data=bytearray(860144)
        data[:6]=b'\x7fELF\x02\x01'
        data[18:20]=b'\xb7\x00'
        data[0x61004:0x61014]=bytes.fromhex('21581491e00315aa09990194'+('60080034' if streaming else '1f2003d5'))
        if guard:
            data[0xa6bdc:0xa6be4]=bytes.fromhex('3f2303d508860014')
            data[0xc8400:0xc841c]=bytes.fromhex('282840b91f09027160000054ff8304d1f579ff17bf2303d5c0035fd6')
        data[0x308:0x318]=bytes(16) if stale_id else hashlib.sha256(data).digest()[:16]
        return bytes(data)

    def setUp(self):
        self.expected=self.sensor_fixture()

    def package(self,data=None,omit=False,symlink=False,duplicate=False):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        path=Path(temp.name)/'target.zip'
        with zipfile.ZipFile(path,'w') as archive:
            if not omit:
                info=zipfile.ZipInfo(SENSOR_MEMBER)
                info.external_attr=(stat.S_IFLNK|0o777)<<16 if symlink else (stat.S_IFREG|0o644)<<16
                archive.writestr(info,self.expected if data is None else data)
                if duplicate:
                    with warnings.catch_warnings():
                        warnings.simplefilter('ignore',UserWarning)
                        archive.writestr(SENSOR_MEMBER,self.expected)
        return path

    def check(self,path):
        return check_sensor_error_guard(path,hashlib.sha256(self.expected).hexdigest())

    def test_exact_qualified_object(self):
        self.assertTrue(self.check(self.package())['sensor_error_guard_pass'])

    def test_old_unguarded_object(self):
        self.assertFalse(self.check(self.package(data=b'old unguarded sensor'))['sensor_error_guard_pass'])

    def test_missing_object(self):
        self.assertFalse(self.check(self.package(omit=True))['sensor_error_guard_pass'])

    def test_empty_object(self):
        self.assertFalse(self.check(self.package(data=b''))['sensor_error_guard_pass'])

    def test_symlink_cannot_impersonate_qualified_object(self):
        self.assertFalse(self.check(self.package(symlink=True))['sensor_error_guard_pass'])

    def test_duplicate_member_rejected(self):
        with self.assertRaisesRegex(ValueError,'duplicate'):
            self.check(self.package(duplicate=True))

    def test_missing_source_identity_rejected(self):
        with self.assertRaises(ValueError):
            check_sensor_error_guard(self.package(),'')

    def test_guard_only_rejected_even_with_its_own_same_run_hash(self):
        data=self.sensor_fixture(streaming=True)
        result=check_sensor_error_guard(self.package(data=data),hashlib.sha256(data).hexdigest())
        self.assertIn('lux_aod on-change request correction is missing',result['issues'])

    def test_request_fix_alone_rejected_even_with_its_own_hash(self):
        data=self.sensor_fixture(guard=False)
        result=check_sensor_error_guard(self.package(data=data),hashlib.sha256(data).hexdigest())
        self.assertIn('OEM sensor error-event parser defense is missing',result['issues'])

    def test_stale_combined_build_id_rejected_even_with_its_own_hash(self):
        data=self.sensor_fixture(stale_id=True)
        result=check_sensor_error_guard(self.package(data=data),hashlib.sha256(data).hexdigest())
        self.assertIn('OEM sensor combined diagnostic build identity is stale',result['issues'])

if __name__=='__main__':unittest.main()
