"""Tests for the offline boot image parser.

The fixtures are synthetic boot images built in memory, so the suite runs
anywhere without needing firmware files. Where a real reference image is present
under references/, one test additionally checks it can be parsed.
"""

from __future__ import annotations

import gzip
import io
import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bootimg import bootimage, lz4 as lz4mod  # noqa: E402


def build_cpio(entries: list[tuple[str, int, bytes]]) -> bytes:
    """Build a minimal newc cpio archive."""

    out = bytearray()
    for name, mode, data in entries:
        name_bytes = name.encode() + b"\x00"
        # newc field order: ino, mode, uid, gid, nlink, mtime, filesize,
        # devmajor, devminor, rdevmajor, rdevminor, namesize, check
        fields = [
            0,
            mode,
            0,
            0,
            1,
            0,
            len(data),
            0,
            0,
            0,
            0,
            len(name_bytes),
            0,
        ]
        header = b"070701" + b"".join(b"%08X" % f for f in fields)
        out += header
        out += name_bytes
        out += b"\x00" * ((-len(out)) % 4)
        out += data
        out += b"\x00" * ((-len(out)) % 4)
    trailer_name = b"TRAILER!!!\x00"
    fields = [0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, len(trailer_name), 0]
    out += b"070701" + b"".join(b"%08X" % f for f in fields)
    out += trailer_name
    out += b"\x00" * ((-len(out)) % 4)
    return bytes(out)


def lz4_legacy(payload: bytes) -> bytes:
    """Reproduce the framing Android uses: magic, size, length, one LZ4 block."""

    import lz4.block

    block = lz4.block.compress(payload, store_size=False)
    return (
        b"\x02\x21\x4c\x18"
        + struct.pack("<I", len(payload))
        + struct.pack("<I", len(block))
        + block
    )


def build_boot_v4(
    *,
    kernel: bytes = b"",
    ramdisk_raw: bytes = b"",
    ramdisk_lz4: bytes | None = None,
    cmdline: str = "",
    os_version: tuple[int, int, int, int] = (12, 0, 0, 0),
    page: int = 4096,
) -> bytes:
    """Assemble a header v4 boot image with 4 KiB pages."""

    ramdisk = ramdisk_lz4 if ramdisk_lz4 is not None else ramdisk_raw
    os_raw = (os_version[0] << 25) | (os_version[1] << 18) | (os_version[2] << 11) | os_version[3]
    header = bytearray(page)
    header[0:8] = b"ANDROID!"
    struct.pack_into("<I", header, 8, len(kernel))
    struct.pack_into("<I", header, 12, len(ramdisk))
    struct.pack_into("<I", header, 16, os_raw)
    struct.pack_into("<I", header, 20, 0)  # signature size
    struct.pack_into("<I", header, 24, 0)  # reserved
    struct.pack_into("<I", header, 28, 0)
    struct.pack_into("<I", header, 32, 0)
    struct.pack_into("<I", header, 36, page)
    struct.pack_into("<I", header, 40, 4)  # header version
    header[44 : 44 + len(cmdline)] = cmdline.encode()
    image = bytearray(header)
    for blob in (kernel, ramdisk):
        if not blob:
            continue
        image += blob
        image += b"\x00" * ((-len(image)) % page)
    return bytes(image)


class CpioTests(unittest.TestCase):
    def test_round_trip_entries(self):
        payload = b"hello ramdisk"
        archive = build_cpio([("init", 0o100750, payload), ("etc", 0o40755, b"")])
        entries = list(bootimage.iter_cpio(archive))
        self.assertEqual([e.name for e in entries], ["init", "etc"])
        self.assertEqual(entries[0].data, payload)
        self.assertTrue(entries[0].is_symlink is False)
        self.assertTrue(entries[1].is_dir)
        self.assertEqual(entries[1].mode & 0o7777, 0o755)

    def test_bad_archive_is_empty(self):
        self.assertEqual(list(bootimage.iter_cpio(b"not a cpio")), [])


