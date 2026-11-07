"""Offline reader for Android boot images, header versions 0 through 4.

Nothing in this module writes to a device. It answers questions such as "what
Android version was this boot image built for", "which device does it claim to
be", and "is it the same kernel as that other image".

Field offsets follow the AOSP system/tools/mkbootimg/include/bootimg/bootimg.h
definitions. Header v3 and v4 use fixed 4 KiB pages; v0 through v2 use the page
size stored in the header.
"""

from __future__ import annotations

import gzip
import hashlib
import lzma
import os
import re
import struct
from dataclasses import dataclass, field
from typing import Iterator

from . import lz4 as lz4mod

BOOT_MAGIC = b"ANDROID!"
VENDOR_BOOT_MAGIC = b"VNDRBOOT"
AVB_FOOTER_MAGIC = b"AVBf"
CPIO_NEWC = b"070701"
CPIO_CRC = b"070702"
CPIO_ODC = b"070707"

# Offsets in boot_img_hdr_v4. Everything before 44 is identical for v3 and v4.
_OFF_KERNEL_SIZE = 8
_OFF_RAMDISK_SIZE = 12
_OFF_OS_VERSION = 16
_OFF_HEADER_SIZE = 20
_OFF_HEADER_VERSION = 40
_OFF_CMDLINE = 44
_CMDLINE_LEN = 1536
_OFF_RECOVERY_DTBO_SIZE = 1632
_OFF_RECOVERY_DTBO_OFFSET = 1636
_OFF_DTB_SIZE = 1648
_OFF_SIGNATURE_SIZE = 1652

_SIZE_LIMIT_FOR_DEEP_SCAN = 768 * 1024 * 1024

_ANDROID_RELEASE_NAMES = {
    29: "Android 10",
    30: "Android 11",
    31: "Android 12",
    32: "Android 12L",
    33: "Android 13",
    34: "Android 14",
    35: "Android 15",
    36: "Android 16",
}


class BootImageError(Exception):
    """Raised when a file is not a usable Android boot image."""


def android_release_name(sdk: int) -> str:
    return _ANDROID_RELEASE_NAMES.get(sdk, f"SDK {sdk}")


def _cstr(raw: bytes) -> str:
    return raw.split(b"\x00", 1)[0].decode("utf-8", "replace")


def _pages(count: int, page: int) -> int:
    if count <= 0:
        return 0
    return (count + page - 1) // page


def detect_compression(blob: bytes) -> str | None:
    """Name the container format of a kernel or ramdisk blob, if it is compressed."""

    if not blob or len(blob) < 4:
        return None
    if blob[:2] == b"\x1f\x8b":
        return "gzip"
    if blob[:6] == b"\xfd7zXZ\x00":
        return "xz"
    if blob[:3] == b"BZh":
        return "bzip2"
    if blob[:4] in (lz4mod.LEGACY_MAGIC, lz4mod.FRAME_MAGIC):
        return "lz4"
    if blob[:5] == b"\x5d\x00\x00\x80\x00" or blob[:5] == b"\x5d\x00\x00\x00\x00":
        return "lzma"
    if blob[:4] == b"\x28\xb5\x2f\xfd":
        return "zstd"
    if blob[:6] == b"\x89LZO\x00\r\n\x1a\n":
        return "lzo"
    return None


def decompress(blob: bytes, kind: str | None) -> tuple[bytes | None, str | None]:
    """Decompress a blob. Returns (data, note); data is None when it cannot be done."""

    if not blob:
        return None, "empty"
    try:
        if kind == "gzip":
            return gzip.decompress(blob), None
        if kind in ("xz", "lzma"):
            return lzma.decompress(blob), None
        if kind == "lz4":
            return lz4mod.decompress(blob), None
        if kind == "zstd":
            try:
                import zstandard  # type: ignore
            except ImportError:
                return None, "install zstandard to unpack this kernel or ramdisk"
            return zstandard.ZstdDecompressor().decompress(blob), None
        if kind == "lzo":
            try:
                import lzokay  # type: ignore
            except ImportError:
                return None, "install lzokay to unpack this kernel or ramdisk"
            return lzokay.decompress(blob), None
    except Exception as exc:  # noqa: BLE001 - report and carry on
        return None, f"{type(exc).__name__}: {exc}"
    if kind is None:
        return None, "not compressed"
    return None, f"unsupported compression {kind}"


