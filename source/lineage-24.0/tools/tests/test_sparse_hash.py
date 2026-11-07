import hashlib
import io
from pathlib import Path
import struct
import sys
import unittest
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sparse_hash import image_hash, MAGIC, BUFFER


def fixture(extension=False):
    raw = b'abcd' * 1024
    fill = b'\x01\x23\x45\x67'
    expanded = raw + fill * 1024 + bytes(4096)
    crc = zlib.crc32(expanded)
    extra = b'ext!' if extension else b''
    def chunk(kind, blocks, data):
        return struct.pack('<2H2I', kind, 0, blocks, 12 + len(extra) + len(data)) + extra + data
    header = struct.pack('<I4H4I', MAGIC, 1, 0, 28 + len(extra), 12 + len(extra), 4096, 3, 4, crc)
    data = header + extra + chunk(0xCAC1, 1, raw) + chunk(0xCAC2, 1, fill) + chunk(0xCAC3, 1, b'') + chunk(0xCAC4, 0, struct.pack('<I', crc))
    return data, expanded


class SparseHashTests(unittest.TestCase):
    def test_mixed_chunks_and_crc(self):
        data, raw = fixture()
        self.assertEqual(image_hash(io.BytesIO(data), len(raw)),
                         {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(), 'sparse': True})

    def test_extended_headers(self):
        data, raw = fixture(True)
        self.assertEqual(image_hash(io.BytesIO(data), len(raw))['sha256'], hashlib.sha256(raw).hexdigest())

    def test_raw_and_empty(self):
        for data in (b'', b'abc', b'abcd' * BUFFER):
            self.assertEqual(image_hash(io.BytesIO(data), len(data)),
                             {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(), 'sparse': False})

    def test_short_reads(self):
        class ShortReader(io.BytesIO):
            def read(self, size=-1):
                return super().read(min(size, 3))
        data, raw = fixture()
        self.assertEqual(image_hash(ShortReader(data), len(raw))['sha256'], hashlib.sha256(raw).hexdigest())

    def test_rejects_truncation(self):
        data, raw = fixture()
        for end in (3, 4, 27, 32, len(data)-1):
            with self.subTest(end=end), self.assertRaises(ValueError):
                image_hash(io.BytesIO(data[:end]), len(raw))

    def test_rejects_invalid_headers_and_chunks(self):
        data, raw = fixture()
        for offset, format_, value in ((4, '<H', 2), (8, '<H', 27), (10, '<H', 11),
                                       (12, '<I', 3), (16, '<I', 4), (20, '<I', 3),
                                       (24, '<I', 1), (28, '<H', 0xCAFF),
                                       (32, '<I', 4), (36, '<I', 12)):
            changed = bytearray(data)
            struct.pack_into(format_, changed, offset, value)
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                image_hash(io.BytesIO(changed), len(raw))

    def test_rejects_checksum_and_trailing_data(self):
        data, raw = fixture()
        changed = bytearray(data); changed[-1] ^= 1
        for invalid in (changed, data+b'extra'):
            with self.assertRaises(ValueError):
                image_hash(io.BytesIO(invalid), len(raw))

    def test_expected_size_is_enforced(self):
        for data, size in ((b'abc', 2), (b'abc', 4), (b'', -1)):
            with self.assertRaises(ValueError):
                image_hash(io.BytesIO(data), size)

    def test_large_fill_and_hole(self):
        block_size = 4096
        blocks = BUFFER // block_size + 1
        fill = b'\x89\xab\xcd\xef'
        raw = fill * (blocks * block_size // 4) + bytes(blocks * block_size)
        header = struct.pack('<I4H4I', MAGIC, 1, 0, 28, 12, block_size, blocks * 2, 2, 0)
        data = header + struct.pack('<2H2I', 0xCAC2, 0, blocks, 16) + fill
        data += struct.pack('<2H2I', 0xCAC3, 0, blocks, 12)
        self.assertEqual(image_hash(io.BytesIO(data), len(raw))['sha256'], hashlib.sha256(raw).hexdigest())


if __name__ == '__main__':
    unittest.main()