class HeaderTests(unittest.TestCase):
    def setUp(self):
        import tempfile

        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, data: bytes, name: str = "boot.img") -> str:
        path = os.path.join(self.tmp.name, name)
        with open(path, "wb") as fh:
            fh.write(data)
        return path

    def test_v4_header_fields(self):
        kernel = b"K" * 5000
        ramdisk = gzip.compress(build_cpio([("init", 0o100755, b"x" * 10)]))
        path = self.write(build_boot_v4(kernel=kernel, ramdisk_raw=ramdisk, cmdline="console=tty0"))
        image = bootimage.load(path)
        self.assertEqual(image.header_version, 4)
        self.assertEqual(image.page_size, 4096)
        self.assertEqual(image.kernel.size, 5000)
        self.assertEqual(image.ramdisk.size, len(ramdisk))
        self.assertEqual(image.cmdline, "console=tty0")
        self.assertEqual(image.os_version, (12, 0, 0, 0))
        self.assertEqual(image.os_version_str, "12.0.0")
        # Kernel must be page aligned after the header.
        self.assertEqual(image.kernel.offset, 4096)
        self.assertEqual(image.ramdisk.offset, 4096 + 2 * 4096)
        self.assertEqual(image.kernel.effective, kernel)
        self.assertEqual(image.ramdisk.compression, "gzip")

    def test_lz4_legacy_ramdisk(self):
        archive = build_cpio([("init", 0o100755, b"magisk" * 100)])
        path = self.write(build_boot_v4(ramdisk_lz4=lz4_legacy(archive)))
        image = bootimage.load(path)
        self.assertEqual(image.ramdisk.compression, "lz4")
        self.assertEqual(image.ramdisk.unpacked, archive)

    def test_missing_magic_is_rejected(self):
        path = self.write(b"NOTABOOT" + b"\x00" * 4096)
        with self.assertRaises(bootimage.BootImageError):
            bootimage.load(path)

    def test_identity_and_magisk_markers(self):
        build_prop = (
            "ro.product.bootimage.device=ferrari\n"
            "ro.bootimage.build.fingerprint=realme/RMX3301/ferrari:15/AP3A/1:user/release-keys\n"
            "ro.bootimage.build.version.sdk=35\n"
        ).encode()
        archive = build_cpio(
            [
                ("init", 0o100750, b"magiskinit\x00magisk\x00"),
                ("system/etc/ramdisk/build.prop", 0o100644, build_prop),
                (".backup/.magisk", 0o100000, b"KEEPVERITY=true\nSHA1=deadbeef\n"),
            ]
        )
        path = self.write(build_boot_v4(ramdisk_lz4=lz4_legacy(archive)))
        image = bootimage.load(path)
        identity = image.identity()
        self.assertEqual(identity["device"], "ferrari")
        self.assertEqual(identity["android_release_from_sdk"], "Android 15")
        markers = image.patch_markers()
        self.assertIsNotNone(markers["magisk"])
        self.assertEqual(markers["magisk"]["config"]["KEEPVERITY"], "true")
        self.assertTrue(markers["magisk"]["magiskinit"])

    def test_android_release_names(self):
        self.assertEqual(bootimage.android_release_name(35), "Android 15")
        self.assertEqual(bootimage.android_release_name(33), "Android 13")
        self.assertIn("99", bootimage.android_release_name(99))


