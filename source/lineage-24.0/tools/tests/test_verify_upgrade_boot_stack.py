import hashlib
import importlib.util
import io
from pathlib import Path
import sys
import unittest

device=Path(__file__).resolve().parents[1]/'device'
sys.path.insert(0,str(device))
spec=importlib.util.spec_from_file_location('verify_upgrade_boot_stack',device/'verify_upgrade_boot_stack.py')
verify=importlib.util.module_from_spec(spec);spec.loader.exec_module(verify)


class ExactImageReadbackTests(unittest.TestCase):
    def test_short_vbmeta_prefix_is_distinct_from_whole_partition(self):
        image=b'AVB0'+bytes(12284)
        partition=image+bytes(65536-len(image))
        expected=hashlib.sha256(image).hexdigest()
        self.assertEqual(verify.measure_exact(io.BytesIO(partition[:len(image)]),len(image)),expected)
        self.assertNotEqual(hashlib.sha256(partition).hexdigest(),expected)

    def test_extra_partition_padding_cannot_be_treated_as_image(self):
        with self.assertRaisesRegex(ValueError,'extra'):
            verify.measure_exact(io.BytesIO(bytes(65536)),12288)

    def test_short_read_is_refused(self):
        with self.assertRaisesRegex(ValueError,'shorter'):
            verify.measure_exact(io.BytesIO(bytes(4096)),12288)

    def test_empty_image_and_boolean_size_are_refused(self):
        for size in (0,-1,True):
            with self.assertRaises(ValueError):verify.measure_exact(io.BytesIO(b'x'),size)

    def test_fragmented_transport_is_fully_measured(self):
        class Fragmented(io.BytesIO):
            def read(self,size=-1):return super().read(min(size,7))
        data=b'packaged-image'*65536
        self.assertEqual(verify.measure_exact(Fragmented(data),len(data)),hashlib.sha256(data).hexdigest())


if __name__=='__main__':unittest.main()