@dataclass
class Section:
    """A kernel, ramdisk, dtb or signature blob inside a boot image."""

    name: str
    offset: int
    size: int
    compression: str | None = None
    data: bytes | None = None
    unpacked: bytes | None = None
    note: str | None = None

    @property
    def unpacked_size(self) -> int | None:
        return None if self.unpacked is None else len(self.unpacked)

    @property
    def sha256(self) -> str | None:
        payload = self.unpacked if self.unpacked is not None else self.data
        if payload is None:
            return None
        return hashlib.sha256(payload).hexdigest()

    @property
    def effective(self) -> bytes | None:
        """The most useful form of this section: unpacked when possible."""

        return self.unpacked if self.unpacked is not None else self.data

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "offset": self.offset,
            "size": self.size,
            "compression": self.compression,
            "unpacked_size": self.unpacked_size,
            "sha256": self.sha256,
            "note": self.note,
        }


@dataclass
class AvbFooter:
    version: tuple[int, int]
    original_image_size: int
    vbmeta_offset: int
    vbmeta_size: int

    def as_dict(self) -> dict:
        return {
            "version": list(self.version),
            "original_image_size": self.original_image_size,
            "vbmeta_offset": self.vbmeta_offset,
            "vbmeta_size": self.vbmeta_size,
        }


@dataclass
class CpioEntry:
    name: str
    mode: int
    size: int
    data: bytes

    @property
    def is_dir(self) -> bool:
        return (self.mode & 0o170000) == 0o040000

    @property
    def is_symlink(self) -> bool:
        return (self.mode & 0o170000) == 0o120000

    @property
    def is_file(self) -> bool:
        return (self.mode & 0o170000) == 0o100000


def iter_cpio(data: bytes) -> Iterator[CpioEntry]:
    """Walk a cpio archive in newc, crc or odc format."""

    if data[:6] in (CPIO_NEWC, CPIO_CRC):
        pos = 0
        while pos + 110 <= len(data):
            if data[pos : pos + 6] not in (CPIO_NEWC, CPIO_CRC):
                break
            try:
                mode = int(data[pos + 14 : pos + 22], 16)
                size = int(data[pos + 54 : pos + 62], 16)
                namesize = int(data[pos + 94 : pos + 102], 16)
            except ValueError:
                break
            name_start = pos + 110
            name = data[name_start : name_start + namesize - 1].decode("utf-8", "replace")
            body = name_start + namesize
            body += (-body) % 4
            payload = data[body : body + size]
            pos = body + size
            pos += (-pos) % 4
            if name == "TRAILER!!!":
                return
            yield CpioEntry(name, mode, size, payload)
    elif data[:6] == CPIO_ODC:
        pos = 0
        while pos + 76 <= len(data):
            if not data[pos : pos + 6].isdigit():
                break
            try:
                mode = int(data[pos + 14 : pos + 20], 8)
                size = int(data[pos + 59 : pos + 70], 8)
                namesize = int(data[pos + 70 : pos + 76], 8)
            except ValueError:
                break
            name = data[pos + 76 : pos + 76 + namesize - 1].decode("utf-8", "replace")
            body = pos + 76 + namesize
            payload = data[body : body + size]
            pos = body + size
            pos += (-pos) % 2
            if name == "TRAILER!!!":
                return
            yield CpioEntry(name, mode, size, payload)