class Lz4Tests(unittest.TestCase):
    """The three legacy layouts that appear in real boot images."""

    @staticmethod
    def _block(payload: bytes) -> bytes:
        import lz4.block

        return lz4.block.compress(payload, store_size=False)

    def test_android_layout_length_prefixed_blocks(self):
        # magic, uncompressed size, then one 4 byte length and its block.
        payload = b"ramdisk payload" * 200
        block = self._block(payload)
        blob = (
            b"\x02\x21\x4c\x18"
            + struct.pack("<I", len(payload))
            + struct.pack("<I", len(block))
            + block
        )
        self.assertEqual(lz4mod.decompress(blob), payload)

    def test_lz4_cli_layout_single_raw_block(self):
        # magic, uncompressed size, then the block with no length prefix.
        payload = b"ramdisk payload" * 200
        block = self._block(payload)
        blob = b"\x02\x21\x4c\x18" + struct.pack("<I", len(payload)) + block
        self.assertEqual(lz4mod.decompress(blob), payload)

    def test_layout_with_real_block_size_field(self):
        # magic, then a 64 KiB block size field, then the block.
        payload = b"ramdisk payload" * 200
        block = self._block(payload)
        blob = (
            b"\x02\x21\x4c\x18"
            + struct.pack("<I", 0x10000)
            + struct.pack("<I", len(payload))
            + block
        )
        self.assertEqual(lz4mod.decompress(blob), payload)

    def test_declared_size_smaller_than_output_is_recovered(self):
        # The header's size field is not always the real output size.
        payload = b"x" * 4000
        block = self._block(payload)
        blob = (
            b"\x02\x21\x4c\x18"
            + struct.pack("<I", 37)
            + struct.pack("<I", len(block))
            + block
        )
        self.assertEqual(lz4mod.decompress(blob), payload)

    def test_unknown_framing_raises(self):
        with self.assertRaises(lz4mod.Lz4Error):
            lz4mod.decompress(b"\x00\x01\x02\x03" + b"\x00" * 64)


def build_vendor_boot_v4(
    *,
    vendor_ramdisk: bytes = b"",
    fdt_payload_size: int = 1024,
    header_dtb_size: int | None = None,
    table_entries: list[tuple[str, bytes]] | None = None,
    page: int = 4096,
) -> bytes:
    """Assemble a vendor boot image, header v4, with optional ramdisk table.

    The header claims a dtb size that can be deliberately wrong, because that is
    what the images for this phone do.
    """

    entries = table_entries or []
    fdt = b"\xd0\r\xfe\xed" + struct.pack(">I", 8 + fdt_payload_size) + b"\x00" * fdt_payload_size
    dtb_size = header_dtb_size if header_dtb_size is not None else len(fdt)

    header = bytearray(page)
    header[0:8] = b"VNDRBOOT"
    struct.pack_into("<I", header, 8, 4)  # header version
    struct.pack_into("<I", header, 12, page)
    struct.pack_into("<I", header, 16, 0x8000)
    struct.pack_into("<I", header, 20, 0x1000000)
    struct.pack_into("<I", header, 24, len(vendor_ramdisk))
    header[28 : 28 + 8] = b"vfb test"
    struct.pack_into("<I", header, 2076, 0x100)
    header[2080:2084] = b"vb\x00\x00"
    struct.pack_into("<I", header, 2096, 2128)  # header size
    struct.pack_into("<I", header, 2100, dtb_size)
    struct.pack_into("<Q", header, 2104, 0x1F00000)

    def align(value: int) -> int:
        return value + ((-value) % page)

    ramdisk_offset = align(page)
    after_ramdisk = align(ramdisk_offset + len(vendor_ramdisk))
    table_offset = after_ramdisk if entries else 0

    table = bytearray()
    blob_offset = align(table_offset + 108 * len(entries)) if entries else 0
    for name, blob in entries:
        entry = bytearray(108)
        struct.pack_into("<I", entry, 0, len(blob))
        struct.pack_into("<Q", entry, 4, blob_offset)
        struct.pack_into("<I", entry, 12, 1)
        entry[16 : 16 + len(name)] = name.encode()
        table.extend(entry)
        blob_offset = align(blob_offset + len(blob))

    # The table fields live in the header, so they are written last, once the
    # body layout is known.
    struct.pack_into("<I", header, 2112, len(entries))
    struct.pack_into("<I", header, 2116, 108)
    struct.pack_into("<Q", header, 2120, table_offset)

    body = bytearray(header)
    def pad() -> None:
        body.extend(b"\x00" * ((-len(body)) % page))

    pad()
    body.extend(vendor_ramdisk)
    pad()
    if entries:
        body.extend(table)
        pad()
        for _, blob in entries:
            body.extend(blob)
            pad()
    body.extend(fdt)
    pad()
    return bytes(body)


