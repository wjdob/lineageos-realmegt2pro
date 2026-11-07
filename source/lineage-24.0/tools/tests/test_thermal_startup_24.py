"""Check the observed native15 thermal packaging and service-name omissions."""
from pathlib import Path
import hashlib
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'build'))
from verify_vendor_24 import check_thermal_startup


class ThermalStartupTests(unittest.TestCase):
    def fixture(self, restart='vendor.thermal-hal', config=True, executable=True):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        path=Path(temp.name)/'target.zip'
        script=('service vendor.thermal-hal /vendor/bin/hw/android.hardware.thermal-service.qti\n'
                '    class hal\non boot\n    restart '+restart+'\n').encode()
        default=b'# Empty default; built-in target configuration remains selected.\n'
        with zipfile.ZipFile(path,'w') as archive:
            archive.writestr('VENDOR/etc/init/android.hardware.thermal-service.qti.rc',script)
            if config:archive.writestr('VENDOR/etc/thermal-engine.conf',default)
            if executable:archive.writestr('VENDOR/bin/hw/android.hardware.thermal-service.qti',b'executable')
        return path,hashlib.sha256(script).hexdigest(),hashlib.sha256(default).hexdigest()

    def test_consistent_service_and_config_pass(self):
        self.assertTrue(check_thermal_startup(*self.fixture())['thermal_startup_pass'])

    def test_native15_stale_service_name_fails_even_with_bound_script_hash(self):
        self.assertFalse(check_thermal_startup(*self.fixture(restart='android.thermal-hal'))['thermal_startup_pass'])

    def test_missing_default_file_fails(self):
        self.assertFalse(check_thermal_startup(*self.fixture(config=False))['thermal_startup_pass'])

    def test_missing_hal_executable_fails(self):
        self.assertFalse(check_thermal_startup(*self.fixture(executable=False))['thermal_startup_pass'])


if __name__=='__main__':unittest.main()