@dataclass
class BootImage:
    path: str
    file_size: int
    sha1: str
    sha256: str
    magic: bytes
    header_version: int
    header_size: int
    page_size: int
    os_version: tuple[int, int, int, int] | None
    os_version_raw: int
    name: str
    cmdline: str
    extra_cmdline: str | None
    kernel: Section
    ramdisk: Section
    second: Section | None = None
    recovery_dtbo: Section | None = None
    dtb: Section | None = None
    signature_size: int = 0
    avb_footer: AvbFooter | None = None
    notes: list[str] = field(default_factory=list)
    _raw: bytes | None = field(default=None, repr=False)

    # ------------------------------------------------------------- identity

    @property
    def os_version_str(self) -> str:
        if not self.os_version:
            return "unknown"
        major, minor, patch, _ = self.os_version
        return f"{major}.{minor}.{patch}"

    @property
    def kernel_version(self) -> str | None:
        """Kernel release string, read from the kernel image's own version banner."""

        for blob in (self.kernel.effective, self._raw):
            if not blob:
                continue
            match = re.search(rb"Linux version (\d+\.\d+(?:\.\d+)?)", blob[: 96 * 1024 * 1024])
            if match:
                return match.group(1).decode("ascii", "replace")
        return None

    @property
    def kernel_banner(self) -> str | None:
        for blob in (self.kernel.effective, self._raw):
            if not blob:
                continue
            match = re.search(rb"Linux version ([^\x00]{10,240})", blob[: 96 * 1024 * 1024])
            if match:
                return match.group(1).decode("utf-8", "replace")
        return None

    def ramdisk_entries(self) -> list[CpioEntry]:
        """List the ramdisk contents, transparently unwrapping a nested gzip."""

        data = self.ramdisk.unpacked
        if data is None:
            return []
        if data[:2] == b"\x1f\x8b":
            inner, _ = decompress(data, "gzip")
            if inner:
                data = inner
        return list(iter_cpio(data))

    def ramdisk_file(self, name: str) -> bytes | None:
        for entry in self.ramdisk_entries():
            if entry.name == name:
                return entry.data
        return None

    # ------------------------------------------------------------ reporting

    def as_dict(self, *, include_markers: bool = True) -> dict:
        out = {
            "path": self.path,
            "file_size": self.file_size,
            "sha1": self.sha1,
            "sha256": self.sha256,
            "header_version": self.header_version,
            "header_size": self.header_size,
            "page_size": self.page_size,
            "boot_image_os_version": self.os_version_str,
            "kernel_version": self.kernel_version,
            "kernel_banner": self.kernel_banner,
            "cmdline": self.cmdline,
            "name": self.name,
            "kernel": self.kernel.as_dict(),
            "ramdisk": self.ramdisk.as_dict(),
            "recovery_dtbo": self.recovery_dtbo.as_dict() if self.recovery_dtbo else None,
            "dtb": self.dtb.as_dict() if self.dtb else None,
            "signature_size": self.signature_size,
            "avb_footer": self.avb_footer.as_dict() if self.avb_footer else None,
            "notes": self.notes,
        }
        if include_markers:
            out["identity"] = self.identity()
            out["patches"] = self.patch_markers()
        return out

    def identity(self) -> dict:
        """Device and build identity taken from the ramdisk's bootimage build.prop."""

        facts: dict = {}
        props: dict[str, str] = {}
        for entry in self.ramdisk_entries():
            if entry.name.endswith("build.prop") and b"ro.product.bootimage" in entry.data:
                for line in entry.data.decode("utf-8", "replace").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, _, value = line.partition("=")
                    props[key.strip()] = value.strip()
        wanted = (
            "ro.product.bootimage.brand",
            "ro.product.bootimage.device",
            "ro.product.bootimage.model",
            "ro.product.bootimage.name",
            "ro.bootimage.build.fingerprint",
            "ro.bootimage.build.id",
            "ro.bootimage.build.version.incremental",
            "ro.bootimage.build.version.release",
            "ro.bootimage.build.version.release_or_codename",
            "ro.bootimage.build.version.sdk",
            "ro.bootimage.build.date",
            "ro.bootimage.build.date.utc",
        )
        for key in wanted:
            if key not in props:
                continue
            short = key
            for prefix in ("ro.product.bootimage.", "ro.bootimage."):
                if short.startswith(prefix):
                    short = short[len(prefix) :]
                    break
            facts[short] = props[key]
        sdk = props.get("ro.bootimage.build.version.sdk")
        if sdk and sdk.isdigit():
            facts["android_release_from_sdk"] = android_release_name(int(sdk))
        return facts

    def patch_markers(self) -> dict:
        """Look for Magisk, KernelSU and APatch traces in the ramdisk."""

        entries = self.ramdisk_entries()
        names = [e.name for e in entries]
        found: dict = {"magisk": None, "kernelsu": None, "apatch": None}
        magisk: dict = {}
        for entry in entries:
            if entry.name == ".backup/.magisk":
                config: dict[str, str] = {}
                for line in entry.data.decode("utf-8", "replace").splitlines():
                    if "=" in line:
                        key, _, value = line.partition("=")
                        config[key.strip()] = value.strip()
                magisk["config"] = config
            elif entry.name == ".backup/.rmlist":
                magisk["rmlist"] = entry.data.decode("utf-8", "replace").split()
            elif entry.name == "init":
                if b"magisk" in entry.data:
                    magisk["magiskinit"] = True
                    magisk["magiskinit_size"] = entry.size
            elif entry.name.startswith("overlay.d/sbin/"):
                magisk.setdefault("overlay", []).append(entry.name)
        if magisk:
            found["magisk"] = magisk

        if any(n.startswith("kernelsu") or n == "ksud" for n in names) or any(
            "KernelSU" in e.name for e in entries
        ):
            found["kernelsu"] = {"entries": [n for n in names if "kernelsu" in n.lower()]}
        if any("apatch" in n.lower() for n in names):
            found["apatch"] = {"entries": [n for n in names if "apatch" in n.lower()]}

        # Kernel level markers need the kernel blob, which is decompressed on demand.
        kernel_blob = self.kernel.effective
        if kernel_blob:
            for label, pattern in (
                ("kernelsu", rb"KernelSU"),
                ("apatch", rb"KernelPatch"),
            ):
                if re.search(pattern, kernel_blob):
                    entry = found.setdefault(label, {}) or {}
                    entry["kernel_string"] = True
                    found[label] = entry
        return found


