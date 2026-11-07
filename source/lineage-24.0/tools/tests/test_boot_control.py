from pathlib import Path
import struct
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from boot_control import decode


class BootControlTests(unittest.TestCase):
    def sample(self,status=0):
        data=bytearray(32768+64)
        command=b'bootonce-bootloader\0'
        data[:len(command)]=command
        struct.pack_into('<BIBB',data,32768,2,0x56740AB0,status,1)
        return data

    def test_offsets_and_command(self):
        r=decode(self.sample());self.assertEqual(r['command'],'bootonce-bootloader');self.assertEqual(r['merge_status'],'NONE')

    def test_pending_merge_is_not_none(self):
        self.assertEqual(decode(self.sample(3))['merge_status'],'MERGING')

    def test_invalid_header_rejected(self):
        with self.assertRaises(ValueError):decode(bytes(32768+64))

    def test_truncated_rejected(self):
        with self.assertRaises(ValueError):decode(self.sample()[:-1])

    def test_unknown_enum_rejected(self):
        with self.assertRaises(ValueError):decode(self.sample(99))
