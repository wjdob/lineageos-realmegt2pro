from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'build'))
from init_diagnostic_cache_24 import retire_paths


class DiagnosticCache(unittest.TestCase):
    def test_only_named_init_outputs_retired(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root/'soong/.intermediates/system/core/init/init_first_stage/obj/init.o'
            target.parent.mkdir(parents=True);target.write_bytes(b'diagnostic')
            installed = root/'target/product/ferrari/ramdisk/init'
            installed.parent.mkdir(parents=True);installed.write_bytes(b'diagnostic')
            second = root/'soong/.intermediates/system/core/init/init_second_stage/diagnostic.o'
            second.parent.mkdir(parents=True);second.write_bytes(b'diagnostic')
            library = root/'soong/.intermediates/system/core/init/libinit/diagnostic.o'
            library.parent.mkdir(parents=True);library.write_bytes(b'diagnostic')
            retained = root/'soong/.intermediates/system/core/init/libinit_defaults/normal.o'
            retained.parent.mkdir(parents=True);retained.write_bytes(b'normal')
            retired = retire_paths(root)
            self.assertEqual(len(retired), 4)
            self.assertFalse(target.exists());self.assertFalse(installed.exists());self.assertFalse(second.exists());self.assertFalse(library.exists())
            self.assertEqual(retained.read_bytes(), b'normal')

    def test_symlink_is_refused_before_any_removal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp);out = root/'out';out.mkdir()
            outside = root/'outside';outside.mkdir();(outside/'keep').write_bytes(b'keep')
            target = out/'soong/.intermediates/system/core/init/init_first_stage'
            target.parent.mkdir(parents=True);target.symlink_to(outside, target_is_directory=True)
            with self.assertRaises(ValueError):retire_paths(out)
            self.assertEqual((outside/'keep').read_bytes(), b'keep')

    def test_wrong_type_refused_before_any_removal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            module=root/'soong/.intermediates/system/core/init/init_first_stage'
            module.mkdir(parents=True);(module/'keep').write_bytes(b'keep')
            installed=root/'target/product/ferrari/ramdisk/init';installed.mkdir(parents=True)
            with self.assertRaises(ValueError):retire_paths(root)
            self.assertTrue((module/'keep').exists())


if __name__ == '__main__':unittest.main()
