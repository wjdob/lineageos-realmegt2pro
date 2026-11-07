"""Tests for slot_extent_overlap - backlog item D01.

The defect this guards against: the previous version read only num_sectors (offset 0)
and target_data (offset 12), never target_type (offset 8). A ZERO extent carries
target_data = 0, so it was scored as a real address at block 0 and could inflate
the reported overlap between slot sets.
"""

import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import slot_extent_overlap as seo


def pack_extent(num_sectors, target_type, target_data, target_source):
    """Pack one LpMetadataExtent exactly as liblp lays it out."""
    return struct.pack('<QIQI', num_sectors, target_type, target_data, target_source)


class ParseExtentTests(unittest.TestCase):
    def test_linear_extent_offsets(self):
        # num_sectors 2048, LINEAR, target_data 5000, source 1
        buf = pack_extent(2048, seo.LP_TARGET_TYPE_LINEAR, 5000, 1)
        self.assertEqual(len(buf), 24)
        self.assertEqual(seo.parse_extent(buf, 0), (2048, 0, 5000, 1))

    def test_zero_extent_parsed_with_its_type(self):
        buf = pack_extent(4096, seo.LP_TARGET_TYPE_ZERO, 0, 1)
        num, typ, data, src = seo.parse_extent(buf, 0)
        self.assertEqual(num, 4096)
        self.assertEqual(typ, seo.LP_TARGET_TYPE_ZERO)
        self.assertEqual(data, 0)
        self.assertEqual(src, 1)

    def test_nonzero_offset(self):
        buf = b'\x00' * 8 + pack_extent(16, 0, 99, 2)
        self.assertEqual(seo.parse_extent(buf, 8), (16, 0, 99, 2))


class ExpandTests(unittest.TestCase):
    """Negative control: ZERO extents must contribute no sectors."""

    def test_linear_extent_claims_its_sectors(self):
        ext = [(4, seo.LP_TARGET_TYPE_LINEAR, 10, 0)]
        self.assertEqual(seo.expand(ext), {10, 11, 12, 13})

    def test_zero_extent_contributes_nothing(self):
        # The regression: a ZERO extent of 4096 sectors at target_data 0 must add nothing.
        ext = [(4096, seo.LP_TARGET_TYPE_ZERO, 0, 0)]
        self.assertEqual(seo.expand(ext), set())

    def test_zero_extent_is_not_scored_as_block_zero(self):
        # This is the exact defect D01 describes. Before the fix, block 0 was claimed.
        ext = [(1, seo.LP_TARGET_TYPE_ZERO, 0, 0)]
        claimed = seo.expand(ext)
        self.assertNotIn(0, claimed)
        self.assertEqual(len(claimed), 0)

    def test_mixed_extents_claim_only_linear(self):
        ext = [
            (2, seo.LP_TARGET_TYPE_LINEAR, 100, 0),
            (9999, seo.LP_TARGET_TYPE_ZERO, 0, 0),
        ]
        self.assertEqual(seo.expand(ext), {100, 101})

    def test_zero_extent_cannot_inflate_overlap(self):
        # Two slots, each with a large ZERO extent. Overlap must be empty.
        a = [(5000, seo.LP_TARGET_TYPE_ZERO, 0, 0)]
        b = [(5000, seo.LP_TARGET_TYPE_ZERO, 0, 0)]
        self.assertEqual(seo.expand(a) & seo.expand(b), set())


class LinearFilterTests(unittest.TestCase):
    def test_linear_drops_zero(self):
        ext = [
            (1, seo.LP_TARGET_TYPE_ZERO, 0, 0),
            (2, seo.LP_TARGET_TYPE_LINEAR, 50, 0),
        ]
        self.assertEqual(seo.linear(ext), [(2, 0, 50, 0)])

    def test_linear_on_all_zero_is_empty(self):
        ext = [(8, seo.LP_TARGET_TYPE_ZERO, 0, 0)]
        self.assertEqual(seo.linear(ext), [])


class AggregateTests(unittest.TestCase):
    def test_type_counts(self):
        parts = {
            'a': [(1, 0, 10, 0), (1, 1, 0, 0)],
            'b': [(1, 0, 20, 0)],
        }
        self.assertEqual(seo.type_counts(parts), {0: 2, 1: 1})

    def test_sources_ignore_zero(self):
        parts = {
            'a': [(1, 0, 10, 7), (1, 1, 0, 99)],
        }
        # A ZERO extent's target_source is meaningless and must not widen the set.
        self.assertEqual(seo.sources(parts), {7})


if __name__ == '__main__':
    unittest.main()