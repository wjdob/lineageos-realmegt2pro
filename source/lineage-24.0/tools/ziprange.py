#!/usr/bin/env python3
"""Read a ZIP over HTTP with range requests, so only the needed bytes download.

Realme OTA packages are around 8 GB. Downloading one in full to reach a single
member inside it is wasteful, and on this machine it would not have fit. This
module reads the central directory with range requests, then streams out just
the member you ask for.

Read only: it fetches bytes and writes them to a local file. It does not touch
any device.

Usage:

    python tools/ziprange.py --list <url>
    python tools/ziprange.py --extract payload.bin --out C:/Users/wdob/realmeGT2Pro-dev/ota/payload.bin <url>
"""

from __future__ import annotations

import argparse
import os
import struct
import sys
import urllib.request
import zlib

EOCD_SIG = b"PK\x05\x06"
EOCD64_LOCATOR_SIG = b"PK\x06\x07"
EOCD64_SIG = b"PK\x06\x06"
CENTRAL_SIG = b"PK\x01\x02"
LOCAL_SIG = b"PK\x03\x04"

CHUNK = 1 << 20


class ZipRangeError(Exception):
    """Raised when the remote file is not a usable ZIP."""


def _request(url: str, start: int, end: int, timeout: int = 120):
    req = urllib.request.Request(url)
    req.add_header("Range", f"bytes={start}-{end}")
    req.add_header("User-Agent", "Mozilla/5.0 (compatible; rmx3301-offline-tooling)")
    return urllib.request.urlopen(req, timeout=timeout)


def fetch_range(url: str, start: int, end: int, timeout: int = 120) -> bytes:
    with _request(url, start, end, timeout) as resp:
        return resp.read()


def content_length(url: str) -> int:
    req = urllib.request.Request(url, method="HEAD")
    req.add_header("User-Agent", "Mozilla/5.0 (compatible; rmx3301-offline-tooling)")
    with urllib.request.urlopen(req, timeout=60) as resp:
        return int(resp.headers["Content-Length"])


class Member:
    def __init__(self, name: str, method: int, compressed: int, uncompressed: int, header_offset: int):
        self.name = name
        self.method = method
        self.compressed = compressed
        self.uncompressed = uncompressed
        self.header_offset = header_offset

    @property
    def stored(self) -> bool:
        return self.method == 0

    def __repr__(self) -> str:
        return f"<Member {self.name} {'stored' if self.stored else 'deflate'} {self.uncompressed}>"


def read_central_directory(url: str, size: int | None = None) -> tuple[list[Member], int]:
    """Return every member and the base offset the ZIP starts at."""

    total = size if size is not None else content_length(url)
    tail_len = min(66560, total)
    tail = fetch_range(url, total - tail_len, total - 1)

    # End of central directory record layout, from byte 0 of the record:
    #   0 signature, 4 disk number, 6 disk with CD, 8 entries this disk,
    #   10 total entries, 12 CD size, 16 CD offset, 20 comment length.
    pos = tail.rfind(EOCD_SIG)
    if pos < 0:
        raise ZipRangeError("end of central directory record not found; not a ZIP?")
    cd_size = struct.unpack_from("<I", tail, pos + 12)[0]
    cd_offset = struct.unpack_from("<I", tail, pos + 16)[0]
    # Kept in the return value for callers that pass it back to
    # local_data_offset. It is always zero, because every offset in a ZIP is an
    # absolute file position.
    base = 0

    # Zip64: those fields saturate at 0xFFFFFFFF and a locator just before the
    # EOCD points at a zip64 end of central directory record with the real
    # 64 bit values, at offsets 40 (size) and 48 (offset).
    # The two fields saturate independently. In this archive the size is a
    # valid 487 bytes while the offset alone is 0xFFFFFFFF, so each has to be
    # tested and replaced on its own.
    loc = tail.rfind(EOCD64_LOCATOR_SIG)
    if loc >= 0 and (cd_size == 0xFFFFFFFF or cd_offset == 0xFFFFFFFF):
        eocd64_offset = struct.unpack_from("<Q", tail, loc + 8)[0]
        eocd64 = fetch_range(url, eocd64_offset, eocd64_offset + 55)
        if eocd64[:4] == EOCD64_SIG:
            real_size = struct.unpack_from("<Q", eocd64, 40)[0]
            real_offset = struct.unpack_from("<Q", eocd64, 48)[0]
            if cd_size == 0xFFFFFFFF:
                cd_size = real_size
            if cd_offset == 0xFFFFFFFF:
                cd_offset = real_offset

    if cd_size == 0 or cd_size > 256 * 1024 * 1024:
        raise ZipRangeError(f"implausible central directory size {cd_size}")
    if cd_offset + cd_size > total:
        raise ZipRangeError(
            f"central directory at {cd_offset} with size {cd_size} runs past the end of {total}"
        )

    # Central directory offsets are absolute byte positions in the file, whether
    # or not the archive carries a self extracting stub.
    cd = fetch_range(url, cd_offset, cd_offset + cd_size - 1)

    members: list[Member] = []
    pos = 0
    while pos + 46 <= len(cd) and cd[pos : pos + 4] == CENTRAL_SIG:
        method = struct.unpack_from("<H", cd, pos + 10)[0]
        compressed = struct.unpack_from("<I", cd, pos + 20)[0]
        uncompressed = struct.unpack_from("<I", cd, pos + 24)[0]
        name_len = struct.unpack_from("<H", cd, pos + 28)[0]
        extra_len = struct.unpack_from("<H", cd, pos + 30)[0]
        comment_len = struct.unpack_from("<H", cd, pos + 32)[0]
        header_offset = struct.unpack_from("<I", cd, pos + 42)[0]
        name = cd[pos + 46 : pos + 46 + name_len].decode("utf-8", "replace")
        # Zip64 extra field, id 0x0001, carries the real sizes and offset.
        extra = cd[pos + 46 + name_len : pos + 46 + name_len + extra_len]
        epos = 0
        while epos + 4 <= len(extra):
            field_id, field_len = struct.unpack_from("<HH", extra, epos)
            if field_id == 0x0001:
                body = extra[epos + 4 : epos + 4 + field_len]
                cursor = 0
                if uncompressed == 0xFFFFFFFF and cursor + 8 <= len(body):
                    uncompressed = struct.unpack_from("<Q", body, cursor)[0]
                    cursor += 8
                if compressed == 0xFFFFFFFF and cursor + 8 <= len(body):
                    compressed = struct.unpack_from("<Q", body, cursor)[0]
                    cursor += 8
                if header_offset == 0xFFFFFFFF and cursor + 8 <= len(body):
                    header_offset = struct.unpack_from("<Q", body, cursor)[0]
                    cursor += 8
            epos += 4 + field_len
        members.append(Member(name, method, compressed, uncompressed, header_offset))
        pos += 46 + name_len + extra_len + comment_len
    return members, base


