from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from arb_check import ArbResult


class ArbAdvisoryTests(unittest.TestCase):
    def test_neither_zero_nor_nonzero_index_certifies_downgrade_safety(self):
        for index in (0, 1, 255):
            with self.subTest(index=index):
                result = ArbResult(index, 1, 0, 0, 0, 64)
                self.assertEqual(result.as_dict()['anti_rollback_index'], index)
                self.assertTrue(result.as_dict()['downgrade_verdict'].startswith('undetermined:'))
                self.assertFalse(hasattr(result, 'safe_to_downgrade'))


if __name__ == '__main__':
    unittest.main()
