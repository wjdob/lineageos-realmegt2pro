"""Stop a changed camera backend before publishing an extracted vendor set."""
from pathlib import Path
import hashlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'build'))
import prepare_vendor_24 as extraction


class CohortTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.name = 'proprietary/odm/lib64/libAlgoInterface.so'
        self.file = self.root / self.name
        self.file.parent.mkdir(parents=True)
        self.file.write_bytes(b'reviewed backend')
        self.contract = {'expected_outputs': {
            self.name: hashlib.sha256(self.file.read_bytes()).hexdigest()}}

    def test_exact_cohort_is_accepted(self):
        extraction.expected_outputs(self.root, self.contract)

    def test_changed_backend_is_rejected(self):
        self.file.write_bytes(b'other Android cohort')
        with self.assertRaisesRegex(ValueError, 'cohort differs'):
            extraction.expected_outputs(self.root, self.contract)

    def test_missing_provider_is_rejected(self):
        self.file.unlink()
        with self.assertRaisesRegex(ValueError, 'missing or escaped'):
            extraction.expected_outputs(self.root, self.contract)

    def test_unsafe_destinations_and_incomplete_hash_are_rejected(self):
        for name, digest in [('../outside.so', 'a' * 64),
                             ('/proprietary/a.so', 'a' * 64),
                             ('proprietary/../outside.so', 'a' * 64),
                             ('proprietary/a.so', 'partial')]:
            with self.subTest(name=name, digest=digest):
                with self.assertRaisesRegex(ValueError, 'invalid expected'):
                    extraction.expected_outputs(self.root, {'expected_outputs': {name: digest}})


if __name__ == '__main__':
    unittest.main()
