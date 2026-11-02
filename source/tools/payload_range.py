#!/usr/bin/env python3
"""List and extract partitions from an Android OTA payload.bin, over HTTP ranges or from a file.

The payload is an update_engine payload ("CrAU"): a fixed header, a protobuf
manifest (DeltaArchiveManifest) listing every partition and the byte range of
each operation's data, then the data blobs. Because the manifest carries
offsets and lengths, a single partition can be fetched with range requests
instead of downloading the whole payload.

The manifest is standard AOSP. Field numbers are those of
system/update_engine/update_metadata.proto (LineageOS lineage-23.0), corrected
on 2026-10-17 for review finding R-15. The earlier version of this file read
field 4 (src_extents) as the SHA-256, field 6 (dst_extents) as a "source
extent" and field 7 (dst_length, a varint) as a nested message, and called
the manifest non-AOSP. It was not; the field map was wrong.

  DeltaArchiveManifest  block_size=3  minor_version=12  partitions=13  max_timestamp=14
  PartitionUpdate       partition_name=1  new_partition_info=7  operations=8
  PartitionInfo         size=1  hash=2
  InstallOperation      type=1 data_offset=2 data_length=3 src_extents=4 src_length=5
                        dst_extents=6 dst_length=7 data_sha256_hash=8 src_sha256_hash=9
  Extent                start_block=1  num_blocks=2

Extraction writes every operation at its dst_extents (block_size * start_block),
verifies each data blob against data_sha256_hash, and verifies the finished
image against new_partition_info.hash (the SHA-256 the payload's producer
recorded for the whole partition). An image that fails that check is left as
<out>.unverified and the tool exits non-zero.

Only full payloads can be extracted: SOURCE_COPY and the *DIFF operations need
the old partition image.

Read only with respect to the source. It writes only the output file.

Usage:
    python tools/payload_range.py --list <payload_url | file.bin | ota.zip>
    python tools/payload_range.py --extract boot --out boot.img <payload_url | file.bin | ota.zip>

For a URL that points at an OTA zip, pass the offset of payload.bin inside the
zip as --base (tools/ziprange.py). For a local .zip the offset is found
automatically.
"""

from __future__ import annotations

import argparse
import bz2
import hashlib
import lzma
import os
import struct
import sys
import urllib.request
import zipfile

MAGIC = b"CrAU"

# DeltaArchiveManifest
F_BLOCK_SIZE = 3
F_MINOR_VERSION = 12
F_PARTITIONS = 13
F_MAX_TIMESTAMP = 14
# PartitionUpdate
F_PARTITION_NAME = 1
F_NEW_PARTITION_INFO = 7
F_OPERATIONS = 8
# PartitionInfo
F_INFO_SIZE = 1
F_INFO_HASH = 2
# InstallOperation
F_OP_TYPE = 1
F_OP_DATA_OFFSET = 2
F_OP_DATA_LENGTH = 3
F_OP_SRC_EXTENTS = 4
F_OP_SRC_LENGTH = 5
F_OP_DST_EXTENTS = 6
F_OP_DST_LENGTH = 7
F_OP_DATA_SHA256 = 8
F_OP_SRC_SHA256 = 9
# Extent
F_EXTENT_START_BLOCK = 1
F_EXTENT_NUM_BLOCKS = 2

# InstallOperation.Type. There is no ZSTD type in the AOSP proto; 10 is BROTLI_BSDIFF.
OP_NAMES = {
    0: "REPLACE", 1: "REPLACE_BZ", 2: "MOVE", 3: "BSDIFF", 4: "SOURCE_COPY",
    5: "SOURCE_BSDIFF", 6: "ZERO", 7: "DISCARD", 8: "REPLACE_XZ", 9: "PUFFDIFF",
    10: "BROTLI_BSDIFF", 11: "ZUCCHINI", 12: "LZ4DIFF_BSDIFF", 13: "LZ4DIFF_PUFFDIFF",
}
OP_REPLACE, OP_REPLACE_BZ, OP_ZERO, OP_DISCARD, OP_REPLACE_XZ = 0, 1, 6, 7, 8
OPS_WITH_DATA = {OP_REPLACE, OP_REPLACE_BZ, OP_REPLACE_XZ}
OPS_ZERO = {OP_ZERO, OP_DISCARD}


class PayloadError(Exception):
    """Raised when the payload cannot be understood or does not verify."""


