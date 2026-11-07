from pathlib import Path
import json
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
import warnings
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import codec_store_abi_24 as abi


def elf():
    data = bytearray(512)
    data[:7] = b'\x7fELF\x02\x01\x01'
    struct.pack_into('<H', data, 18, 183)
    struct.pack_into('<Q', data, 32, 64)
    struct.pack_into('<HH', data, 54, 56, 1)
    # Deliberately use VA != file offset.
    struct.pack_into('<IIQQQQQQ', data, 64, 1, 5, 256, 0x4000, 0, 256, 256, 4096)
    return data


def fixture():
    provider = elf()
    provider[256:260] = bytes.fromhex('00400491')  # ADD X0, X0, #272
    provider[260:264] = bytes.fromhex('01248052')  # MOV W1, #288
    provider[264:268] = bytes.fromhex('65540014')
    base = elf()
    old, new = '00218052c5040094', '00248052c5040094'
    base[256:264] = bytes.fromhex(old)
    candidate = bytearray(base)
    candidate[256:264] = bytes.fromhex(new)
    row = dict(name='audio', target_member='VENDOR/bin/audio', source_path='vendor/bin/audio',
               base_sha256=abi.digest(base), candidate_sha256=abi.digest(candidate),
               allocation_va=0x4000, old_hex=old, new_hex=new)
    contract = dict(required_size=288, legacy_size=264, limits='fixture', launchers=[row],
                    provider=dict(target_member='VENDOR/lib64/provider.so', sha256=abi.digest(provider),
                                  constructor_virtual_base_va=0x4000, constructor_virtual_base_hex='00400491',
                                  virtual_base_offset=272, deleting_size_va=0x4004, deleting_size_hex='01248052',
                                  sized_delete_branch_va=0x4008, sized_delete_branch_hex='65540014'))
    return bytes(base), bytes(candidate), bytes(provider), contract


