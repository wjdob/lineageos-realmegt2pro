"""Hash raw bytes represented by one Android sparse image without expanding to disk.

Format: AOSP system/core/libsparse/sparse_format.h. DONT_CARE contributes zero
bytes, matching expansion into a new file, not a write over an existing partition.
This checks representation/integrity only; it never applies an OTA or contacts a device.
"""
import hashlib
import struct
import zlib

MAGIC = 0xED26FF3A
BUFFER = 1024 * 1024


def exact(stream, size):
    result = bytearray()
    while len(result) < size:
        data = stream.read(size - len(result))
        if not data:
            raise ValueError('truncated image')
        result.extend(data)
    return bytes(result)


def image_hash(stream, expected_size):
    """Return size/SHA-256 for a raw or sparse stream; require exact output size."""
    if expected_size < 0:
        raise ValueError('negative expected size')
    first = b''
    while len(first) < 4:
        part = stream.read(4 - len(first))
        if not part:
            break
        first += part
    digest, count, crc = hashlib.sha256(), 0, 0

    def consume(data):
        nonlocal count, crc
        count += len(data)
        if count > expected_size:
            raise ValueError('image exceeds expected size')
        digest.update(data)
        crc = zlib.crc32(data, crc)

    sparse = first == struct.pack('<I', MAGIC)
    if not sparse:
        consume(first)
        for data in iter(lambda: stream.read(BUFFER), b''):
            consume(data)
    else:
        major, minor, header_size, chunk_header_size, block_size, blocks, chunks, checksum = struct.unpack('<4H4I', exact(stream, 24))
        if major != 1 or header_size < 28 or chunk_header_size < 12:
            raise ValueError('unsupported sparse header')
        if not block_size or block_size % 4 or blocks * block_size != expected_size:
            raise ValueError('invalid sparse output size/block size')
        exact(stream, header_size - 28)
        for _ in range(chunks):
            kind, reserved, chunk_blocks, total_size = struct.unpack('<2H2I', exact(stream, 12))
            exact(stream, chunk_header_size - 12)
            output_size = chunk_blocks * block_size
            payload_size = total_size - chunk_header_size
            if payload_size < 0 or count + output_size > expected_size:
                raise ValueError('invalid chunk size')
            if kind == 0xCAC1:
                if payload_size != output_size:
                    raise ValueError('invalid RAW size')
                remaining = output_size
                while remaining:
                    data = exact(stream, min(BUFFER, remaining))
                    consume(data)
                    remaining -= len(data)
            elif kind in (0xCAC2, 0xCAC3):
                if payload_size != (4 if kind == 0xCAC2 else 0):
                    raise ValueError('invalid FILL/DONT_CARE size')
                pattern = exact(stream, 4) if kind == 0xCAC2 else b'\0' * 4
                buffer = pattern * (BUFFER // 4)
                remaining = output_size
                while remaining:
                    size = min(BUFFER, remaining)
                    consume(buffer[:size])
                    remaining -= size
            elif kind == 0xCAC4:
                if chunk_blocks or payload_size != 4:
                    raise ValueError('invalid CRC32 chunk')
                if struct.unpack('<I', exact(stream, 4))[0] != crc:
                    raise ValueError('CRC32 chunk mismatch')
            else:
                raise ValueError('unknown sparse chunk')
        if checksum and checksum != crc:
            raise ValueError('sparse header checksum mismatch')
        if stream.read(1):
            raise ValueError('trailing sparse data')
    if count != expected_size:
        raise ValueError('image size differs from expected size')
    return {'bytes': count, 'sha256': digest.hexdigest(), 'sparse': sparse}
