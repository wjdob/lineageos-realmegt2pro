from pathlib import Path
import hashlib
import json
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from candidate_sensors import inspect, main, REQUIRED, RC, MANIFEST, CONFIG, EXECUTABLE, SERVICE


class SensorPackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.package = Path(self.temp.name) / 'target.zip'
        self.members = {name: b'fixture bytes' for name in REQUIRED}
        self.members[RC] = ('service vendor.sensors-hal-multihal /vendor/bin/hw/' + SERVICE + '\n    class hal\n').encode()
        self.members[MANIFEST] = b'<manifest><hal format="aidl"><name>android.hardware.sensors</name><version>3</version><fqname>ISensors/default</fqname></hal></manifest>'
        self.members[CONFIG] = b'# Sub HALs\nsensors.dynamic_sensor_hal.so\nsensors.ssc.so\nsensors.oplus.so\n'

    def check(self):
        with zipfile.ZipFile(self.package, 'w') as archive:
            for name, data in self.members.items():
                archive.writestr(name, data)
        return inspect(self.package)

    def test_reviewed_wiring_passes(self):
        self.assertTrue(self.check()['sensor_contract_pass'])

    def test_generic_replacement_fails_even_with_other_files_present(self):
        self.members['VENDOR/bin/hw/android.hardware.sensors-service.multihal'] = self.members.pop(EXECUTABLE)
        self.assertFalse(self.check()['sensor_contract_pass'])

    def test_second_init_provider_fails(self):
        self.members['ODM/etc/init/second.rc'] = self.members[RC]
        self.assertFalse(self.check()['sensor_contract_pass'])

    def test_stale_init_command_fails_without_installed_generic_binary(self):
        self.members['VENDOR/etc/init/stale.rc'] = b'service other /vendor/bin/hw/android.hardware.sensors-service.multihal\n'
        self.assertFalse(self.check()['sensor_contract_pass'])

    def test_wrong_aidl_version_fails(self):
        self.members[MANIFEST] = self.members[MANIFEST].replace(b'<version>3', b'<version>2')
        self.assertFalse(self.check()['sensor_contract_pass'])

    def test_duplicate_hal_declaration_fails(self):
        self.members['ODM/etc/vintf/manifest/second.xml'] = self.members[MANIFEST]
        self.assertFalse(self.check()['sensor_contract_pass'])

    def test_missing_oplus_subhal_fails(self):
        self.members[CONFIG] = b'sensors.ssc.so\n'
        self.assertFalse(self.check()['sensor_contract_pass'])

    def test_wrong_partition_does_not_supply_library(self):
        name = 'VENDOR/lib64/sensors.oplus.so'
        self.members[name.replace('VENDOR/', 'SYSTEM/')] = self.members.pop(name)
        self.assertFalse(self.check()['sensor_contract_pass'])

    def invoke_collected(self, state='success', tamper=False):
        self.check()
        root = Path(self.temp.name)
        record = root / 'result.json'
        report = root / 'report.json'
        record.write_text(json.dumps({'state': state, 'artifacts': [{
            'path': 'out/target/product/ferrari/lineage_ferrari-target_files.zip',
            'collected': str(self.package), 'bytes': self.package.stat().st_size,
            'sha256': hashlib.sha256(self.package.read_bytes()).hexdigest()}]}))
        if tamper:
            with self.package.open('r+b') as stream:
                stream.write(b'X')  # Same length, changed bytes after collection.
        with patch.object(sys, 'argv', ['candidate_sensors.py', '--run-record', str(record), '--report', str(report)]):
            return main()

    def test_successful_collection_contract(self):
        self.assertEqual(self.invoke_collected(), 0)

    def test_failed_collection_cannot_produce_pass(self):
        with self.assertRaisesRegex(ValueError, 'successful collector record'):
            self.invoke_collected(state='failed')
        self.assertFalse((Path(self.temp.name) / 'report.json').exists())

    def test_same_size_archive_tampering_rejected(self):
        with self.assertRaisesRegex(ValueError, 'collected archive changed'):
            self.invoke_collected(tamper=True)
        self.assertFalse((Path(self.temp.name) / 'report.json').exists())


if __name__ == '__main__':
    unittest.main()
