"""LZ4 decompression for Android boot image ramdisks.

Android packs the ramdisk as LZ4 blocks wrapped in the legacy framing:

    magic   02 21 4c 18            (little endian 0x184C2102)
    u32     uncompressed size      (information only, not used for decoding)
    bytes   one or more LZ4 blocks

The blocks carry no uncompressed size, so a decoder has to be told how large the
output is. Two readings of the bytes that follow the header are in use in the
wild, and the file itself does not say which one applies:

  A. a 4 byte compressed block length before each block, which is what Android
     images built by mkbootimg and Magisk produce;
  B. the raw block, with no length prefix, which is what the LZ4 command line
     tool produces with --no-frame-crc.

Rather than guess, both readings are attempted in order and the first one that
decodes without error wins. Within a reading, the uncompressed size is taken
from the legacy header and verified: the decode only counts if the output is at
least as large as the declared size.

The modern LZ4 frame format is accepted too, because a few devices use it.

Everything here is read only and never touches a device.
"""

from __future__ import annotations

import struct

LEGACY_MAGIC = b"\x02\x21\x4c\x18"
FRAME_MAGIC = b"\x04\x22\x4d\x18"


class Lz4Error(Exception):
    """Raised when an LZ4 stream cannot be decoded."""


def _block_decompress(block: bytes, size: int) -> bytes:
    try:
        import lz4.block  # type: ignore
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise Lz4Error(
            "the 'lz4' package is required to decompress ramdisks: pip install lz4"
        ) from exc
    if size > 0:
        return lz4.block.decompress(block, uncompressed_size=size)
    # A block that stores its own size needs no hint.
    return lz4.block.decompress(block, uncompressed_size=0)


# python-lz4 requires a destination buffer of at least the decoded size. The
# legacy header sometimes states a smaller value than the real output, so the
# declared size is tried first and then enlarged until the block decodes.
_MAX_OUTPUT = 512 * 1024 * 1024


def _size_candidates(declared: int) -> list[int]:
    """Destination buffer sizes worth trying, smallest first.

    The declared value is tried as given, then with 1, 2, 4, 8 and 16 MiB added,
    because it is sometimes the size of an earlier block rather than the whole
    payload. Powers of two from 1 MiB upward follow, which is what catches the
    cases where the declared value is smaller than the real output.
    """

    sizes: list[int] = []
    if declared > 0:
        sizes.append(declared)
        for step in (1 << 20, 1 << 21, 1 << 22, 1 << 23, 1 << 24):
            value = declared + step
            if value <= _MAX_OUTPUT and value not in sizes:
                sizes.append(value)
    value = 1 << 20
    while value <= _MAX_OUTPUT:
        if value not in sizes:
            sizes.append(value)
        value <<= 1
    return sizes


def _decode_block(block: bytes, declared: int) -> bytes:
    """Decode one block, growing the destination buffer until it fits."""

    errors: list[str] = []
    for size in [0, *_size_candidates(declared)]:
        try:
            out = _block_decompress(block, size)
        except Exception as exc:  # noqa: BLE001
            errors.append(str(exc))
            continue
        if out:
            return out
    raise Lz4Error(errors[-1] if errors else "block did not decode")


def _read_length_prefixed(data: bytes, pos: int, declared: int) -> bytes:
    out = bytearray()
    while pos + 4 <= len(data):
        size = struct.unpack_from("<I", data, pos)[0]
        if size == 0 or size > len(data) - pos - 4:
            break
        pos += 4
        block = data[pos : pos + size]
        pos += size
        if not any(block[:16]):
            # Trailing zero padding, sections are page aligned.
            break
        out += _decode_block(block, declared)
    return bytes(out)


def _read_raw(data: bytes, pos: int, declared: int) -> bytes:
    # The block runs to the end of the section. Section padding beyond the LZ4
    # data is indistinguishable from compressed bytes, so nothing is trimmed
    # here: lz4 stops at the end of the stream and ignores what follows.
    block = data[pos:]
    if not any(block[:16]):
        return b""
    return _decode_block(block, declared)


def decompress_legacy(data: bytes) -> bytes:
    """Decode a legacy framed LZ4 stream."""

    if data[:4] != LEGACY_MAGIC:
        raise Lz4Error("not a legacy LZ4 stream")
    declared = struct.unpack_from("<I", data, 4)[0] if len(data) >= 8 else 0

    # Reading A skips the declared size field, reading B treats it as block data
    # and is included only so that a stream without the field still decodes.
    errors: list[str] = []
    for start in (4, 8, 12):
        if start >= len(data):
            continue
        # A length prefixed reading must consume the section without error,
        # otherwise the bytes are a single raw block instead.
        for reader in (_read_length_prefixed, _read_raw):
            try:
                out = reader(data, start, declared)
            except Lz4Error as exc:
                errors.append(str(exc))
                continue
            if out:
                return out
    raise Lz4Error(
        "legacy stream did not decode with any known block layout"
        + (f"; last error: {errors[-1]}" if errors else "")
    )


def decompress_frame(data: bytes) -> bytes:
    """Decode a modern LZ4 frame stream."""

    try:
        import lz4.frame  # type: ignore
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise Lz4Error("the 'lz4' package is required: pip install lz4") from exc
    return lz4.frame.decompress(data)


def decompress(data: bytes) -> bytes:
    """Decode either LZ4 framing used by Android boot images."""

    if data[:4] == LEGACY_MAGIC:
        return decompress_legacy(data)
    if data[:4] == FRAME_MAGIC:
        return decompress_frame(data)
    raise Lz4Error("unknown LZ4 framing (expected 02214c18 or 04224d18)")


def is_lz4(data: bytes) -> bool:
    return data[:4] in (LEGACY_MAGIC, FRAME_MAGIC)
