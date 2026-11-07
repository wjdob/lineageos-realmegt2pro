"""Stock filename case must survive staging on a case-insensitive host."""
from pathlib import Path
import hashlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'build'))
import prepare_vendor_24 as extraction


class SourceCaseTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.directory = self.root / 'odm/lib/rfsa/adsp'
        self.directory.mkdir(parents=True)
        self.lower = 'odm/lib/rfsa/adsp/libarcsoft_portraitsn_hvx_skel.so'
        self.upper = 'odm/lib/rfsa/adsp/libarcsoft_portraitSN_hvx_skel.so'
        (self.root / self.lower).write_bytes(b'lowercase provider')

    def test_case_alias_is_refused_even_when_host_lookup_would_find_it(self):
        with self.assertRaisesRegex(ValueError, 'exact-case'):
            extraction.exact_source_name(self.root, self.upper)

    def test_exact_spelling_and_content_are_accepted(self):
        data = (self.root / self.lower).read_bytes()
        rows = [{'source': self.lower, 'bytes': len(data),
                 'sha256': hashlib.sha256(data).hexdigest()}]
        self.assertEqual(extraction.vendor_inputs(self.root, {'files': rows}), rows)

    def test_case_preserved_wrong_bytes_are_refused(self):
        rows = [{'source': self.lower, 'bytes': len(b'lowercase provider'), 'sha256': '0' * 64}]
        with self.assertRaisesRegex(ValueError, 'differs from reviewed'):
            extraction.vendor_inputs(self.root, {'files': rows})

    def test_escaped_or_ambiguous_name_is_refused(self):
        for name in ('../outside', '/absolute', 'odm//file', 'odm/./file', 'C:file'):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'unsafe'):
                extraction.exact_source_name(self.root, name)

    def test_directory_component_case_is_checked(self):
        with self.assertRaisesRegex(ValueError, 'exact-case'):
            extraction.exact_source_name(self.root, self.lower.replace('adsp/', 'ADSP/'))


if __name__ == '__main__':
    unittest.main()