# ------------------------------------------------------------------ protobuf

def _read_varint(buf: bytes, pos: int) -> tuple[int, int]:
    result = shift = 0
    while True:
        if pos >= len(buf):
            raise PayloadError("varint runs past the end of the buffer")
        byte = buf[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, pos
        shift += 7
        if shift > 63:
            raise PayloadError("varint is too long")


def _fields(buf: bytes):
    """Yield (field_number, wire_type, value) for one message. Groups are not used by AOSP."""
    pos = 0
    while pos < len(buf):
        key, pos = _read_varint(buf, pos)
        field, wire = key >> 3, key & 7
        if wire == 0:
            value, pos = _read_varint(buf, pos)
        elif wire == 2:
            length, pos = _read_varint(buf, pos)
            if pos + length > len(buf):
                raise PayloadError(f"field {field} runs past the end of its message")
            value = buf[pos:pos + length]
            pos += length
        elif wire == 5:
            value = struct.unpack_from("<I", buf, pos)[0]
            pos += 4
        elif wire == 1:
            value = struct.unpack_from("<Q", buf, pos)[0]
            pos += 8
        else:
            raise PayloadError(f"unexpected protobuf wire type {wire} (field {field}); "
                               "the manifest is not what this decoder expects")
        yield field, wire, value


def _extent(buf: bytes) -> tuple[int, int]:
    start = num = 0
    for f, w, v in _fields(buf):
        if f == F_EXTENT_START_BLOCK and w == 0:
            start = v
        elif f == F_EXTENT_NUM_BLOCKS and w == 0:
            num = v
    return start, num


# ------------------------------------------------------------------ model

class Operation:
    def __init__(self):
        self.op_type = 0
        self.data_offset = 0
        self.data_length = 0
        self.src_extents: list[tuple[int, int]] = []
        self.dst_extents: list[tuple[int, int]] = []
        self.dst_length: int | None = None
        self.sha256: bytes | None = None

    @property
    def name(self) -> str:
        return OP_NAMES.get(self.op_type, f"op{self.op_type}")

    def __repr__(self) -> str:
        return f"<{self.name} data={self.data_offset}+{self.data_length} dst={self.dst_extents}>"


class Partition:
    def __init__(self, name: str):
        self.name = name
        self.size: int | None = None
        self.hash: bytes | None = None
        self.operations: list[Operation] = []

    def __repr__(self) -> str:
        return f"<Partition {self.name} size={self.size} ops={len(self.operations)}>"


class Manifest:
    def __init__(self):
        self.block_size = 4096        # proto default
        self.minor_version = 0
        self.max_timestamp = None
        self.partitions: list[Partition] = []


def parse_manifest(buf: bytes) -> Manifest:
    man = Manifest()
    for field, wire, value in _fields(buf):
        if field == F_BLOCK_SIZE and wire == 0:
            man.block_size = value
        elif field == F_MINOR_VERSION and wire == 0:
            man.minor_version = value
        elif field == F_MAX_TIMESTAMP and wire == 0:
            man.max_timestamp = value
        elif field == F_PARTITIONS and wire == 2:
            part = Partition("")
            for pf, pw, pv in _fields(value):
                if pf == F_PARTITION_NAME and pw == 2:
                    part.name = pv.decode("utf-8", "replace")
                elif pf == F_NEW_PARTITION_INFO and pw == 2:
                    for inf, iw, iv in _fields(pv):
                        if inf == F_INFO_SIZE and iw == 0:
                            part.size = iv
                        elif inf == F_INFO_HASH and iw == 2:
                            part.hash = bytes(iv)
                elif pf == F_OPERATIONS and pw == 2:
                    op = Operation()
                    for of, ow, ov in _fields(pv):
                        if of == F_OP_TYPE and ow == 0:
                            op.op_type = ov
                        elif of == F_OP_DATA_OFFSET and ow == 0:
                            op.data_offset = ov
                        elif of == F_OP_DATA_LENGTH and ow == 0:
                            op.data_length = ov
                        elif of == F_OP_SRC_EXTENTS and ow == 2:
                            op.src_extents.append(_extent(ov))
                        elif of == F_OP_DST_EXTENTS and ow == 2:
                            op.dst_extents.append(_extent(ov))
                        elif of == F_OP_DST_LENGTH and ow == 0:
                            op.dst_length = ov
                        elif of == F_OP_DATA_SHA256 and ow == 2:
                            op.sha256 = bytes(ov)
                    part.operations.append(op)
            if part.name:
                man.partitions.append(part)
    return man


# ------------------------------------------------------------------ I/O

class Source:
    """Byte ranges of payload.bin, from a URL, a payload file, or a local OTA zip."""

    def __init__(self, location: str, base: int | None = None):
        self.location = location
        self.is_url = location.startswith(("http://", "https://"))
        if base is None:
            base = 0
            if not self.is_url and location.lower().endswith(".zip"):
                base = zip_member_offset(location, "payload.bin")
        self.base = base
        self._fh = None if self.is_url else open(location, "rb")

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def read(self, start: int, length: int) -> bytes:
        if length <= 0:
            return b""
        if self.is_url:
            req = urllib.request.Request(self.location)
            req.add_header("Range", f"bytes={self.base + start}-{self.base + start + length - 1}")
            req.add_header("User-Agent", "Mozilla/5.0 (compatible; rmx3301-offline-tooling)")
            with urllib.request.urlopen(req, timeout=300) as resp:
                data = resp.read()
        else:
            self._fh.seek(self.base + start)
            data = self._fh.read(length)
        if len(data) != length:
            raise PayloadError(f"wanted {length} bytes at {start}, got {len(data)}")
        return data


def zip_member_offset(path: str, member: str) -> int:
    """Offset of a STORED member's data inside a local zip."""
    with zipfile.ZipFile(path) as z:
        info = z.getinfo(member)
        if info.compress_type != zipfile.ZIP_STORED:
            raise PayloadError(f"{member} is compressed inside the zip; extract it first")
    with open(path, "rb") as f:
        f.seek(info.header_offset)
        head = f.read(30)
        if head[:4] != b"PK\x03\x04":
            raise PayloadError("bad local file header")
        name_len, extra_len = struct.unpack("<HH", head[26:30])
    return info.header_offset + 30 + name_len + extra_len


def read_header(src: Source) -> tuple[int, int, int]:
    """Return (major_version, manifest_size, metadata_signature_size)."""
    head = src.read(0, 24)
    if head[:4] != MAGIC:
        raise PayloadError(f"payload magic is {head[:4]!r}, expected {MAGIC!r}")
    major = struct.unpack_from(">Q", head, 4)[0]
    manifest_size = struct.unpack_from(">Q", head, 12)[0]
    sig_size = struct.unpack_from(">I", head, 20)[0] if major >= 2 else 0
    if manifest_size <= 0 or manifest_size > 64 * 1024 * 1024:
        raise PayloadError(f"implausible manifest size {manifest_size}")
    return major, manifest_size, sig_size


def load_manifest(src: Source) -> tuple[Manifest, int]:
    major, manifest_size, sig_size = read_header(src)
    header_len = 24 if major >= 2 else 20
    manifest = parse_manifest(src.read(header_len, manifest_size))
    return manifest, header_len + manifest_size + sig_size


# ------------------------------------------------------------------ extraction

def _decompress(op: Operation, blob: bytes) -> bytes:
    if op.op_type == OP_REPLACE:
        return blob
    if op.op_type == OP_REPLACE_XZ:
        return lzma.decompress(blob)
    if op.op_type == OP_REPLACE_BZ:
        return bz2.decompress(blob)
    raise PayloadError(f"unsupported operation {op.name}")


def extract_partition(src: Source, man: Manifest, part: Partition, data_start: int, out_path: str,
                      progress=None) -> dict:
    """Write one partition and verify it. Returns a summary dict; raises PayloadError on failure."""
    bs = man.block_size
    unsupported = sorted({op.name for op in part.operations
                          if op.op_type not in OPS_WITH_DATA | OPS_ZERO})
    if unsupported:
        raise PayloadError(f"partition {part.name} uses {', '.join(unsupported)}, which needs the old "
                           "partition image (an incremental payload); it cannot be rebuilt from the payload alone")
    if part.size is None:
        raise PayloadError(f"partition {part.name} has no new_partition_info.size")

    tmp = out_path + ".part"
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    counts: dict = {}
    covered = 0
    with open(tmp, "wb") as fh:
        fh.truncate(part.size)
        for n, op in enumerate(part.operations, 1):
            counts[op.name] = counts.get(op.name, 0) + 1
            span = sum(num for _, num in op.dst_extents) * bs
            covered += span
            if op.op_type in OPS_ZERO:
                for start, num in op.dst_extents:
                    fh.seek(start * bs)
                    fh.write(b"\x00" * (num * bs))
            else:
                blob = src.read(data_start + op.data_offset, op.data_length)
                if op.sha256 is not None and hashlib.sha256(blob).digest() != op.sha256:
                    raise PayloadError(f"operation {n}: data_sha256_hash mismatch")
                data = _decompress(op, blob)
                if len(data) != span:
                    raise PayloadError(f"operation {n}: {len(data):,} bytes for {span:,} bytes of dst_extents")
                pos = 0
                for start, num in op.dst_extents:
                    fh.seek(start * bs)
                    fh.write(data[pos:pos + num * bs])
                    pos += num * bs
            if progress:
                progress(n, len(part.operations))
        end = fh.seek(0, os.SEEK_END)
    if end != part.size:
        raise PayloadError(f"{part.name}: dst_extents reach {end:,} bytes, partition is {part.size:,}")

    h = hashlib.sha256()
    with open(tmp, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    digest = h.digest()
    summary = {"size": part.size, "covered": covered, "ops": counts, "sha256": digest.hex(),
               "expected": part.hash.hex() if part.hash else None}
    if part.hash is None:
        summary["verified"] = None
        os.replace(tmp, out_path + ".unverified")
        raise PayloadError(f"{part.name}: the manifest records no partition hash; "
                           f"left as {out_path}.unverified")
    if digest != part.hash:
        summary["verified"] = False
        os.replace(tmp, out_path + ".unverified")
        raise PayloadError(f"{part.name}: sha256 {digest.hex()} != manifest {part.hash.hex()}; "
                           f"left as {out_path}.unverified")
    summary["verified"] = True
    os.replace(tmp, out_path)
    return summary


# ------------------------------------------------------------------ CLI

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("source", help="payload URL, payload.bin, or a local OTA .zip")
    parser.add_argument("--base", type=int, default=None, help="offset of payload.bin inside a remote zip")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--extract", metavar="PARTITION")
    parser.add_argument("--out")
    args = parser.parse_args(argv)

    try:
        src = Source(args.source, args.base)
    except Exception as exc:  # noqa: BLE001 - report every failure, never swallow it
        print(f"error: {exc}", file=sys.stderr)
        return 3
    with src:
        return _run(args, src)


def _run(args, src: Source) -> int:
    try:
        man, data_start = load_manifest(src)
    except Exception as exc:  # noqa: BLE001 - report every failure, never swallow it
        print(f"error: {exc}", file=sys.stderr)
        return 3

    if args.list or not args.extract:
        major, manifest_size, sig_size = read_header(src)
        print(f"payload version {major}, manifest {manifest_size:,} bytes, signature {sig_size:,} bytes, "
              f"block size {man.block_size}, minor version {man.minor_version}")
        print(f"partition data starts at offset {data_start:,} (zip base {src.base:,})")
        print(f"{len(man.partitions)} partitions")
        total = 0
        for part in man.partitions:
            amount = sum(op.data_length for op in part.operations)
            total += amount
            kinds: dict = {}
            for op in part.operations:
                kinds[op.name] = kinds.get(op.name, 0) + 1
            print(f"  {part.name:<20} size={part.size if part.size is not None else '?':>14} "
                  f"ops={len(part.operations):>5} data={amount:>14,} "
                  f"hash={part.hash.hex()[:16] if part.hash else '-':<16} "
                  + ",".join(f"{k}:{v}" for k, v in sorted(kinds.items())))
        print(f"total operation data {total:,} bytes")
        return 0

    part = next((p for p in man.partitions if p.name == args.extract), None)
    if part is None:
        print(f"error: {args.extract} is not in the payload. Partitions: "
              + ", ".join(p.name for p in man.partitions), file=sys.stderr)
        return 3
    out = args.out or f"{part.name}.img"
    print(f"extracting {part.name}: {len(part.operations)} operations, "
          f"{sum(op.data_length for op in part.operations):,} bytes of data")
    try:
        s = extract_partition(src, man, part, data_start, out)
    except PayloadError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3
    print(f"wrote {out}: {s['size']:,} bytes, operations {s['ops']}")
    print(f"  sha256   {s['sha256']}")
    print(f"  manifest {s['expected']}  -> {'MATCH' if s['verified'] else 'MISMATCH'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