@dataclass
class VendorRamdisk:
    """One entry of the vendor ramdisk table in a vendor boot image."""

    name: str
    offset: int
    size: int
    section: Section | None = None

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "offset": self.offset,
            "size": self.size,
            "compression": self.section.compression if self.section else None,
            "unpacked_size": self.section.unpacked_size if self.section else None,
            "sha256": self.section.sha256 if self.section else None,
        }


@dataclass
class VendorBootImage:
    """An Android vendor boot image, header v3 or v4.

    The layout is different from a normal boot image: a fixed vendor ramdisk
    followed by a table of additional ramdisk fragments, then dtb and, in v4,
    a recovery dtbo. The kernel is not here; it lives in the boot partition.
    """

    path: str
    file_size: int
    sha1: str
    sha256: str
    header_version: int
    page_size: int
    kernel_addr: int
    ramdisk_addr: int
    vendor_ramdisk_size: int
    cmdline: str
    tags_addr: int
    name: str
    header_size: int
    dtb_size: int
    dtb_addr: int
    vendor_ramdisk: Section | None = None
    ramdisks: list[VendorRamdisk] = field(default_factory=list)
    dtb: Section | None = None
    recovery_dtbo: Section | None = None
    avb_footer: AvbFooter | None = None
    notes: list[str] = field(default_factory=list)

    def ramdisk_entries(self) -> list[CpioEntry]:
        """List the concatenated vendor ramdisk contents.

        A vendor ramdisk is a sequence of cpio archives run together, so the
        walker is run repeatedly until it stops finding archives.
        """

        section = self.vendor_ramdisk
        if section is None or section.unpacked is None:
            return []
        data = section.unpacked
        entries: list[CpioEntry] = []
        pos = 0
        while pos < len(data):
            window = data[pos:]
            if window[:6] not in (CPIO_NEWC, CPIO_CRC, CPIO_ODC):
                break
            before = len(entries)
            consumed = 0
            # iter_cpio stops at TRAILER!!!, so capture how far it got by
            # re-walking the slice and summing the entry extents.
            for entry in iter_cpio(window):
                entries.append(entry)
            if len(entries) == before:
                break
            # Find the next archive start after this one's trailer.
            trailer = window.find(b"TRAILER!!!")
            if trailer < 0:
                break
            consumed = trailer + len(b"TRAILER!!!")
            consumed += (-consumed) % 4
            # The trailer record itself is 110 bytes of header before the name.
            consumed += 110
            consumed += (-consumed) % 4
            pos += max(consumed, 1)
        return entries

    def as_dict(self) -> dict:
        return {
            "path": self.path,
            "kind": "vendor_boot",
            "file_size": self.file_size,
            "sha1": self.sha1,
            "sha256": self.sha256,
            "header_version": self.header_version,
            "page_size": self.page_size,
            "header_size": self.header_size,
            "name": self.name,
            "cmdline": self.cmdline,
            "kernel_addr": hex(self.kernel_addr),
            "ramdisk_addr": hex(self.ramdisk_addr),
            "tags_addr": hex(self.tags_addr),
            "dtb_addr": hex(self.dtb_addr),
            "vendor_ramdisk": {
                "size": self.vendor_ramdisk_size,
                "compression": self.vendor_ramdisk.compression if self.vendor_ramdisk else None,
                "unpacked_size": self.vendor_ramdisk.unpacked_size if self.vendor_ramdisk else None,
                "sha256": self.vendor_ramdisk.sha256 if self.vendor_ramdisk else None,
            },
            "ramdisk_table": [r.as_dict() for r in self.ramdisks],
            "dtb_size": self.dtb_size,
            "recovery_dtbo": None
            if not self.recovery_dtbo
            else {"size": self.recovery_dtbo.size, "sha256": self.recovery_dtbo.sha256},
            "avb_footer": self.avb_footer.as_dict() if self.avb_footer else None,
            "notes": self.notes,
        }


