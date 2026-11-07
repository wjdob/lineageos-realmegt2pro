#!/usr/bin/env python3
"""Compare logical-partition extent ADDRESSES between slot sets in a liblp super image.

Revised 2026-10-18 for backlog item D01. The previous version read only `num_sectors`
(offset 0) and `target_data` (offset 12). It ignored `target_type` (offset 8) and
`target_source` (offset 20), so it could not tell a LINEAR extent from a ZERO extent,
and a ZERO extent's `target_data` of 0 was scored as a real address at block 0.

LpMetadataExtent is packed:

    uint64 num_sectors     offset 0
    uint32 target_type     offset 8    (LINEAR = 0, ZERO = 1)
    uint64 target_data     offset 12
    uint32 target_source   offset 20

Only LINEAR extents occupy blocks. ZERO extents are holes and must contribute nothing.
"""

import argparse
import struct
import sys

RESERVED, GEOM, GEOM_OFF = 4096, 4096, 4096
LP_GEOM_MAGIC = 0x616C4467
LP_META_MAGIC = 0x414C5030
LP_TARGET_TYPE_LINEAR = 0
LP_TARGET_TYPE_ZERO = 1


def parse_extent(tables, offset):
    """Unpack one LpMetadataExtent. Offsets are the packed struct offsets."""
    num_sectors, = struct.unpack_from('<Q', tables, offset)
    target_type, = struct.unpack_from('<I', tables, offset + 8)
    target_data, = struct.unpack_from('<Q', tables, offset + 12)
    target_source, = struct.unpack_from('<I', tables, offset + 20)
    return (num_sectors, target_type, target_data, target_source)


def read_meta(f, metadata_max_size, slot):
    off = RESERVED + GEOM * 2 + metadata_max_size * slot
    f.seek(off)
    head = f.read(16)
    if len(head) < 16:
        return None
    magic, _maj, _mnr, hsize = struct.unpack_from('<IHHI', head, 0)
    if magic != LP_META_MAGIC:
        return None
    f.seek(off)
    hdr = f.read(hsize)
    tables_size, = struct.unpack_from('<I', hdr, 44)
    parts = struct.unpack_from('<III', hdr, 80)
    exts = struct.unpack_from('<III', hdr, 92)
    tables = f.read(tables_size)
    return parts, exts, tables


def collect(f, metadata_max_size, slot):
    """Return {partition name: [extent tuples]} for one metadata slot."""
    r = read_meta(f, metadata_max_size, slot)
    if r is None:
        return None
    (poff, pnum, psz), (eoff, _enum, esz), tables = r
    out = {}
    for i in range(pnum):
        b = poff + i * psz
        name = tables[b:b + 36].split(b'\x00')[0].decode('ascii', 'replace')
        first, = struct.unpack_from('<I', tables, b + 40)
        num, = struct.unpack_from('<I', tables, b + 44)
        out[name] = [parse_extent(tables, eoff + (first + e) * esz) for e in range(num)]
    return out


def linear(extents):
    """Only LINEAR extents occupy blocks. ZERO extents are holes."""
    return [e for e in extents if e[1] == LP_TARGET_TYPE_LINEAR]


def expand(extents):
    """Sector set claimed by LINEAR extents only. ZERO extents contribute nothing."""
    s = set()
    for num_sectors, target_type, target_data, _src in extents:
        if target_type != LP_TARGET_TYPE_LINEAR:
            continue
        s.update(range(target_data, target_data + num_sectors))
    return s


def type_counts(parts):
    c = {}
    for extents in parts.values():
        for _n, t, _d, _s in extents:
            c[t] = c.get(t, 0) + 1
    return c


