"""Keep first-stage diagnostics confined to the explicit isolated build target."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'build'))
from init_boot_trace_24 import PREIMAGES, reconstruct, validate_run
from run_candidate_24 import required_artifacts


class InitTraceScope(unittest.TestCase):
    def test_release_and_other_targets_cannot_apply_diagnostic(self):
        for target in ('otapackage', 'nothing', 'check-elf-files', 'codec2-provider', None):
            with self.subTest(target=target), self.assertRaises(ValueError):
                validate_run({'target': target, 'source_hashes': {'helper': 'known'}}, 'helper', 'known')

    def test_changed_or_missing_frozen_helper_refused(self):
        for hashes in ({}, {'helper': 'old'}):
            with self.subTest(hashes=hashes), self.assertRaises(ValueError):
                validate_run({'target': 'init-diagnostic', 'source_hashes': hashes}, 'helper', 'new')

    def test_explicit_bound_diagnostic_accepted(self):
        validate_run({'target': 'init-diagnostic', 'source_hashes': {'helper': 'known'}}, 'helper', 'known')

    def test_unknown_preimage_refused(self):
        with self.assertRaisesRegex(ValueError, 'preimage mismatch'):
            reconstruct({name: b'changed-source' for name in PREIMAGES})

    def test_missing_source_refused(self):
        with self.assertRaises(ValueError):
            reconstruct({})

    def test_exact_init_pair_collected(self):
        self.assertEqual(required_artifacts('init-diagnostic'), ['out/target/product/ferrari/ramdisk/init', 'out/target/product/ferrari/system/bin/init'])


if __name__ == '__main__':
    unittest.main()