def is_vendor_boot(path: str) -> bool:
    with open(path, "rb") as fh:
        return fh.read(8) == VENDOR_BOOT_MAGIC


def load_vendor_boot(path: str, *, read_ramdisk: bool = True) -> VendorBootImage:
    """Parse an Android vendor boot image. Read only."""

    file_size = os.path.getsize(path)
    with open(path, "rb") as fh:
        if file_size <= _SIZE_LIMIT_FOR_DEEP_SCAN:
            raw = fh.read()
        else:
            raw = fh.read(4096)
    header = raw[:4096]
    if header[:8] != VENDOR_BOOT_MAGIC:
        raise BootImageError(f"{path}: does not start with the VNDRBOOT magic")
    if file_size > _SIZE_LIMIT_FOR_DEEP_SCAN:
        raw = header

    notes: list[str] = []
    header_version = struct.unpack_from("<I", header, 8)[0]
    page_size = struct.unpack_from("<I", header, 12)[0] or 4096
    kernel_addr = struct.unpack_from("<I", header, 16)[0]
    ramdisk_addr = struct.unpack_from("<I", header, 20)[0]
    vendor_ramdisk_size = struct.unpack_from("<I", header, 24)[0]
    cmdline = _cstr(header[28 : 28 + 2048])
    tags_addr = struct.unpack_from("<I", header, 2076)[0]
    name = _cstr(header[2080 : 2080 + 16])
    header_size = struct.unpack_from("<I", header, 2096)[0]
    dtb_size = struct.unpack_from("<I", header, 2100)[0]
    dtb_addr = struct.unpack_from("<Q", header, 2104)[0]

    off = page_size
    vendor_ramdisk = Section("vendor_ramdisk", off, vendor_ramdisk_size)
    off += _pages(vendor_ramdisk_size, page_size) * page_size

    ramdisks: list[VendorRamdisk] = []
    dtb: Section | None = None
    recovery_dtbo: Section | None = None

    if header_version >= 4:
        # AOSP declares the table offset as a u64, but the images this phone
        # ships store only the low 32 bits there and leave the high word unused,
        # which makes the u64 read nonsense. Take the u64 when it is plausible
        # and fall back to the low word when it is not.
        table_entry_num = struct.unpack_from("<I", header, 2112)[0]
        table_entry_size = struct.unpack_from("<I", header, 2116)[0]
        table_offset = struct.unpack_from("<Q", header, 2120)[0]
        if table_offset > file_size:
            low = struct.unpack_from("<I", header, 2120)[0]
            if low <= file_size:
                notes.append(
                    f"ramdisk table offset read as 32 bit: header u64 value {table_offset} "
                    f"is past the end of the file, low word {low} is not"
                )
                table_offset = low
        # A ramdisk table entry is 108 bytes: ramdisk_size u32, ramdisk_offset
        # u64, ramdisk_type u32, ramdisk_name[32], board_id[16 x u32]. The table
        # only makes sense if its offset lands inside the file and every entry
        # it claims is readable, so that is checked rather than assumed.
        table_usable = (
            table_entry_num > 0
            and table_entry_size >= 108
            and 0 < table_offset < file_size
            and table_offset + table_entry_num * table_entry_size <= file_size
        )
        if table_entry_num and not table_usable:
            notes.append(
                f"ramdisk table metadata is inconsistent (entries={table_entry_num}, "
                f"entry size={table_entry_size}, offset={table_offset}); ignoring it"
            )
        if table_usable:
            for index in range(table_entry_num):
                base = table_offset + index * table_entry_size
                r_size = struct.unpack_from("<I", raw, base)[0]
                r_offset = struct.unpack_from("<Q", raw, base + 4)[0]
                r_type = struct.unpack_from("<I", raw, base + 12)[0]
                r_name = _cstr(raw[base + 16 : base + 48])
                entry = VendorRamdisk(
                    name=r_name or f"type_{r_type}",
                    offset=r_offset,
                    size=r_size,
                )
                if raw and 0 < r_offset < file_size:
                    blob = raw[r_offset : r_offset + r_size]
                    section = Section(entry.name, r_offset, len(blob))
                    section.data = blob
                    section.compression = detect_compression(blob)
                    if read_ramdisk and blob:
                        if section.compression is None:
                            section.unpacked = blob
                        else:
                            payload, note = decompress(blob, section.compression)
                            if payload is not None:
                                section.unpacked = payload
                            else:
                                section.note = note
                    entry.section = section
                    off = max(off, r_offset + _pages(len(blob), page_size) * page_size)
                ramdisks.append(entry)

        # Find the device tree by its own magic, from the end of the vendor
        # ramdisk onward. This is more reliable than either the table offset or
        # dtb_size, both of which are unreliable on this platform.
        fdt_magic = b"\xd0\r\xfe\xed"
        search_from = 4096 + _pages(vendor_ramdisk_size, page_size) * page_size
        found = raw.find(fdt_magic, search_from) if raw else -1
        if found >= 0:
            off = found
        dtb = Section("dtb", off, dtb_size) if dtb_size else None
    elif dtb_size:
        dtb = Section("dtb", off, dtb_size)
        off += _pages(dtb_size, page_size) * page_size

    image = VendorBootImage(
        path=path,
        file_size=file_size,
        sha1=_sha1_of_file(path),
        sha256=_sha256_of_file(path),
        header_version=header_version,
        page_size=page_size,
        kernel_addr=kernel_addr,
        ramdisk_addr=ramdisk_addr,
        vendor_ramdisk_size=vendor_ramdisk_size,
        cmdline=cmdline,
        tags_addr=tags_addr,
        name=name,
        header_size=header_size,
        dtb_size=dtb_size,
        dtb_addr=dtb_addr,
        vendor_ramdisk=vendor_ramdisk,
        ramdisks=ramdisks,
        dtb=dtb,
        recovery_dtbo=recovery_dtbo,
        avb_footer=_parse_avb_footer(raw) if raw else None,
        notes=notes,
    )

    # The dtb_size field in the header is not trustworthy on this platform: for
    # the images here it claims roughly four times the real size. When the blob
    # at the dtb offset is a flattened device tree, its own header states the
    # real size, so use that and record the disagreement.
    if dtb is not None and dtb.size and raw:
        if raw[dtb.offset : dtb.offset + 4] == b"\xd0\r\xfe\xed" and dtb.offset + 8 <= len(raw):
            real = struct.unpack_from(">I", raw, dtb.offset + 4)[0]
            if 0 < real <= len(raw) - dtb.offset and real != dtb.size:
                notes.append(
                    f"dtb: header says {dtb.size} bytes but the device tree header says {real}; "
                    "using the device tree value"
                )
                dtb.size = real

    for section in (vendor_ramdisk, dtb):
        if section is None or section.size == 0 or not raw:
            continue
        blob = raw[section.offset : section.offset + section.size]
        if len(blob) != section.size:
            notes.append(
                f"{section.name}: header declares {section.size} bytes but the file holds {len(blob)}"
            )
            section.size = len(blob)
        section.data = blob
        section.compression = detect_compression(blob)
        if read_ramdisk and section.name == "vendor_ramdisk" and blob:
            if section.compression is None:
                section.unpacked = blob
            else:
                payload, note = decompress(blob, section.compression)
                if payload is not None:
                    section.unpacked = payload
                else:
                    section.note = note
                    notes.append(f"vendor_ramdisk: {note}")
    return image


