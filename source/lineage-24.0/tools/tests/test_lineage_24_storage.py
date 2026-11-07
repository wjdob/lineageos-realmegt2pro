"""Reject redirected or non-SSD storage before staging 24.0 inputs."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'build'))
import storage_24
import reconstruct_candidate


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.store = self.base / 'store'
        self.store.mkdir()
        for name in ('tree', 'work', 'records', 'evidence', 'tmp'):
            (self.store / name).mkdir()
        (self.store / 'storage-identity.json').write_text(json.dumps(
            {'schema':1, 'branch':'lineage-24.0', 'host_drive':'C'}))
        self.enterContext(patch.object(storage_24, 'STORE', self.store))
        self.enterContext(patch.object(storage_24, 'BACKING', self.store))
        self.mounts = [dict(source='C:', fstype='9p'),
                       dict(source='/dev/sdd[/build/lineage24-store]', fstype='ext4', options='rw,relatime'),
                       dict(source='/dev/sdd', fstype='ext4', options='rw,relatime')]
        self.enterContext(patch.object(storage_24, 'mounted', side_effect=lambda p: self.mounts[
            0 if p == storage_24.HOST else 2 if p == Path('/') else 1]))
        self.enterContext(patch.object(storage_24, 'root_on_ssd',return_value={'host_drive':'C'}))

    def test_exact_ssd_ext4_directory_accepted(self):
        self.assertTrue(storage_24.verify_store(self.store)['backing_verified'])

    def test_external_loop_image_refused(self):
        self.mounts[1]['source'] = '/dev/loop7'
        with self.assertRaisesRegex(ValueError, 'not backed'):
            storage_24.verify_store(self.store)

    def test_wrong_windows_drive_refused(self):
        self.mounts[0]['source'] = 'E:'
        with self.assertRaisesRegex(ValueError, 'Windows C:'):
            storage_24.verify_store(self.store)

    def test_wrong_backing_directory_refused(self):
        other=self.base/'other';other.mkdir()
        with patch.object(storage_24,'BACKING',other),self.assertRaisesRegex(ValueError,'not backed'):
            storage_24.verify_store(self.store)

    def test_wrong_branch_marker_refused(self):
        (self.store/'storage-identity.json').write_text(json.dumps(
            {'schema':1,'branch':'lineage-23.2','host_drive':'C'}))
        with self.assertRaisesRegex(ValueError,'identity differs'):
            storage_24.verify_store(self.store)

    def test_ssd_registration_accepts_extended_windows_path(self):
        self.assertEqual(storage_24.registration_on_ssd(
            [{'name':'test','path':'\\\\?\\C:\\wsl\\test'}],'test')['host_drive'],'C')

    def test_ssd_registration_rejects_external_distro(self):
        with self.assertRaisesRegex(ValueError,'not registered'):
            storage_24.registration_on_ssd([{'name':'test','path':'E:\\wsl\\test'}],'test')

    def test_ssd_registration_rejects_missing_distro(self):
        with self.assertRaisesRegex(ValueError,'ambiguous'):
            storage_24.registration_on_ssd([{'name':'other','path':'C:\\wsl\\test'}],'test')

    def test_redirected_store_child_refused(self):
        (self.store / 'tmp').rmdir()
        (self.store / 'tmp').symlink_to(self.base, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'redirected'):
            storage_24.verify_store(self.store)

    def test_readonly_store_refused(self):
        self.mounts[1]['options'] = 'ro,relatime'
        with self.assertRaisesRegex(ValueError, 'writable ext4'):
            storage_24.verify_store(self.store)

    def test_external_scratch_default_remains_forbidden(self):
        with self.assertRaisesRegex(ValueError, 'designated scratch'):
            reconstruct_candidate.reconstruct(self.store / 'tree', self.base / 'scratch')

    def test_scratch_root_itself_cannot_be_output(self):
        output = self.base / 'absent'
        with self.assertRaisesRegex(ValueError, 'designated scratch'):
            reconstruct_candidate.reconstruct(self.store / 'tree', output, scratch_root=output)

    def test_overlay_mountpoint_is_created_without_source(self):
        point = self.base / 'build'
        with patch.object(storage_24, 'BUILD_TREE', point):
            storage_24.prepare_mountpoint()
        self.assertTrue(point.is_dir())
        self.assertEqual(list(point.iterdir()), [])

    def test_nonempty_overlay_mountpoint_preserved_and_refused(self):
        point = self.base / 'build'
        point.mkdir()
        (point / 'source').write_text('keep')
        with patch.object(storage_24, 'BUILD_TREE', point), self.assertRaisesRegex(ValueError, 'must be empty'):
            storage_24.prepare_mountpoint()
        self.assertEqual((point / 'source').read_text(), 'keep')

    def fresh_fixture(self):
        tree=self.base/'overlay';tree.mkdir()
        run=self.store/'work/candidate-test'
        upper=run/'upper';upper.mkdir(parents=True)
        (run/'work').mkdir()
        marker={'root':str(tree),'lower':str(self.store/'tree'),'run':str(run),'base_run':None}
        for target in (tree,upper):
            (target/'.realme-next-isolated.json').write_text(json.dumps(marker))
        mount={'fstype':'overlay','options':f'rw,lowerdir={self.store}/tree,upperdir={upper},workdir={run}/work'}
        return tree,upper,mount

    def test_fresh_lower_requires_empty_bound_overlay(self):
        tree,upper,mount=self.fresh_fixture()
        with patch.object(storage_24,'mounted',return_value=mount):
            self.assertEqual(storage_24.fresh_lower(tree,self.store,'candidate-test'),self.store/'tree')

    def test_fresh_lower_rejects_unchecked_upper_file(self):
        tree,upper,mount=self.fresh_fixture()
        (upper/'unchecked').touch()
        with patch.object(storage_24,'mounted',return_value=mount),self.assertRaisesRegex(ValueError,'unchecked changes'):
            storage_24.fresh_lower(tree,self.store,'candidate-test')

    def test_fresh_lower_rejects_other_mount_source(self):
        tree,upper,mount=self.fresh_fixture()
        mount['options']=mount['options'].replace('lowerdir='+str(self.store/'tree'),'lowerdir=/other')
        with patch.object(storage_24,'mounted',return_value=mount),self.assertRaisesRegex(ValueError,'does not bind'):
            storage_24.fresh_lower(tree,self.store,'candidate-test')


class RegistrationQueryTests(unittest.TestCase):
    def test_service_registry_query_uses_absolute_executable(self):
        payload=json.dumps([{'name':'test','path':'C:\\wsl\\test'}])
        with patch.dict(storage_24.os.environ,{'WSL_DISTRO_NAME':'test'}),patch.object(storage_24.subprocess,'check_output',return_value=payload) as query:
            self.assertEqual(storage_24.root_on_ssd()['host_drive'],'C')
        self.assertTrue(Path(query.call_args.args[0][0]).is_absolute())

    def test_missing_distro_environment_uses_absolute_wslpath(self):
        payload=json.dumps([{'name':'test','path':'C:\\wsl\\test'}])
        with patch.dict(storage_24.os.environ,{},clear=True),patch.object(storage_24.subprocess,'check_output',side_effect=[payload,'\\\\wsl.localhost\\test\\\n']) as query:
            self.assertEqual(storage_24.root_on_ssd()['host_drive'],'C')
        self.assertEqual(query.call_args.args[0],['/usr/bin/wslpath','-w','/'])


if __name__ == '__main__':
    unittest.main()