class CodecStoreAbiTests(unittest.TestCase):
    def binding_fixture(self):
        _, _, _, contract = fixture()
        contract['probe'] = {'manifest_sha256': 'a' * 64}
        contract['extraction'] = {'path': 'device/common/extract-files.py', 'sha256': 'b' * 64}
        files = [{'path': contract['extraction']['path'], 'canonical_sha256': 'b' * 64},
                 {'path': contract['launchers'][0]['source_path'], 'canonical_sha256': contract['launchers'][0]['candidate_sha256']}]
        hashes = {str(p.relative_to(abi.ROOT)): abi.digest(p.read_bytes())
                  for p in (abi.CONTRACT, Path(abi.__file__))}
        inputs = {'target': 'otapackage', 'manifest_sha256': 'a' * 64,
                  'recipe_snapshot': {'manifest_sha256': 'a' * 64, 'files': files}, 'source_hashes': hashes}
        return contract, inputs

    def check_binding(self, contract, inputs):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'inputs.json'
            path.write_text(json.dumps(inputs))
            return abi.bind_inputs(path, contract)

    def test_same_run_source_binding_passes(self):
        self.assertEqual(self.check_binding(*self.binding_fixture())['manifest_sha256'], 'a' * 64)

    def test_real_driver_dotdot_invocation_uses_canonical_tool_identity(self):
        contract, inputs = self.binding_fixture()
        invocation = str(abi.ROOT / 'tools/build/../codec_store_abi_24.py')
        with patch.object(abi, '__file__', invocation):
            self.assertEqual(self.check_binding(contract, inputs)['manifest_sha256'], 'a' * 64)

    def test_another_source_manifest_is_rejected(self):
        contract, inputs = self.binding_fixture()
        inputs['manifest_sha256'] = 'c' * 64
        with self.assertRaisesRegex(ValueError, 'source manifest'):
            self.check_binding(contract, inputs)

    def test_stale_contract_or_tool_is_rejected(self):
        for file in (abi.CONTRACT, Path(abi.__file__)):
            contract, inputs = self.binding_fixture()
            inputs['source_hashes'][str(file.relative_to(abi.ROOT))] = '0' * 64
            with self.subTest(file=file), self.assertRaisesRegex(ValueError, 'same-run inputs'):
                self.check_binding(contract, inputs)

    def test_unpatched_launcher_recipe_is_rejected(self):
        contract, inputs = self.binding_fixture()
        inputs['recipe_snapshot']['files'][-1]['canonical_sha256'] = contract['launchers'][0]['base_sha256']
        with self.assertRaisesRegex(ValueError, 'same-run recipe'):
            self.check_binding(contract, inputs)

    def test_virtual_addresses_translate_through_load(self):
        base, candidate, provider, contract = fixture()
        self.assertEqual(abi.check_launcher(candidate, contract['launchers'][0], contract)['file_offset'], 256)
        self.assertEqual(abi.check_provider(provider, contract)['required_size'], 288)
        self.assertEqual(abi.check_provider(provider, contract)['virtual_base_offset'], 272)

    def test_legacy_undersized_launcher_is_rejected(self):
        base, _, _, contract = fixture()
        with self.assertRaisesRegex(ValueError, 'undersized'):
            abi.check_launcher(base, contract['launchers'][0], contract)

    def test_unrelated_byte_change_is_rejected_even_with_updated_candidate_hash(self):
        _, candidate, _, contract = fixture()
        changed = bytearray(candidate)
        changed[-1] ^= 1
        contract['launchers'][0]['candidate_sha256'] = abi.digest(changed)
        with self.assertRaisesRegex(ValueError, 'outside allocation'):
            abi.check_launcher(changed, contract['launchers'][0], contract)

    def test_wrong_allocation_is_rejected_even_with_updated_hash(self):
        base, candidate, _, contract = fixture()
        changed = bytearray(candidate)
        struct.pack_into('<I', changed, 256, 0x52800000 | (280 << 5))
        row = contract['launchers'][0]
        row['candidate_sha256'] = abi.digest(changed)
        row['new_hex'] = bytes(changed[256:264]).hex()
        with self.assertRaisesRegex(ValueError, 'allocation size'):
            abi.check_launcher(changed, row, contract)

    def test_unreviewed_or_changed_provider_size_is_rejected(self):
        _, _, provider, contract = fixture()
        changed = bytearray(provider)
        changed[-1] ^= 1
        with self.assertRaisesRegex(ValueError, 'provider changed'):
            abi.check_provider(changed, contract)
        changed = bytearray(provider)
        struct.pack_into('<I', changed, 260, 0x52800001 | (304 << 5))
        contract['provider']['sha256'] = abi.digest(changed)
        contract['provider']['deleting_size_hex'] = bytes(changed[260:264]).hex()
        with self.assertRaisesRegex(ValueError, 'sizeof'):
            abi.check_provider(changed, contract)

    def test_elf_wrong_architecture_extents_and_ambiguous_mapping_are_rejected(self):
        base, _, _, _ = fixture()
        for variant in ('arch', 'headers', 'extent', 'writable', 'duplicate', 'non-file-backed'):
            data = bytearray(base)
            if variant == 'arch':
                struct.pack_into('<H', data, 18, 62)
            elif variant == 'headers':
                struct.pack_into('<H', data, 56, 100)
            elif variant == 'extent':
                struct.pack_into('<Q', data, 64 + 32, 1024)
            elif variant == 'writable':
                struct.pack_into('<I', data, 68, 7)
            elif variant == 'duplicate':
                struct.pack_into('<H', data, 56, 2)
                data[120:176] = data[64:120]
            else:
                struct.pack_into('<Q', data, 64 + 32, 0)
            with self.subTest(variant=variant), self.assertRaises(ValueError):
                abi.executable_offset(data, 0x4000, 4)

    def test_collected_package_binds_provider_and_launcher_together(self):
        base, candidate, provider, contract = fixture()
        with tempfile.TemporaryDirectory() as directory, patch.object(abi, 'load_contract', return_value=contract):
            target = Path(directory) / 'target.zip'
            for data, expected in ((base, False), (candidate, True)):
                with zipfile.ZipFile(target, 'w') as z:
                    z.writestr(contract['provider']['target_member'], provider)
                    z.writestr(contract['launchers'][0]['target_member'], data)
                if expected:
                    self.assertEqual(abi.check_package(target)['launchers'][0]['allocation_size'], 288)
                else:
                    with self.assertRaisesRegex(ValueError, 'undersized'):
                        abi.check_package(target)
            with warnings.catch_warnings():
                warnings.simplefilter('ignore', UserWarning)
                with zipfile.ZipFile(target, 'a') as z:
                    z.writestr(contract['launchers'][0]['target_member'], candidate)
            with self.assertRaisesRegex(ValueError, 'duplicate'):
                abi.check_package(target)


if __name__ == '__main__':
    unittest.main()
