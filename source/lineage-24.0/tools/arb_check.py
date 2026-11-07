"""Extract the Qualcomm anti-rollback index from an xbl_config image.

This is a Python implementation of the algorithm used by
OTA-Pulse's XblConfigParser.kt, which is itself a port of
koaaN/arbextract.c. This inherited parser reports an image metadata field;
it does not determine whether this phone will accept a firmware downgrade.

The image is ELF64. The anti-rollback data lives in a Qualcomm "HASH segment",
which appears as the last non-empty PT_NULL program header. Inside that segment:

  1. scan the first 0x1000 bytes for a Hash Table Segment Header, stepping four
     bytes at a time, and accept the first candidate that passes sanity checks
  2. the header is: uint32 version, common_size, qti_size, oem_size,
     hash_table_size, then a 16 byte reserved area, so 36 bytes in total
  3. OEM Metadata begins at header + 36 + common_size + qti_size
  4. it reads uint32 major, uint32 minor, uint32 anti_rollback

This reads image metadata, not the handset's fuse or rollback state. A value of
zero does not establish that a downgrade is safe or would be accepted.

Read only. It parses a file.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

ELF_MAGIC = b"\x7fELF"
ELF_HEADER_SIZE = 64
PH_SIZE = 56
HEADER_SCAN_LIMIT = 0x1000
HEADER_SIZE = 36


class XblConfigError(Exception):
    """Raised when the image cannot be parsed."""


@dataclass
class ArbResult:
    arb: int
    major: int
    minor: int
    header_offset: int
    segment_offset: int
    segment_size: int

    def as_dict(self) -> dict:
        return {
            "anti_rollback_index": self.arb,
            "oem_metadata_major": self.major,
            "oem_metadata_minor": self.minor,
            "hash_segment_offset": self.segment_offset,
            "hash_segment_size": self.segment_size,
            "hash_header_offset": self.header_offset,
            "downgrade_verdict": "undetermined: image metadata does not establish device rollback state or firmware compatibility",
        }


def _u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def find_hash_segment(data: bytes) -> tuple[int, int, int]:
    """Return (phoff, segment_offset, segment_size) for the HASH segment."""

    if len(data) < ELF_HEADER_SIZE:
        raise XblConfigError(f"file is only {len(data)} bytes, too small for an ELF header")
    if data[:4] != ELF_MAGIC:
        raise XblConfigError(f"not an ELF file, first four bytes are {data[:4]!r}")
    if data[4] != 2:
        raise XblConfigError(f"not ELF64, e_ident[EI_CLASS] is {data[4]}")
    if data[5] != 1:
        raise XblConfigError(f"not little endian, e_ident[EI_DATA] is {data[5]}")

    pf_off = struct.unpack_from("<Q", data, 0x20)[0]
    ph_ent_size = struct.unpack_from("<H", data, 0x36)[0]
    ph_num = struct.unpack_from("<H", data, 0x38)[0]
    if ph_ent_size < PH_SIZE:
        raise XblConfigError(f"program header entry size {ph_ent_size} is too small")
    if ph_num == 0:
        raise XblConfigError("no program headers")

    for index in range(ph_num - 1, -1, -1):
        pos = pf_off + index * ph_ent_size
        if pos + PH_SIZE > len(data):
            continue
        p_type = _u32(data, pos)
        p_offset = struct.unpack_from("<Q", data, pos + 8)[0]
        p_filesz = struct.unpack_from("<Q", data, pos + 32)[0]
        if p_type == 0 and p_filesz > 0:
            return pf_off, p_offset, p_filesz
    raise XblConfigError("no non-empty PT_NULL program header, so there is no HASH segment")


def find_hash_header(data: bytes, seg_off: int, seg_size: int) -> tuple[int, int, int]:
    """Return (header_offset_within_segment, common_size, qti_size)."""

    limit = min(HEADER_SCAN_LIMIT, seg_size)
    candidate_rejections = 0
    off = 0
    while off + HEADER_SIZE <= limit:
        version = _u32(data, seg_off + off)
        common = _u32(data, seg_off + off + 4)
        qti = _u32(data, seg_off + off + 8)
        oem = _u32(data, seg_off + off + 12)
        hash_table = _u32(data, seg_off + off + 16)
        if (
            1 <= version <= 10
            and common <= 0x1000
            and oem <= 0x4000
            and hash_table <= 0x4000
            and off + HEADER_SIZE + common + qti + oem <= seg_size
        ):
            return off, common, qti
        candidate_rejections += 1
        off += 4
    raise XblConfigError(
        f"no Hash Table Segment Header found in the first {limit} bytes of the segment "
        f"({candidate_rejections} positions rejected)"
    )


def parse(path: str) -> ArbResult:
    """Read an xbl_config image and return its anti-rollback data."""

    with open(path, "rb") as fh:
        data = fh.read()
    _, seg_off, seg_size = find_hash_segment(data)
    header_off, common, qti = find_hash_header(data, seg_off, seg_size)
    oem_off = seg_off + header_off + HEADER_SIZE + common + qti
    if oem_off + 12 > len(data):
        raise XblConfigError(f"OEM metadata at {oem_off} runs past the end of the file")
    major = _u32(data, oem_off)
    minor = _u32(data, oem_off + 4)
    arb = _u32(data, oem_off + 8)
    return ArbResult(
        arb=arb,
        major=major,
        minor=minor,
        header_offset=header_off,
        segment_offset=seg_off,
        segment_size=seg_size,
    )


def main(argv: list[str] | None = None) -> int:
    import argparse
    import json
    import os
    import sys

    parser = argparse.ArgumentParser(
        description="Read the Qualcomm anti-rollback index from an xbl_config image. Read only."
    )
    parser.add_argument("images", nargs="+", help="xbl_config images to inspect")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    status = 0
    results = {}
    for path in args.images:
        try:
            result = parse(path)
        except (XblConfigError, OSError) as exc:
            results[path] = {"error": str(exc)}
            status = 1
            continue
        results[path] = result.as_dict()
        if not args.json:
            print(os.path.basename(path))
            print(f"  hash segment      offset {result.segment_offset:,}, {result.segment_size:,} bytes")
            print(f"  hash header       at +{result.header_offset} within the segment")
            print(f"  oem metadata      major {result.major}, minor {result.minor}")
            print(f"  ANTI-ROLLBACK     {result.arb}")
            print(f"  verdict           {result.as_dict()['downgrade_verdict']}")
            print()

    if args.json:
        print(json.dumps(results, indent=2))
    return status


if __name__ == "__main__":
    raise SystemExit(main())
