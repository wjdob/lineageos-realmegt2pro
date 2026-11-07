"""Tests for payload_range.py against payloads built from the AOSP proto.

The payloads are encoded here from system/update_engine/update_metadata.proto field numbers
(independently of the tool's decoder). They exercise what review finding R-15 found broken:
dst_extents (field 6), dst_length (7), data_sha256_hash (8), ZERO/DISCARD operations, and the
whole-partition hash in new_partition_info. No firmware needed.
"""

from __future__ import annotations

import bz2
import hashlib
import lzma
import os
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import payload_range as pr  # noqa: E402

BS = 4096


def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def _vi(field: int, n: int) -> bytes:
    return _varint(field << 3) + _varint(n)


def _ld(field: int, payload: bytes) -> bytes:
    return _varint(field << 3 | 2) + _varint(len(payload)) + payload


def extent(start: int, num: int) -> bytes:
    return _vi(1, start) + _vi(2, num)


def build_payload(partitions, block_size=BS):
    """partitions: [(name, size, [(type, raw_data_or_None, [(start, num)...], compress)], hash_override)]"""
    blobs = bytearray()
    parts_pb = b""
    for name, size, ops, hash_override in partitions:
        image = bytearray(size)
        ops_pb = b""
        for op_type, raw, dst, comp in ops:
            op = _vi(1, op_type)
            if raw is not None:
                data = {"none": lambda d: d, "xz": lzma.compress, "bz2": bz2.compress}[comp](raw)
                op += _vi(2, len(blobs)) + _vi(3, len(data))
                for s, n in dst:
                    op += _ld(6, extent(s, n))                           # dst_extents = 6
                op += _vi(7, len(raw))                                   # dst_length = 7 (varint)
                op += _ld(8, hashlib.sha256(data).digest())              # data_sha256_hash = 8
                blobs += data
                pos = 0
                for s, n in dst:
                    image[s * BS:(s + n) * BS] = raw[pos:pos + n * BS]
                    pos += n * BS
            else:
                for s, n in dst:
                    op += _ld(6, extent(s, n))
                    image[s * BS:(s + n) * BS] = bytes(n * BS)          # ZERO / DISCARD -> zeros
            ops_pb += _ld(8, op)                                         # operations = 8
        digest = hash_override or hashlib.sha256(bytes(image)).digest()
        info = _vi(1, size) + _ld(2, digest)                             # PartitionInfo size=1 hash=2
        parts_pb += _ld(13, _ld(1, name.encode()) + _ld(7, info) + ops_pb)
    manifest = _vi(3, block_size) + parts_pb
    header = b"CrAU" + struct.pack(">QQI", 2, len(manifest), 0)
    return header + manifest + bytes(blobs)


def block(fill: int, n: int = 1) -> bytes:
    return bytes([fill]) * (BS * n)


class ExtractTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.d.cleanup()

    def _run(self, payload: bytes, name: str):
        path = os.path.join(self.d.name, "payload.bin")
        with open(path, "wb") as f:
            f.write(payload)
        with pr.Source(path) as src:
            man, data_start = pr.load_manifest(src)
            part = next(p for p in man.partitions if p.name == name)
            out = os.path.join(self.d.name, name + ".img")
            return pr.extract_partition(src, man, part, data_start, out), out

    def test_zero_discard_and_out_of_order_extents(self):
        # 8 blocks: REPLACE_XZ writes blocks 6-7 then 0-1 (one op, two extents, reversed order),
        # ZERO covers 2-3, DISCARD 4, REPLACE_BZ 5. Garbage pre-fill is impossible (new file), so
        # the ZERO op is checked through the manifest hash of an image whose blocks 2-3 are zero.
        raw = block(0xAA) + block(0xBB) + block(0xCC) + block(0xDD)
        ops = [
            (pr.OP_REPLACE_XZ, raw, [(6, 2), (0, 2)], "xz"),
            (pr.OP_ZERO, None, [(2, 2)], None),
            (pr.OP_DISCARD, None, [(4, 1)], None),
            (pr.OP_REPLACE_BZ, block(0xEE), [(5, 1)], "bz2"),
        ]
        s, out = self._run(build_payload([("p", 8 * BS, ops, None)]), "p")
        self.assertTrue(s["verified"])
        img = open(out, "rb").read()
        self.assertEqual(img[6 * BS:8 * BS], block(0xAA) + block(0xBB))
        self.assertEqual(img[0:2 * BS], block(0xCC) + block(0xDD))
        self.assertEqual(img[2 * BS:5 * BS], bytes(3 * BS))
        self.assertEqual(img[5 * BS:6 * BS], block(0xEE))
        self.assertEqual(s["ops"], {"REPLACE_XZ": 1, "ZERO": 1, "DISCARD": 1, "REPLACE_BZ": 1})

    def test_zero_op_overwrites_earlier_data(self):
        # ZERO must write zeros, not merely skip: data then ZERO over the same block
        ops = [(pr.OP_REPLACE, block(0x11, 2), [(0, 2)], "none"), (pr.OP_ZERO, None, [(1, 1)], None)]
        s, out = self._run(build_payload([("z", 2 * BS, ops, None)]), "z")
        self.assertTrue(s["verified"])
        self.assertEqual(open(out, "rb").read()[BS:], bytes(BS))

    def test_manifest_hash_mismatch_is_refused(self):
        ops = [(pr.OP_REPLACE, block(0x22), [(0, 1)], "none")]
        payload = build_payload([("h", BS, ops, b"\x00" * 32)])
        with self.assertRaises(pr.PayloadError):
            self._run(payload, "h")
        self.assertTrue(os.path.exists(os.path.join(self.d.name, "h.img.unverified")))
        self.assertFalse(os.path.exists(os.path.join(self.d.name, "h.img")))

    def test_corrupt_blob_fails_data_sha256(self):
        ops = [(pr.OP_REPLACE, block(0x33), [(0, 1)], "none")]
        payload = bytearray(build_payload([("c", BS, ops, None)]))
        payload[-1] ^= 0xFF
        with self.assertRaisesRegex(pr.PayloadError, "data_sha256_hash"):
            self._run(bytes(payload), "c")

    def test_incremental_operation_is_refused(self):
        ops = [(pr.OP_REPLACE, block(0x44), [(0, 1)], "none"), (4, None, [(0, 1)], None)]  # SOURCE_COPY
        with self.assertRaisesRegex(pr.PayloadError, "SOURCE_COPY"):
            self._run(build_payload([("i", BS, ops, None)]), "i")


class ParseTests(unittest.TestCase):
    def test_field_numbers(self):
        payload = build_payload([("boot", 2 * BS, [(pr.OP_REPLACE, block(1, 2), [(0, 2)], "none")], None)])
        man = pr.parse_manifest(payload[24:24 + struct.unpack(">Q", payload[12:20])[0]])
        op = man.partitions[0].operations[0]
        self.assertEqual(man.block_size, BS)
        self.assertEqual(op.dst_extents, [(0, 2)])
        self.assertEqual(op.dst_length, 2 * BS)
        self.assertEqual(op.sha256, hashlib.sha256(block(1, 2)).digest())
        self.assertEqual(op.src_extents, [])
        self.assertEqual(man.partitions[0].size, 2 * BS)

    def test_no_zstd_type(self):
        # update_metadata.proto has no ZSTD; 10 is BROTLI_BSDIFF
        self.assertEqual(pr.OP_NAMES[10], "BROTLI_BSDIFF")

    def test_zip_member_offset(self):
        import zipfile
        with tempfile.TemporaryDirectory() as d:
            z = os.path.join(d, "ota.zip")
            payload = build_payload([("v", BS, [(pr.OP_REPLACE, block(7), [(0, 1)], "none")], None)])
            with zipfile.ZipFile(z, "w", compression=zipfile.ZIP_STORED) as zf:
                zf.writestr("META-INF/com/android/metadata", "ota-type=AB\n")
                zf.writestr("payload.bin", payload)
            with pr.Source(z) as src:
                self.assertEqual(src.read(0, 4), b"CrAU")
                man, data_start = pr.load_manifest(src)
                out = os.path.join(d, "v.img")
                self.assertTrue(pr.extract_partition(src, man, man.partitions[0], data_start, out)["verified"])


if __name__ == "__main__":
    unittest.main()