def local_data_offset(url: str, base: int, member: Member) -> int:
    head = fetch_range(url, base + member.header_offset, base + member.header_offset + 29)
    if head[:4] != LOCAL_SIG:
        raise ZipRangeError(f"{member.name}: local header magic not found")
    name_len = struct.unpack_from("<H", head, 26)[0]
    extra_len = struct.unpack_from("<H", head, 28)[0]
    return base + member.header_offset + 30 + name_len + extra_len


def extract(url: str, member: Member, base: int, out_path: str, progress=None) -> int:
    start = local_data_offset(url, base, member)
    remaining = member.compressed
    decompressor = zlib.decompressobj(-15) if not member.stored else None
    written = 0
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    with open(out_path, "wb") as fh:
        cursor = start
        while remaining > 0:
            end = cursor + min(CHUNK, remaining) - 1
            with _request(url, cursor, end) as resp:
                block = resp.read()
            if not block:
                raise ZipRangeError("server returned no more data")
            cursor += len(block)
            remaining -= len(block)
            if decompressor is not None:
                block = decompressor.decompress(block)
            fh.write(block)
            written += len(block)
            if progress:
                progress(written, member.uncompressed)
    return written


def find(members: list[Member], name: str) -> Member:
    for member in members:
        if member.name == name or member.name.endswith("/" + name):
            return member
    raise ZipRangeError(f"{name} is not in the archive")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("url")
    parser.add_argument("--list", action="store_true", help="list members with sizes")
    parser.add_argument("--extract", metavar="MEMBER", help="member name to write out")
    parser.add_argument("--out", help="output path for --extract")
    args = parser.parse_args(argv)

    try:
        members, base = read_central_directory(args.url)
    except Exception as exc:  # noqa: BLE001
        print(f"error: {exc}", file=sys.stderr)
        return 3

    if args.list or not args.extract:
        print(f"{len(members)} members")
        for member in members:
            kind = "stored " if member.stored else "deflate"
            print(f"  {member.uncompressed:>14,}  {kind}  {member.name}")
        return 0

    try:
        member = find(members, args.extract)
    except ZipRangeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3

    out = args.out or os.path.basename(member.name)
    print(f"extracting {member.name} ({member.uncompressed:,} bytes, {'stored' if member.stored else 'deflate'})")
    print(f"downloading {member.compressed:,} bytes from the remote archive")
    last = [0.0]

    def progress(done: int, total: int) -> None:
        pct = (done / total * 100) if total else 0.0
        if pct - last[0] >= 5 or done >= total:
            last[0] = pct
            print(f"  {pct:5.1f}%  {done:,} bytes", flush=True)

    try:
        written = extract(args.url, member, base, out, progress)
    except Exception as exc:  # noqa: BLE001
        print(f"error during extraction: {exc}", file=sys.stderr)
        return 3
    print(f"wrote {out} ({written:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())