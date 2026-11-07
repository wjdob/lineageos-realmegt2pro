import struct
import sys
import tempfile
import unittest
from pathlib import Path
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from firmware_policy import OS_PARTITIONS, check, exact_partitions


def varint(n):
    out = bytearray()
    while n >= 128:
        out.append((n & 127) | 128)
        n >>= 7
    return bytes(out + bytes([n]))


def field(number, data):
    return varint(number * 8 + 2) + varint(len(data)) + data


class FirmwarePolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def packages(self, payload_names=None, radio=False):
        ota, target = self.root/'ota.zip', self.root/'target.zip'
        manifest = b''.join(field(13, field(1, n.encode())) for n in
                            (payload_names if payload_names is not None else sorted(OS_PARTITIONS)))
        with zipfile.ZipFile(ota, 'w') as z:
            z.writestr('payload.bin', b'CrAU' + struct.pack('>QQI', 2, len(manifest), 0) + manifest)
        with zipfile.ZipFile(target, 'w') as z:
            z.writestr('META/ab_partitions.txt', '\n'.join(sorted(OS_PARTITIONS)))
            for n in OS_PARTITIONS:
                z.writestr('IMAGES/'+n+'.img', b'fixture')
            if radio:
                z.writestr('RADIO/abl.img', b'firmware')
        return ota, target

    def test_external_firmware_package_accepted(self):
        self.assertEqual(check(*self.packages())['state'], 'passed')

    def test_payload_firmware_rejected_even_when_target_list_is_clean(self):
        with self.assertRaisesRegex(ValueError, 'unexpected'):
            check(*self.packages(payload_names=[*OS_PARTITIONS, 'abl']))

    def test_bundled_radio_rejected(self):
        with self.assertRaisesRegex(ValueError, 'RADIO'):
            check(*self.packages(radio=True))

    def test_compressed_payload_rejected(self):
        ota, target = self.packages()
        with zipfile.ZipFile(ota) as z:
            payload = z.read('payload.bin')
        with zipfile.ZipFile(ota, 'w', compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr('payload.bin', payload)
        with self.assertRaisesRegex(ValueError, 'stored uncompressed'):
            check(ota, target)

    def test_missing_and_duplicate_partitions_rejected(self):
        with self.assertRaisesRegex(ValueError, 'missing'):
            exact_partitions(OS_PARTITIONS-{'boot'}, 'fixture')
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            exact_partitions([*OS_PARTITIONS, 'boot'], 'fixture')

    def test_target_partition_firmware_rejected(self):
        ota, target = self.packages()
        with zipfile.ZipFile(self.root/'clean.zip', 'w') as z:
            with zipfile.ZipFile(target) as original:
                for item in original.infolist():
                    data = original.read(item.filename)
                    if item.filename == 'META/ab_partitions.txt':
                        data += b'\nmodem'
                    z.writestr(item, data)
        with self.assertRaisesRegex(ValueError, 'target-files: unexpected'):
            check(ota, self.root/'clean.zip')


if __name__ == '__main__':
    unittest.main()
