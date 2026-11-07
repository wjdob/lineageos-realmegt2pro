"""Regression checks for pin verifiers that previously ignored invalid entries."""
import contextlib
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'build'))
from manifest import read_pins
import assert_lock
import assert_local_pins


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.file = Path(self.tmp.name) / 'manifest.xml'

    def write(self, body):
        self.file.write_text('<manifest>' + body + '</manifest>')
        return self.file

    def project(self, path='a', rev='a' * 40):
        return f'<project name="repo" path="{path}" revision="{rev}"/>'

    def test_valid_repeated_name_with_distinct_paths(self):
        self.assertEqual(len(read_pins(self.write(self.project() + self.project('b')))), 2)

    def test_unpinned_extra_is_not_silently_ignored(self):
        with self.assertRaises(ValueError):
            read_pins(self.write(self.project() + self.project('b', 'main')))

    def test_empty_is_not_success(self):
        with contextlib.redirect_stdout(io.StringIO()), patch.object(assert_local_pins.subprocess, 'run') as run:
            self.assertEqual(assert_local_pins.main(['check', str(self.write(''))]), 2)
            run.assert_not_called()

    def test_duplicate_path_rejected(self):
        with self.assertRaises(ValueError):
            read_pins(self.write(self.project() * 2))

    def test_missing_path_defaults_to_name(self):
        self.assertIn(('repo', 'repo'), read_pins(self.write('<project name="repo" revision="' + 'a'*40 + '"/>')))

    def test_external_or_parent_paths_rejected(self):
        for location in ('../outside', '/absolute', 'C:/outside', 'a/../../b'):
            with self.subTest(path=location), self.assertRaises(ValueError):
                read_pins(self.write(self.project(location)))

    def test_includes_rejected(self):
        with self.assertRaises(ValueError):
            read_pins(self.write(self.project() + '<include name="extra.xml"/>'))

    def test_revision_difference_fails(self):
        baseline = Path(self.tmp.name) / 'baseline.xml'
        baseline.write_text('<manifest>' + self.project() + '</manifest>')
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(assert_lock.main(['check', str(baseline), str(self.write(self.project(rev='b'*40)))]), 1)

    def test_single_quote_xml_supported(self):
        self.file.write_text("<manifest><project name='repo' revision='" + 'a'*40 + "'/></manifest>")
        self.assertEqual(len(read_pins(self.file)), 1)

    def test_malformed_xml_fails_cleanly(self):
        self.file.write_text('<manifest>')
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(assert_lock.main(['check', str(self.file), str(self.file)]), 2)
