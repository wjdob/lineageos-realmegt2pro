"""Compile small libfdt fixtures to exercise the packaged overlay contract."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fingerprint_memory import check_images, REPO


@unittest.skipUnless(shutil.which('dtc') and shutil.which('fdtoverlay') and shutil.which('fdtget'), 'requires libfdt tools')
class FingerprintMemoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=REPO/'tmp')
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.contract = json.loads((REPO/'configs/fingerprint-memory-23.2.json').read_text())

    def compile(self, text, name):
        path = self.directory/name
        subprocess.run(['dtc','-@','-I','dts','-O','dtb','-o',str(path)], input=text.encode(),
                       check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return path.read_bytes()

    def images(self, size=0x2000000, wrong_heap=False, count=4, board=0x10008):
        bases = []
        for i in range(count):
            source = '''/dts-v1/; / {
                model = "Waipio test"; qcom,msm-id = <457 %d>;
                reserved-memory {
                    ta: qseecom_ta_region { compatible = "shared-dma-pool";
                        size = <0 0x1000000>; alignment = <0 0x400000>;
                        alloc-ranges = <0 0 0 0xffffffff>; reusable; };
                    qseecom_region { size = <0 0x1400000>; };
                    other: other-region { size = <0 0x1000>; };
                };
                soc {
                    qseecom@c1700000 { qseecom_ta_mem = <&ta>; };
                    qcom,dma-heaps { qcom,qseecom_ta { memory-region = <&%s>; }; };
                };
            };''' % (i+1, 'other' if wrong_heap else 'ta')
            bases.append(self.compile(source, 'base-%d.dtb'%i))
        overlay = self.compile('''/dts-v1/; /plugin/; / {
            model = "Ferrari test"; qcom,board-id = <%d 0>;
            fragment@0 { target = <&ta>; __overlay__ { size = <0 %d>; }; };
        };''' % (board,size), 'overlay.dtbo')
        return b'VNDRBOOT'+b'\0'*56+b''.join(bases), bytes.fromhex('d7b7ab1e')+b'\0'*60+overlay

    def test_overlay_updates_every_concatenated_base(self):
        result = check_images(*self.images(), self.contract)
        self.assertEqual(len(result['effective_trees']),4)
        self.assertTrue(all(row['ta_bytes']==33554432 for row in result['effective_trees']))

    def test_rejects_old_sixteen_mib_reservation(self):
        with self.assertRaisesRegex(ValueError,'16777216'):
            check_images(*self.images(size=0x1000000), self.contract)

    def test_native_raw_dtb_mode_checks_all_bases(self):
        vendor_boot, dtbo = self.images()
        result = check_images(vendor_boot[64:], dtbo, self.contract, raw_dtb=True)
        self.assertEqual(len(result['effective_trees']), 4)
        self.assertIn('dtb_sha256', result)

    def test_rejects_heap_bound_to_another_pool(self):
        with self.assertRaisesRegex(ValueError,'DMA heap references another pool'):
            check_images(*self.images(wrong_heap=True), self.contract)

    def test_rejects_missing_compatible_base(self):
        with self.assertRaisesRegex(ValueError,'number of Ferrari-compatible'):
            check_images(*self.images(count=3), self.contract)

    def test_rejects_wrong_board_overlay(self):
        with self.assertRaisesRegex(ValueError,'Ferrari board overlay'):
            check_images(*self.images(board=8), self.contract)

    def test_rejects_non_image_inputs(self):
        with self.assertRaisesRegex(ValueError,'expected vendor_boot'):
            check_images(b'', b'', self.contract)


if __name__ == '__main__':
    unittest.main()
