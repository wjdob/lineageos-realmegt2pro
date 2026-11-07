"""Regression checks for the native15 runtime omission and private input boundary."""
from pathlib import Path
import hashlib
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'build'))
import common_runtime_24 as runtime


class CommonRuntimeTests(unittest.TestCase):
    def fixture(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        data = b'reviewed Qualcomm runtime'
        row = {'path': 'proprietary/vendor/lib64/libqti-perfd-client.so',
               'member': 'VENDOR/lib64/libqti-perfd-client.so', 'bytes': len(data),
               'sha256': hashlib.sha256(data).hexdigest()}
        contract = {'schema': 1, 'files': [row], 'compiled_interfaces': [
            'VENDOR/lib64/vendor.qti.hardware.perf@2.3.so'], 'metadata': [], 'interface_sources': []}
        return root, data, contract

    def package(self, root, data, contract, interface=True, changed=False):
        path = root / 'target.zip'
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr(contract['files'][0]['member'], b'changed' if changed else data)
            if interface:
                elf = bytearray(64)
                elf[:6] = b'\x7fELF\x02\x01'
                elf[18:20] = (183).to_bytes(2, 'little')
                archive.writestr(contract['compiled_interfaces'][0], elf)
        return path

    def test_complete_runtime_and_vendor_interface_pass(self):
        root, data, contract = self.fixture()
        self.assertTrue(runtime.check_package(self.package(root, data, contract), contract)['common_runtime_pass'])

    def test_system_interface_cannot_qualify_missing_vendor_variant(self):
        root, data, contract = self.fixture()
        package = self.package(root, data, contract, interface=False)
        with zipfile.ZipFile(package, 'a') as archive:
            archive.writestr('SYSTEM_EXT/lib64/vendor.qti.hardware.perf@2.3.so', b'not vendor-visible')
        self.assertFalse(runtime.check_package(package, contract)['common_runtime_pass'])

    def test_same_filename_with_wrong_runtime_bytes_fails(self):
        root, data, contract = self.fixture()
        self.assertFalse(runtime.check_package(self.package(root, data, contract, changed=True), contract)['common_runtime_pass'])

    def test_contract_cannot_write_a_partition_or_escape(self):
        _, _, contract = self.fixture()
        for name in ('proprietary/vendor/../../boot', 'proprietary/vendor/firmware/abl.img',
                     '/proprietary/vendor/bin/other', 'proprietary/vendor/lib64//other'):
            contract['files'][0]['path'] = name
            with self.assertRaises(ValueError):
                runtime.rows(contract)

    def test_duplicate_destinations_fail(self):
        _, _, contract = self.fixture()
        contract['files'] *= 2
        with self.assertRaises(ValueError):
            runtime.rows(contract)

    def test_modified_provider_refused(self):
        root, data, contract = self.fixture()
        path = root / contract['files'][0]['path']
        path.parent.mkdir(parents=True)
        path.write_bytes(data)
        self.assertEqual(runtime.validate_provider(contract, root), 1)
        path.write_bytes(b'changed')
        with self.assertRaises(ValueError):
            runtime.validate_provider(contract, root)

    def test_rejects_all_destination_preimages_before_first_copy(self):
        root, data, contract = self.fixture()
        tree = root / 'tree'
        second = dict(contract['files'][0], path='proprietary/vendor/lib64/libqti-perfd.so',
                      member='VENDOR/lib64/libqti-perfd.so')
        contract['files'].append(second)
        vendor = tree / 'vendor/oneplus/sm8450-common'
        bad = vendor / second['path']
        bad.parent.mkdir(parents=True)
        bad.write_bytes(b'unknown prior file')
        with patch.object(runtime, 'BUILD_TREE', tree), patch.object(runtime, 'isolated'), \
                patch.object(runtime, 'verify_provider', return_value=(contract, root)):
            with self.assertRaises(ValueError):
                runtime.materialize(tree)
        self.assertFalse((vendor / contract['files'][0]['path']).exists())
        self.assertEqual(bad.read_bytes(), b'unknown prior file')


if __name__ == '__main__':
    unittest.main()
