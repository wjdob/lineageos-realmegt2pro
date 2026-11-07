import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'build'))
from check_candidate import check_project
import reconstruct_candidate
from run_build import execute


class CandidateCheckoutTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.project = self.root / 'project'
        self.project.mkdir()
        self.git('init', '-q')
        self.git('config', 'user.name', 'Fixture')
        self.git('config', 'user.email', 'fixture@localhost')
        (self.project / 'source').write_text('original\n')
        self.git('add', 'source')
        self.git('commit', '-qm', 'fixture')
        self.head = self.git('rev-parse', 'HEAD').decode().strip()

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.project), *args], stderr=subprocess.STDOUT)

    def test_head_and_local_changes_are_independent_checks(self):
        check_project(self.root, 'project', self.head, {})
        with self.assertRaisesRegex(ValueError, 'HEAD mismatch'):
            check_project(self.root, 'project', '0' * 40, {})
        (self.project / 'source').write_text('changed\n')
        with self.assertRaisesRegex(ValueError, 'unexpected local change'):
            check_project(self.root, 'project', self.head, {})
        allowed = {'project/source': hashlib.sha256(b'changed\n').hexdigest()}
        check_project(self.root, 'project', self.head, allowed)
        (self.project / 'extra').write_text('untracked')
        with self.assertRaisesRegex(ValueError, 'untracked files'):
            check_project(self.root, 'project', self.head, allowed)

    def test_lfs_pointer_is_not_a_materialized_payload(self):
        self.git('lfs', 'install', '--local')
        (self.project / '.gitattributes').write_text('payload filter=lfs diff=lfs merge=lfs -text\n')
        (self.project / 'payload').write_bytes(b'fixture payload\n')
        self.git('add', '.gitattributes', 'payload')
        self.git('commit', '-qm', 'LFS fixture')
        head = self.git('rev-parse', 'HEAD').decode().strip()
        report = check_project(self.root, 'project', head, {})
        self.assertEqual(len(report['lfs']), 1)
        (self.project / 'payload').write_bytes(self.git('show', 'HEAD:payload'))
        with self.assertRaisesRegex(ValueError, 'LFS payload'):
            check_project(self.root, 'project', head, {})

    def test_lfs_rule_without_matching_files_is_empty_not_corrupt(self):
        (self.project / '.gitattributes').write_text('*.apk filter=lfs diff=lfs merge=lfs -text\n')
        self.git('add', '.gitattributes')
        self.git('commit', '-qm', 'empty LFS rule')
        head = self.git('rev-parse', 'HEAD').decode().strip()
        self.assertEqual(check_project(self.root, 'project', head, {})['lfs'], [])

    def test_declared_addition_requires_absent_pin_and_exact_content(self):
        row = dict(project='project', relative='res/new.xml', path='project/res/new.xml',
                   canonical_sha256=hashlib.sha256(b'resource').hexdigest())
        check_project(self.root, 'project', self.head, {}, [row])
        target = self.project / row['relative']
        target.parent.mkdir()
        target.write_bytes(b'resource')
        check_project(self.root, 'project', self.head, {}, [row])
        target.write_bytes(b'other')
        with self.assertRaisesRegex(ValueError, 'unexpected added-file content'):
            check_project(self.root, 'project', self.head, {}, [row])
        tracked = dict(row, relative='source', path='project/source')
        with self.assertRaisesRegex(ValueError, 'already tracked'):
            check_project(self.root, 'project', self.head, {}, [tracked])

    def test_added_template_rejects_escape_revision_and_hash_mismatch(self):
        template = self.root / 'template.xml'
        template.write_bytes(b'resource')
        row = dict(project='project', relative='res/new.xml', path='project/res/new.xml',
                   source='template.xml', revision=self.head,
                   canonical_sha256=hashlib.sha256(b'resource').hexdigest())
        with patch.object(reconstruct_candidate, 'REPO', self.root):
            recipe = {'files': [], 'new_files': [row]}
            reconstruct_candidate.new_file_rows(recipe, {'project': self.head})
            for changes, message in [({'source': '../template.xml'}, 'invalid added-file'),
                                     ({'relative': '../escape'}, 'invalid added-file'),
                                     ({'revision': '0' * 40}, 'revision differs'),
                                     ({'canonical_sha256': '0' * 64}, 'template hash'),
                                     ({'path': 'other/path'}, 'inconsistent')]:
                with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, message):
                    reconstruct_candidate.new_file_rows(
                        {'files': [], 'new_files': [dict(row, **changes)]}, {'project': self.head})

    def test_storage_budget_prevents_command_start(self):
        marker = self.root / 'started'
        result = execute([sys.executable, '-c', 'from pathlib import Path;Path("started").touch()'],
                         self.root, [], self.root / 'records', min_free=0, space_path=self.root,
                         max_used=1, allocation_path=self.root)
        self.assertEqual(result['state'], 'failed')
        self.assertEqual(result['error'], 'allocation budget reached')
        self.assertFalse(marker.exists())

    def test_storage_budget_stops_running_command(self):
        allocation = self.root / 'allocation'
        samples = iter([0, 2])

        def usage(path):
            return SimpleNamespace(free=100, used=next(samples) if path == allocation else 0)

        with patch('run_build.shutil.disk_usage', side_effect=usage):
            result = execute([sys.executable, '-c', 'import time;time.sleep(30)'],
                             self.root, [], self.root / 'records', min_free=0, space_path=self.root,
                             max_used=1, allocation_path=allocation, poll=.01)
        self.assertEqual(result['state'], 'failed')
        self.assertEqual(result['error'], 'allocation budget reached')
        self.assertNotEqual(result['exit_code'], 0)


if __name__ == '__main__':
    unittest.main()