class VendorBootTests(unittest.TestCase):
    def setUp(self):
        import tempfile

        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, data: bytes, name: str = "vendor_boot.img") -> str:
        path = os.path.join(self.tmp.name, name)
        with open(path, "wb") as fh:
            fh.write(data)
        return path

    def test_header_fields(self):
        archive = build_cpio([("lib/modules/test.ko", 0o100644, b"x" * 32)])
        path = self.write(build_vendor_boot_v4(vendor_ramdisk=lz4_legacy(archive)))
        self.assertTrue(bootimage.is_vendor_boot(path))
        image = bootimage.load_vendor_boot(path)
        self.assertEqual(image.header_version, 4)
        self.assertEqual(image.page_size, 4096)
        self.assertEqual(image.vendor_ramdisk_size, len(lz4_legacy(archive)))
        self.assertEqual(image.cmdline, "vfb test")
        self.assertEqual(image.name, "vb")
        entries = image.ramdisk_entries()
        self.assertEqual([e.name for e in entries], ["lib/modules/test.ko"])

    def test_dtb_size_taken_from_device_tree_header(self):
        # The header claims four times the real size, which is what this
        # platform ships. The device tree's own header is authoritative.
        real = 8 + 1024
        path = self.write(build_vendor_boot_v4(vendor_ramdisk=b"", header_dtb_size=real * 4))
        image = bootimage.load_vendor_boot(path)
        self.assertIsNotNone(image.dtb)
        self.assertEqual(image.dtb.size, real)
        self.assertTrue(any("device tree header says" in n for n in image.notes))

    def test_ramdisk_table_entries_are_read(self):
        blob_a = b"a" * 100
        blob_b = b"b" * 200
        path = self.write(
            build_vendor_boot_v4(
                vendor_ramdisk=b"",
                table_entries=[("platform", blob_a), ("dlkm", blob_b)],
            )
        )
        image = bootimage.load_vendor_boot(path)
        self.assertEqual([r.name for r in image.ramdisks], ["platform", "dlkm"])
        self.assertEqual(image.ramdisks[0].size, 100)
        self.assertEqual(image.ramdisks[1].size, 200)

    def test_inconsistent_table_is_ignored_not_fatal(self):
        data = bytearray(build_vendor_boot_v4(vendor_ramdisk=b""))
        struct.pack_into("<I", data, 2112, 5000)  # absurd entry count
        struct.pack_into("<Q", data, 2120, 10 ** 12)  # absurd offset
        path = self.write(bytes(data))
        image = bootimage.load_vendor_boot(path)
        self.assertEqual(image.ramdisks, [])
        self.assertTrue(any("inconsistent" in n for n in image.notes))

    def test_magic_is_required(self):
        path = self.write(b"NOTAVENDOR" + b"\x00" * 4096)
        self.assertFalse(bootimage.is_vendor_boot(path))
        with self.assertRaises(bootimage.BootImageError):
            bootimage.load_vendor_boot(path)


class ReferenceImageTests(unittest.TestCase):
    """Optional checks against real files, skipped when they are absent."""

    REFERENCE = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "references",
        "boot_1150.0.0.130(EX01)_stock.img",
    )

    def test_reference_stock_image_parses(self):
        if not os.path.exists(self.REFERENCE):
            self.skipTest("reference boot image not present")
        image = bootimage.load(self.REFERENCE, read_ramdisk=True)
        self.assertEqual(image.header_version, 4)
        self.assertTrue(image.kernel_version.startswith("5.10."))
        entries = {e.name for e in image.ramdisk_entries()}
        self.assertIn("system/etc/ramdisk/build.prop", entries)


if __name__ == "__main__":
    unittest.main()
