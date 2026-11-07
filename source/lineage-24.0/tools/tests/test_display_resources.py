from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from display_resources import check_dump


class DisplayResourceTests(unittest.TestCase):
    def test_old_native_only_table_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'port-2412x1080'):
            check_dump('OPlusFrameworksResTarget',
                       'resource 0x7f030008 dimen/status_bar_height_portrait\n  () 152.000000px\n')

    def test_correct_number_with_wrong_units_is_rejected(self):
        dump = ('resource 0x7f030008 dimen/status_bar_height_portrait\n'
                '  (port-2412x1080) 114.000000dp\n'
                '  (port-3216x1440) 152.000000px\n')
        with self.assertRaisesRegex(ValueError, '114px'):
            check_dump('OPlusFrameworksResTarget', dump)

    def test_missing_native_override_cannot_reuse_fhd(self):
        dump = ('resource 0x7f030008 dimen/status_bar_height_portrait\n'
                '  () 152.000000px\n  (port-2412x1080) 114.000000px\n')
        with self.assertRaisesRegex(ValueError, 'port-3216x1440'):
            check_dump('OPlusFrameworksResTarget', dump)
