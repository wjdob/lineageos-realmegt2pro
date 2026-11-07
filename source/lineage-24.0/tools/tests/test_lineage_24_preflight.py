"""The 24.0 preflight must gate the SSD store and refuse incomplete trees."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'build'))
import preflight_24

GIB = 1024**3


def disk_usage(host_gib=200, store_gib=200, c_gib=50):
    def usage(path):
        value = host_gib
        if str(path) == str(preflight_24.STORE):
            value = store_gib
        return SimpleNamespace(free=value * GIB)
    return usage


def run(*argv, host_gib=200, store_gib=200, tree=None):
    tree = tree or Path(tempfile.mkdtemp())
    out = io.StringIO()
    with patch.object(sys, 'argv', ['preflight_24.py', *argv]), \
         patch.object(preflight_24, 'TREE', tree), \
         patch.object(preflight_24, 'mountpoint', return_value=True), \
         patch.object(preflight_24, 'verify_store', return_value={'backing_verified': True}), \
         patch.object(preflight_24, 'filesystem', return_value='ext4'), \
         patch.object(preflight_24.shutil, 'disk_usage',
                      side_effect=disk_usage(host_gib=host_gib, store_gib=store_gib)), \
         contextlib.redirect_stdout(out):
        rc = preflight_24.main()
    return rc, json.loads(out.getvalue())


class PreflightTests(unittest.TestCase):
    def test_repeated_build_preflight_uses_new_external_scratch(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            tree = base / 'tree'
            (tree / '.repo').mkdir(parents=True)
            (tree / '.repo/project.list').write_text('right/path\n')
            (base / 'tmp').mkdir()
            release = tree / 'vendor/lineage/vars/aosp_target_release'
            release.parent.mkdir(parents=True)
            release.write_text('# comment\naosp_target_release=cp2a\n')
            with patch.object(preflight_24,'STORE',base), \
                 patch.object(preflight_24,'read_pins',return_value={('project','right/path'):'a'*40}), \
                 patch.object(preflight_24,'apply',return_value={'reconstruction':{'reconstruction':'verified','files':3},'files':1,'new_files':2}) as apply, \
                 patch.object(preflight_24,'check_kernel_layout',return_value={'ok':True}) as layout, \
                 patch.object(preflight_24,'check_checkout',return_value={'projects':[{}],'lfs_content_verified':True}), \
                 patch.object(preflight_24,'verify_provider',return_value=({'files':[{}]},base)), \
                 patch.object(preflight_24,'verify_common',return_value=({'files':[{}],'metadata':[],'interface_sources':[]},base)), \
                 patch.object(preflight_24,'inspect_identity',return_value={'releasekey':{}}):
                for _ in range(2):
                    rc,report=run('--phase','build',tree=tree)
                    self.assertEqual(rc,0,report)
                    self.assertEqual(report['checks']['recipe']['detail'],'3 files reconstructed')
                paths=[call.args[2] for call in apply.call_args_list]
                self.assertNotEqual(paths[0],paths[1])
                self.assertTrue(all(p.is_relative_to(base/'tmp') for p in paths))
                self.assertEqual([call.args for call in layout.call_args_list],[(tree,p) for p in paths])

    def test_same_count_wrong_project_paths_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            tree = Path(directory)
            (tree / '.repo').mkdir()
            (tree / '.repo/project.list').write_text('wrong/path\n')
            release = tree / 'vendor/lineage/vars/aosp_target_release'
            release.parent.mkdir(parents=True)
            release.write_text('aosp_target_release=cp2a\n')
            with patch.object(preflight_24, 'read_pins', return_value={('project', 'right/path'): 'a' * 40}):
                rc, report = run('--phase', 'sync', tree=tree)
            self.assertEqual(rc, 1)
            self.assertFalse(report['checks']['project_list']['ok'])

    def test_sync_refuses_low_host_and_store_space(self):
        rc, report = run('--phase', 'sync', host_gib=10, store_gib=10)
        self.assertEqual(rc, 1)
        self.assertFalse(report['checks']['host_free']['ok'])
        self.assertFalse(report['checks']['store_free']['ok'])

    def test_sync_accepts_space_with_incomplete_tree(self):
        rc, report = run('--phase', 'sync')
        self.assertEqual(rc, 0)
        self.assertTrue(report['checks']['host_free']['ok'])
        self.assertTrue(report['checks']['store_filesystem']['ok'])

    def test_build_refuses_incomplete_tree(self):
        rc, report = run('--phase', 'build')
        self.assertEqual(rc, 1)
        self.assertTrue(report['checks']['tree']['ok'])
        self.assertFalse(report['checks']['project_list']['ok'])

    def test_build_refuses_low_store_space(self):
        rc, report = run('--phase', 'build', host_gib=100, store_gib=10)
        self.assertEqual(rc, 1)
        self.assertFalse(report['checks']['store_free']['ok'])


if __name__ == '__main__':
    unittest.main()
