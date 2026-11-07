from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app_native_visibility as audit


def row(name, needed, scope='app'):
    return dict(path='product/app/Photos/lib/arm64/' + name,
                sha256='a' * 64, scope=scope, needed=needed)


class ExposureTests(unittest.TestCase):
    def test_local_provider_precedes_external_name(self):
        result = audit.dependency_exposure(
            [row('consumer.so', ['libc++.so']), row('libc++.so', [])],
            {'libc++.so'}, set(), 'product', set())
        self.assertEqual(result['edges'][0]['exposure'], 'app-local')

    def test_product_llndk_is_available_without_ndk_public_listing(self):
        result = audit.dependency_exposure([row('decoder.so', ['libvndksupport.so'])],
            set(), {'libvndksupport.so'}, 'product', set())
        self.assertFalse(result['unclassified'])
        self.assertEqual(result['edges'][0]['exposure'], 'product-LLNDK')

    def test_data_app_does_not_inherit_product_llndk(self):
        result = audit.dependency_exposure([row('decoder.so', ['libvndksupport.so'])],
            set(), {'libvndksupport.so'}, 'data', {'libvndksupport.so'})
        self.assertEqual(len(result['unclassified']), 1)

    def test_system_bundle_requires_an_actual_system_search_candidate(self):
        rows = [row('client.so', ['libprivate.so'])]
        absent = audit.dependency_exposure(rows, set(), set(), 'system-bundled', set())
        present = audit.dependency_exposure(rows, set(), set(), 'system-bundled', {'libprivate.so'})
        self.assertEqual(len(absent['unclassified']), 1)
        self.assertEqual(present['edges'][0]['exposure'], 'bundled-system-search')

    def test_platform_roots_are_excluded_from_product_app_projection(self):
        result = audit.dependency_exposure([row('heif.so', ['libgui.so'], 'platform')],
                                          set(), set(), 'product', set())
        self.assertFalse(result['edges'])
        self.assertEqual(len(result['excluded_platform_roots']), 1)

    def test_cross_app_basename_collision_is_not_silently_merged(self):
        with self.assertRaisesRegex(ValueError, 'ambiguous app-local'):
            audit.dependency_exposure([row('libx.so', []), row('libx.so', [])],
                                      set(), set(), 'product', set())

    def test_unknown_domain_is_refused(self):
        with self.assertRaises(ValueError):
            audit.dependency_exposure([], set(), set(), 'vendor-or-anywhere', set())


class InputTests(unittest.TestCase):
    def test_arm64_public_list_filters_32_bit_and_keeps_nopreload(self):
        self.assertEqual(audit.library_list(b'# comment\nliba.so 32\nlibb.so 64\n'
                                           b'libc.so nopreload # late\n'),
                         {'libb.so', 'libc.so'})

    def test_unknown_library_list_syntax_is_not_ignored(self):
        for value in [b'../../libx.so', b'libx.so 32 64', b'libx.so magic']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                audit.library_list(value)

    def test_duplicate_and_escaping_manifest_paths_are_refused(self):
        digest = b'a' * 64
        for value in [digest + b'  ../outside.so\n',
                      digest + b'  system/lib64/a.so\n' + digest + b'  system/lib64/a.so\n',
                      b'not-a-manifest']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                audit.manifest(value)

    def test_normalized_relative_paths_required(self):
        for name in ['/system/a.so', 'system//a.so', 'system/./a.so', 'system\\a.so']:
            with self.subTest(name=name), self.assertRaises(ValueError):
                audit.safe_path(name)

    def test_wrong_elf_is_refused_before_readelf(self):
        with patch.object(audit.subprocess, 'run') as command:
            with self.assertRaisesRegex(ValueError, 'ARM64 shared ELF'):
                audit.inspect_elf(b'not target code', Path('readelf'), Path('.'))
        command.assert_not_called()

    def test_archive_identity_is_required_before_native_inspection(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'input.zip'
            path.write_bytes(b'changed')
            with patch.object(audit, 'inspect_elf') as inspect:
                with self.assertRaisesRegex(ValueError, 'archive identity'):
                    audit.inventory(path, '0' * 64, 'addon', 'photos', Path('readelf'), Path(directory))
                inspect.assert_not_called()

    def test_unreviewed_native_placement_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'input.zip'
            data = b'not executed'
            relative = 'vendor/bin/bad.so'
            with zipfile.ZipFile(path, 'w') as z:
                z.writestr('manifest.sha256', audit.sha(data) + '  ' + relative + '\n')
                z.writestr('payload/' + relative, data)
            with patch.object(audit, 'inspect_elf') as inspect:
                with self.assertRaisesRegex(ValueError, 'placement'):
                    audit.inventory(path, audit.sha(path.read_bytes()), 'addon', 'photos',
                                    Path('readelf'), Path(directory))
                inspect.assert_not_called()

    def test_signature_and_runtime_are_not_inferred_from_an_inventory(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'input.apk'
            with zipfile.ZipFile(path, 'w') as z:
                z.writestr('lib/arm64-v8a/liba.so', b'fixture')
            with patch.object(audit, 'inspect_elf', return_value={'needed': []}):
                result = audit.inventory(path, audit.sha(path.read_bytes()), 'apk', 'clock',
                                         Path('readelf'), Path(directory))
            self.assertEqual(len(result['libraries']), 1)
            self.assertFalse(result['signature_verified'])
            self.assertFalse(result['runtime_qualified'])


@unittest.skipUnless(shutil.which('clang') and shutil.which('ld.lld') and shutil.which('readelf'),
                     'requires host Clang/LLD and readelf for a compile-only ARM64 fixture')
class ElfMetadataTests(unittest.TestCase):
    def test_actual_arm64_shared_object_metadata_without_loading_it(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'fixture.c'
            source.write_text('extern int external_symbol(int);\n'
                              'int fixture_entry(int x) { return external_symbol(x); }\n')
            binary = root / 'fixture.so'
            subprocess.run(['clang', '--target=aarch64-linux-android37', '-fuse-ld=lld',
                            '-nostdlib', '-shared', '-fPIC', '-Wl,-soname,libfixture.so',
                            str(source), '-o', str(binary)], check=True, capture_output=True)
            result = audit.inspect_elf(binary.read_bytes(), Path(shutil.which('readelf')), root)
            self.assertIn('external_symbol', result['imports'])
            self.assertIn('fixture_entry', result['exports'])
            self.assertEqual(result['soname'], ['libfixture.so'])


if __name__ == '__main__':
    unittest.main()
