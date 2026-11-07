from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'build'))
from workspace_revision_24 import revision,windows_gitdir


class WorkspaceTests(unittest.TestCase):
    def test_windows_drive_gitdir_translation(self):
        self.assertEqual(windows_gitdir('C:/Users/owner/repo/.git/worktrees/develop'),
                         Path('/mnt/c/Users/owner/repo/.git/worktrees/develop'))

    def test_unc_gitdir_refused(self):
        with self.assertRaises(ValueError):windows_gitdir('\\\\server\\share\\repo')

    def test_linked_worktree_revision_without_gitfile_edits(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);main=base/'main';main.mkdir()
            def git(*args):
                return subprocess.check_output(['git','-C',str(main),*args],stderr=subprocess.STDOUT)
            git('init','-q');git('config','user.name','Fixture');git('config','user.email','fixture@localhost')
            (main/'source').write_text('source');git('add','source');git('commit','-qm','fixture')
            work=base/'work';git('worktree','add','-qb','development',str(work))
            expected=git('rev-parse','HEAD').decode().strip()
            actual_metadata=Path((work/'.git').read_text().strip()[8:])
            (work/'.git').write_text('gitdir: C:/fixture/.git/worktrees/work\n')
            before=(work/'.git').read_bytes()
            with patch('workspace_revision_24.windows_gitdir',return_value=actual_metadata):
                self.assertEqual(revision(work),expected)
            self.assertEqual((work/'.git').read_bytes(),before)


if __name__=='__main__':unittest.main()