def _sha1_of_file(path: str, chunk: int = 1 << 20) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def _sha256_of_file(path: str, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def _parse_avb_footer(raw: bytes) -> AvbFooter | None:
    if len(raw) < 64:
        return None
    footer = raw[-64:]
    if footer[:4] != AVB_FOOTER_MAGIC:
        return None
    version = struct.unpack_from(">II", footer, 4)
    original_image_size = struct.unpack_from(">Q", footer, 12)[0]
    vbmeta_offset = struct.unpack_from(">Q", footer, 20)[0]
    vbmeta_size = struct.unpack_from(">Q", footer, 28)[0]
    return AvbFooter(
        (version[0], version[1]), original_image_size, vbmeta_offset, vbmeta_size
    )


def load(
    path: str,
    *,
    read_ramdisk: bool = True,
    read_kernel: bool = False,
    read_second: bool = False,
) -> BootImage:
    """Parse a boot image from disk. Read only, never touches a device."""

    file_size = os.path.getsize(path)
    with open(path, "rb") as fh:
        header = fh.read(4096)
    if len(header) < 44 or header[:8] != BOOT_MAGIC:
        raise BootImageError(f"{path}: does not start with the ANDROID! magic")

    notes: list[str] = []
    header_version = struct.unpack_from("<I", header, _OFF_HEADER_VERSION)[0]

    if header_version >= 3:
        kernel_size = struct.unpack_from("<I", header, _OFF_KERNEL_SIZE)[0]
        ramdisk_size = struct.unpack_from("<I", header, _OFF_RAMDISK_SIZE)[0]
        os_version_raw = struct.unpack_from("<I", header, _OFF_OS_VERSION)[0]
        header_size = struct.unpack_from("<I", header, _OFF_HEADER_SIZE)[0]
        cmdline = _cstr(header[_OFF_CMDLINE : _OFF_CMDLINE + _CMDLINE_LEN])
        page_size = 4096
        name = ""
        extra_cmdline = None
    elif header_version in (1, 2):
        kernel_size = struct.unpack_from("<I", header, _OFF_KERNEL_SIZE)[0]
        ramdisk_size = struct.unpack_from("<I", header, 16)[0]
        header_size = struct.unpack_from("<I", header, _OFF_HEADER_SIZE)[0]
        os_version_raw = struct.unpack_from("<I", header, 44)[0]
        page_size = struct.unpack_from("<I", header, 36)[0] or 4096
        name = _cstr(header[48:64])
        cmdline = _cstr(header[64:576])
        extra_cmdline = _cstr(header[608:1632])
    else:
        (
            kernel_size,
            _kernel_addr,
            ramdisk_size,
            _ramdisk_addr,
            second_size,
            _second_addr,
            _tags_addr,
            page_size,
            _hv,
            os_version_raw,
        ) = struct.unpack_from("<10I", header, 8)
        header_size = 0
        name = _cstr(header[48:64])
        cmdline = _cstr(header[64:576])
        extra_cmdline = _cstr(header[608:1632])

    if page_size <= 0:
        page_size = 4096
        notes.append("page size was zero in the header, assumed 4096")

    os_version = (
        (os_version_raw >> 25) & 0x7F,
        (os_version_raw >> 18) & 0x7F,
        (os_version_raw >> 11) & 0x7F,
        os_version_raw & 0x7FF,
    )

    if header_version >= 3:
        # v3 and v4 always use 4 KiB pages and place recovery_dtbo after the ramdisk.
        off = page_size
        kernel = Section("kernel", off, kernel_size)
        off += _pages(kernel_size, page_size) * page_size
        ramdisk = Section("ramdisk", off, ramdisk_size)
        off += _pages(ramdisk_size, page_size) * page_size
        second = None
        recovery_dtbo = None
        dtb = None
        signature_size = 0
        if header_version >= 4:
            dtbo_size = struct.unpack_from("<I", header, _OFF_RECOVERY_DTBO_SIZE)[0]
            dtbo_offset = struct.unpack_from("<Q", header, _OFF_RECOVERY_DTBO_OFFSET)[0]
            signature_size = struct.unpack_from("<I", header, _OFF_SIGNATURE_SIZE)[0]
            if dtbo_size:
                recovery_dtbo = Section("recovery_dtbo", dtbo_offset, dtbo_size)
                off += _pages(dtbo_size, page_size) * page_size
            dtb_size = struct.unpack_from("<I", header, _OFF_DTB_SIZE)[0]
            if dtb_size:
                dtb = Section("dtb", off, dtb_size)
    else:
        off = page_size
        kernel = Section("kernel", off, kernel_size)
        off += _pages(kernel_size, page_size) * page_size
        ramdisk = Section("ramdisk", off, ramdisk_size)
        off += _pages(ramdisk_size, page_size) * page_size
        second = Section("second", off, second_size) if second_size else None
        recovery_dtbo = None
        dtb = None
        signature_size = 0

    raw: bytes | None = None
    if file_size <= _SIZE_LIMIT_FOR_DEEP_SCAN and (
        read_ramdisk or read_kernel or read_second
    ):
        with open(path, "rb") as fh:
            raw = fh.read()

    image = BootImage(
        path=path,
        file_size=file_size,
        sha1=_sha1_of_file(path),
        sha256=_sha256_of_file(path),
        magic=BOOT_MAGIC,
        header_version=header_version,
        header_size=header_size,
        page_size=page_size,
        os_version=os_version,
        os_version_raw=os_version_raw,
        name=name,
        cmdline=cmdline,
        extra_cmdline=extra_cmdline,
        kernel=kernel,
        ramdisk=ramdisk,
        second=second,
        recovery_dtbo=recovery_dtbo,
        dtb=dtb,
        signature_size=signature_size,
        notes=notes,
        _raw=raw,
    )

    targets: list[tuple[Section, bool]] = [
        (image.kernel, read_kernel),
        (image.ramdisk, read_ramdisk),
    ]
    if image.recovery_dtbo:
        targets.append((image.recovery_dtbo, read_kernel))
    if image.dtb:
        targets.append((image.dtb, read_kernel))
    if image.second:
        targets.append((image.second, read_second))

    if raw is not None:
        for section, want_data in targets:
            if section.size == 0:
                continue
            blob = raw[section.offset : section.offset + section.size]
            if len(blob) != section.size:
                image.notes.append(
                    f"{section.name}: header declares {section.size} bytes but the file holds {len(blob)}"
                )
                section.size = len(blob)
            section.data = blob
            section.compression = detect_compression(blob)
            if not want_data:
                continue
            if section.compression is None:
                # Uncompressed: the payload is usable as is. A kernel is normally a raw
                # arm64 Image or an x86 bzImage, and a ramdisk may be a bare cpio archive.
                section.unpacked = blob
                continue
            payload, note = decompress(blob, section.compression)
            if payload is not None:
                section.unpacked = payload
            else:
                section.note = note
                image.notes.append(f"{section.name}: {note}")

    image.avb_footer = _parse_avb_footer(raw) if raw is not None else None
    return image


def sha256_file(path: str, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()
