"""Exercise cache identity, serialization and refusal without an Android build."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'build'))
import output_cache_24 as cache


class OutputCacheTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base=Path(temporary.name)
        self.tree=self.base/'tree';self.tree.mkdir()
        self.store=self.base/'store';self.store.mkdir()
        self.enterContext(patch.object(cache,'STORE',self.store))
        self.enterContext(patch.object(cache,'BUILD_TREE',self.tree))
        self.enterContext(patch.object(cache,'verify_store'))
        self.enterContext(patch.object(cache,'isolated'))
        self.mount=self.enterContext(patch.object(cache.subprocess,'run'))
        self.enterContext(patch.object(cache,'mounted',return_value={'fstype':'ext4','options':'rw'}))
        # Only mount operations are simulated here. The separate private-namespace
        # fixture exercises actual bind aliasing and unmount on the SSD store.
        self.enterContext(patch.object(Path,'samefile',return_value=True))

    def lease(self):
        return cache.output_cache(self.tree,self.store,'a'*64,'b'*64)

    def test_output_survives_release_and_identity_is_reused(self):
        with self.lease() as first:
            self.assertFalse(first['previously_identified'])
            output=Path(first['path']);(output/'object').write_bytes(b'compiled')
        with self.lease() as second:
            self.assertTrue(second['previously_identified'])
            self.assertEqual(second['path'],first['path'])
            self.assertEqual((output/'object').read_bytes(),b'compiled')
        self.assertEqual([call.args[0][0] for call in self.mount.call_args_list],['mount','umount','mount','umount'])

    def test_concurrent_owner_refused_and_lock_released(self):
        with self.lease():
            with self.assertRaisesRegex(ValueError,'another run'):
                with self.lease():self.fail('Concurrent lease accepted')
        with self.lease():pass

    def test_changed_identity_retained_and_refused(self):
        with self.lease() as first:tag=Path(first['path']).parent/'identity.json'
        tag.write_text('changed')
        with self.assertRaisesRegex(ValueError,'identity changed'):
            with self.lease():pass
        self.assertEqual(tag.read_text(),'changed')

    def test_unidentified_cache_is_not_adopted(self):
        with self.lease() as first:output=Path(first['path'])
        (output/'original').write_text('keep')
        (output.parent/'identity.json').unlink()
        with self.assertRaisesRegex(ValueError,'unidentified'):
            with self.lease():pass
        self.assertEqual((output/'original').read_text(),'keep')

    def test_existing_source_output_is_preserved_and_refused(self):
        point=self.tree/'out';point.mkdir();(point/'original').write_text('keep')
        with self.assertRaisesRegex(ValueError,'bind point must be empty'):
            with self.lease():pass
        self.assertEqual((point/'original').read_text(),'keep')
        self.mount.assert_not_called()

    def test_redirected_output_cache_is_preserved_and_refused(self):
        with self.lease() as first:output=Path(first['path'])
        output.rmdir();output.symlink_to(self.tree,target_is_directory=True)
        with self.assertRaisesRegex(ValueError,'redirected'):
            with self.lease():pass
        self.assertTrue(output.is_symlink())

    def test_wrong_tree_refused_before_store_or_mount(self):
        with self.assertRaisesRegex(ValueError,'dedicated'):
            with cache.output_cache(self.base,self.store,'a'*64,'b'*64):pass
        self.mount.assert_not_called()

    def test_manifest_and_signer_define_distinct_caches(self):
        with self.lease() as original:pass
        with cache.output_cache(self.tree,self.store,'c'*64,'b'*64) as changed:pass
        self.assertNotEqual(original['path'],changed['path'])
        with cache.output_cache(self.tree,self.store,'a'*64,'d'*64) as signer:pass
        self.assertNotEqual(original['path'],signer['path'])

    def test_invalid_hash_refused(self):
        for value in ('a'*63,'A'*64,'g'*64):
            with self.subTest(value=value),self.assertRaisesRegex(ValueError,'SHA-256'):
                cache.cache_identity(value,'b'*64)


if __name__=='__main__':unittest.main()
