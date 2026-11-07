"""Tests for the device tool's partition name resolution.

These need no phone. The partition list is a subset of the real by-name listing
from the RMX3301, taken on 2026-10-08.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import rmx3301_device as device  # noqa: E402

RMX3301_BY_NAME = [
    "boot_a", "boot_b", "vendor_boot_a", "vendor_boot_b", "recovery_a", "recovery_b",
    "dtbo_a", "dtbo_b", "vbmeta_a", "vbmeta_b", "vbmeta_system_a", "vbmeta_system_b",
    "vbmeta_vendor_a", "vbmeta_vendor_b", "modem_a", "modem_b", "bluetooth_a",
    "bluetooth_b", "persist", "modemst1", "modemst2", "fsg", "misc", "super", "userdata",
]


class ResolvePartitionsTests(unittest.TestCase):
    def test_defaults_resolve_to_active_slot(self) -> None:
        resolved, missing = device.resolve_partitions(
            device.DEFAULT_PARTITIONS, RMX3301_BY_NAME, "_b"
        )
        self.assertIn("boot_b", resolved)
        self.assertIn("vendor_boot_b", resolved)
        self.assertIn("vbmeta_system_b", resolved)
        self.assertIn("persist", resolved)
        self.assertNotIn("boot_a", resolved)
        self.assertEqual(missing, ["init_boot"])

    def test_every_default_except_init_boot_is_found(self) -> None:
        resolved, _ = device.resolve_partitions(device.DEFAULT_PARTITIONS, RMX3301_BY_NAME, "_b")
        self.assertEqual(len(resolved), len(device.DEFAULT_PARTITIONS) - 1)

    def test_all_slots_returns_both_copies(self) -> None:
        resolved, missing = device.resolve_partitions(["boot", "misc"], RMX3301_BY_NAME, "_b", True)
        self.assertEqual(resolved, ["boot_a", "boot_b", "misc"])
        self.assertEqual(missing, [])

    def test_explicit_suffix_is_used_as_given(self) -> None:
        resolved, missing = device.resolve_partitions(["boot_a"], RMX3301_BY_NAME, "_b")
        self.assertEqual(resolved, ["boot_a"])
        self.assertEqual(missing, [])

    def test_no_slot_suffix_means_exact_names_only(self) -> None:
        resolved, missing = device.resolve_partitions(["boot", "misc"], RMX3301_BY_NAME, "")
        self.assertEqual(resolved, ["misc"])
        self.assertEqual(missing, ["boot"])

    def test_duplicates_are_dropped(self) -> None:
        resolved, _ = device.resolve_partitions(["boot", "boot_b"], RMX3301_BY_NAME, "_b")
        self.assertEqual(resolved, ["boot_b"])


if __name__ == "__main__":
    unittest.main()
