import hashlib
import io
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from stream_capture import copy_chunks, matching_hashes


class StreamCaptureTests(unittest.TestCase):
    def test_exact_binary_capture(self):
        data = bytes(range(256))
        target = io.BytesIO()
        result = copy_chunks([data[:19], data[19:]], target, len(data), 20, lambda: 1000)
        self.assertEqual(target.getvalue(), data)
        self.assertEqual(result, hashlib.sha256(data).hexdigest())

    def test_truncated_and_oversized_streams_fail(self):
        for chunks in ([b'ab'], [b'abcd']):
            with self.assertRaises(ValueError):
                copy_chunks(chunks, io.BytesIO(), 3, 0, lambda: 1000)

    def test_reserve_stops_before_write(self):
        target = io.BytesIO()
        with self.assertRaisesRegex(ValueError, 'reserve'):
            copy_chunks([b'abc'], target, 3, 20, lambda: 22)
        self.assertEqual(target.getvalue(), b'')

    def test_changed_source_cannot_be_promoted(self):
        matching_hashes('a'*64, 'a'*64, 'a'*64)
        with self.assertRaisesRegex(ValueError, 'source changed'):
            matching_hashes('a'*64, 'a'*64, 'b'*64)
        with self.assertRaisesRegex(ValueError, 'invalid'):
            matching_hashes('invalid', 'a'*64, 'a'*64)
