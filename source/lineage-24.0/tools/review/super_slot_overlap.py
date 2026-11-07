"""Does slot A of a virtual A/B super image still hold its own data? Read only.

Parses the liblp metadata of a raw super image (all metadata slots), then checks
whether the extents of slot 0 (_a) are reused by slot 1 (_b), and reads the
filesystem superblock found at each _a partition's first block.

Usage:
    python -I tools/review/super_slot_overlap.py <super.img>

Written for the 2026-10-17 claims review (docs/CLAIMS_REVIEW_2026-10-17.md).
Controls: internal overlap of slot 0 and of slot 1 must each be zero.
"""
import datetime
import hashlib
import struct
import sys

LP_GEOMETRY_MAGIC = 0x616C4467   # "gDla"
LP_HEADER_MAGIC = 0x414C5030     # "0PLA"


def main(path):
    f = open(path, 'rb')

    def rd(off, n):
        f.seek(off)
        return f.read(n)

    geo = rd(4096, 4096)
    assert struct.unpack_from('<I', geo, 0)[0] == LP_GEOMETRY_MAGIC, 'not an LP super image'
    md_max, slot_count, lbs = struct.unpack_from('<III', geo, 40)
    print(f'geometry: metadata_max_size={md_max} slot_count={slot_count} logical_block_size={lbs}')

    def load(slot):
        base = 4096 + 8192 + slot * md_max
        h = rd(base, 256)
        assert struct.unpack_from('<I', h, 0)[0] == LP_HEADER_MAGIC
        hsize = struct.unpack_from('<I', h, 8)[0]
        tables = rd(base + hsize, struct.unpack_from('<I', h, 44)[0])
        hb = bytearray(rd(base, hsize)); stored = bytes(hb[12:44]); hb[12:44] = b'\0' * 32
        ok = hashlib.sha256(hb).digest() == stored and hashlib.sha256(tables).digest() == bytes(h[48:80])
        flags = struct.unpack_from('<I', h, 128)[0] if hsize >= 132 else 0
        pd = struct.unpack_from('<III', h, 80)
        ed = struct.unpack_from('<III', h, 92)
        ext = [struct.unpack_from('<QIQI', tables, ed[0] + i * ed[2]) for i in range(ed[1])]
        parts = {}
        for i in range(pd[1]):
            e = tables[pd[0] + i * pd[2]: pd[0] + (i + 1) * pd[2]]
            name = e[:36].rstrip(b'\0').decode()
            _, first, num, _ = struct.unpack_from('<IIII', e, 36)
            parts[name] = [(ext[first + k][2], ext[first + k][0]) for k in range(num) if ext[first + k][1] == 0]
        return parts, ok, flags

    def overlap(r1, r2):
        s = 0
        for a, an in r1:
            for b, bn in r2:
                lo, hi = max(a, b), min(a + an, b + bn)
                if hi > lo:
                    s += hi - lo
        return s

    slots = [load(s) for s in range(slot_count)]
    for s, (parts, ok, flags) in enumerate(slots):
        print(f'metadata slot {s}: {len(parts)} partitions, checksums_ok={ok}, virtual_ab_flag={bool(flags & 1)}')

    a, b = slots[0][0], slots[1][0]
    allb = [r for rs in b.values() for r in rs]
    print('controls: slot0 internal overlap =', sum(overlap(a[x], a[y]) for x in a for y in a if x < y),
          ' slot1 internal overlap =', sum(overlap(b[x], b[y]) for x in b for y in b if x < y))
    print(f"{'partition':20s} {'MiB':>9s} {'overlapped by _b':>17s}  fs at _a start")
    for name, rs in a.items():
        size = sum(n for _, n in rs)
        o = overlap(rs, allb)
        blk = rd(rs[0][0] * 512, 4096) if rs else b''
        fs = '-'
        if len(blk) == 4096 and struct.unpack_from('<I', blk, 1024)[0] == 0xE0F5E1E2:
            when = datetime.datetime.fromtimestamp(struct.unpack_from('<Q', blk, 1024 + 24)[0], datetime.timezone.utc)
            fs_mib = struct.unpack_from('<I', blk, 1024 + 36)[0] * (1 << blk[1024 + 12]) / 1048576
            fs = f'erofs built {when:%Y-%m-%d} declares {fs_mib:.1f} MiB'
        elif len(blk) == 4096 and struct.unpack_from('<H', blk, 1080)[0] == 0xEF53:
            fs = 'ext4'
        pct = 100 * o / size if size else 0
        print(f'{name:20s} {size * 512 / 1048576:9.1f} {pct:16.1f}%  {fs}')


if __name__ == '__main__':
    main(sys.argv[1])