def sources(parts):
    s = set()
    for extents in parts.values():
        for _n, t, _d, src in extents:
            if t == LP_TARGET_TYPE_LINEAR:
                s.add(src)
    return s


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('super_image', help='path to a raw super.img containing liblp metadata')
    ap.add_argument('--slot-a', type=int, default=0, help='metadata slot holding the _a set (default 0)')
    ap.add_argument('--slot-b', type=int, default=1, help='metadata slot holding the _b set (default 1)')
    a = ap.parse_args(argv)

    with open(a.super_image, 'rb') as f:
        f.seek(GEOM_OFF)
        geo = f.read(64)
        if len(geo) < 52:
            sys.exit('image too small for a liblp geometry')
        magic, = struct.unpack_from('<I', geo, 0)
        if magic != LP_GEOM_MAGIC:
            sys.exit('not a liblp image (geometry magic 0x%08x)' % magic)
        metadata_max_size, slot_count, _lbs = struct.unpack_from('<III', geo, 40)
        print('  metadata_max_size=%d  metadata_slots=%d' % (metadata_max_size, slot_count))

        A = collect(f, metadata_max_size, a.slot_a)
        B = collect(f, metadata_max_size, a.slot_b)

    if A is None or B is None:
        sys.exit('metadata slot missing')

    # Report what was skipped, so a ZERO extent can never be mistaken for an address.
    ca, cb = type_counts(A), type_counts(B)
    void_a = sum(1 for e in A.values() for x in e if x[1] != LP_TARGET_TYPE_LINEAR)
    void_b = sum(1 for e in B.values() for x in e if x[1] != LP_TARGET_TYPE_LINEAR)
    print('  extent types slot %d: %s' % (a.slot_a, dict(sorted(ca.items()))))
    print('  extent types slot %d: %s' % (a.slot_b, dict(sorted(cb.items()))))
    print('  non-LINEAR extents skipped: slot %d %d, slot %d %d' % (a.slot_a, void_a, a.slot_b, void_b))

    src_a, src_b = sources(A), sources(B)
    if len(src_a) > 1 or len(src_b) > 1:
        sys.exit('metadata spans multiple target_source values (%s / %s) - this tool compares one block device'
                 % (sorted(src_a), sorted(src_b)))
    if src_a and src_b and src_a != src_b:
        sys.exit('the two slots map different target_source values (%s vs %s) - they are not the same device'
                 % (sorted(src_a), sorted(src_b)))
    if src_a or src_b:
        print('  target_source: %s (both slots)' % sorted(src_a | src_b))

    a_all, b_all = set(), set()
    for v in A.values():
        a_all |= expand(v)
    for v in B.values():
        b_all |= expand(v)

    overlap = a_all & b_all
    print('  slot %d partitions: %d' % (a.slot_a, len(A)))
    print('  slot %d partitions: %d' % (a.slot_b, len(B)))
    print('  slot %d sectors claimed: %d' % (a.slot_a, len(a_all)))
    print('  slot %d sectors claimed: %d' % (a.slot_b, len(b_all)))
    print('  overlapping sectors    : %d' % len(overlap))
    if a_all:
        pct = 100.0 * len(overlap) / len(a_all)
        print('  %% of slot %d also in slot %d: %.2f%%' % (a.slot_a, a.slot_b, pct))
        print('  (= %.0f MiB at 512-byte sectors)' % (len(overlap) * 512 / 1024 / 1024))

    print()
    print('  per-partition: does the first LINEAR start block match its twin?')
    same = 0
    total = 0
    for name in sorted(A):
        twin = None
        if name.endswith('_a'):
            twin = name[:-len('_a')] + '_b'
        if twin not in B:
            continue
        la, lb = linear(A[name]), linear(B[twin])
        if not la or not lb:
            continue
        total += 1
        a0, b0 = la[0][2], lb[0][2]
        o = len(expand(A[name]) & expand(B[twin]))
        t = len(expand(A[name]))
        if a0 == b0:
            same += 1
        print('    %-22s a_start=%-10d b_start=%-10d same=%-5s overlap=%d/%d'
              % (name, a0, b0, str(a0 == b0), o, t))

    print()
    if total and same == total:
        print('  RESULT: all %d pairs start at the same block - the two slot sets are the' % total)
        print('  same physical blocks, so slot A holds no independent copy.')
    else:
        print('  RESULT: %d of %d pairs share a start block.' % (same, total))
    return 0


if __name__ == '__main__':
    sys.exit(main())