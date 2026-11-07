import gzip
import hashlib
import importlib.util
import io
from pathlib import Path
import struct
import tempfile
import unittest
import zlib
from types import SimpleNamespace
from unittest.mock import patch

path=Path(__file__).resolve().parents[1]/'device/prepare_upgrade_restore.py'
spec=importlib.util.spec_from_file_location('prepare_upgrade_restore',path)
restore=importlib.util.module_from_spec(spec)
spec.loader.exec_module(restore)


class RestorePreparationTests(unittest.TestCase):
    def fixture(self):
        rows=[dict(partition=name,file=name+'.img.gz',source_bytes=4096,stored_bytes=32,
            source_sha256='a'*64,source_after_sha256='a'*64,stored_sha256='b'*64)
            for name in restore.QUIET_PARTITIONS]
        return dict(complete=True,phase='complete',mode='quiet',serial='owner',
                    expected_incremental='23b',expected_slot='b',boot_id='quiet-boot',captures=rows)

    def convert(self,raw):
        result=io.BytesIO()
        stats=restore.write_sparse(io.BytesIO(gzip.compress(raw)),result,len(raw),hashlib.sha256(raw).hexdigest())
        result.seek(0)
        checked=restore.image_hash(result,len(raw))
        self.assertEqual(checked['sha256'],hashlib.sha256(raw).hexdigest())
        self.assertTrue(checked['sparse'])
        return result.getvalue(),stats

    def test_zero_ranges_are_explicit_fill_not_dont_care(self):
        image,stats=self.convert(bytes(4096))
        self.assertEqual(struct.unpack_from('<H',image,28)[0],0xcac2)
        self.assertEqual(image[40:44],bytes(4))
        self.assertEqual(stats['dont_care_chunks'],0)

    def test_raw_and_fill_chunks_preserve_exact_source(self):
        raw=bytes(restore.CHUNK)+b'a'*restore.CHUNK+bytes(4096)
        image,stats=self.convert(raw)
        self.assertEqual(stats['sparse_chunks'],3)
        self.assertLess(len(image),len(raw))

    def test_incomplete_backup_is_refused(self):
        record=self.fixture();record['complete']=False
        with self.assertRaises(ValueError):restore.selected_capture(record,'userdata','owner','23b')

    def test_probe_cannot_be_used_as_quiet_backup(self):
        record=self.fixture();record['mode']='probe'
        with self.assertRaises(ValueError):restore.selected_capture(record,'userdata','owner','23b')

    def test_missing_metadata_pair_is_refused(self):
        record=self.fixture();record['captures']=[r for r in record['captures'] if r['partition']!='metadata']
        with self.assertRaises(ValueError):restore.selected_capture(record,'userdata','owner','23b')

    def test_other_device_or_build_is_refused(self):
        for serial,build in (('other','23b'),('owner','24')):
            with self.assertRaises(ValueError):restore.selected_capture(self.fixture(),'userdata',serial,build)

    def test_protected_capture_is_refused(self):
        with self.assertRaises(ValueError):restore.selected_capture(self.fixture(),'frp','owner','23b')

    def test_changed_quiet_source_is_refused(self):
        record=self.fixture();record['captures'][0]['source_after_sha256']='c'*64
        with self.assertRaises(ValueError):restore.selected_capture(record,'userdata','owner','23b')

    def test_path_traversal_is_refused(self):
        record=self.fixture();record['captures'][0]['file']='../userdata.img.gz'
        with self.assertRaises(ValueError):restore.selected_capture(record,'userdata','owner','23b')

    def test_bad_expanded_hash_is_refused(self):
        with self.assertRaises(ValueError):
            restore.write_sparse(io.BytesIO(gzip.compress(bytes(4096))),io.BytesIO(),4096,'a'*64)

    def test_extra_expanded_bytes_are_refused(self):
        with self.assertRaises(ValueError):
            restore.write_sparse(io.BytesIO(gzip.compress(bytes(8192))),io.BytesIO(),4096,hashlib.sha256(bytes(4096)).hexdigest())

    def test_corrupt_gzip_is_refused(self):
        data=bytearray(gzip.compress(bytes(4096)));data[-8]^=1
        with self.assertRaises((ValueError,OSError,EOFError,zlib.error)):
            restore.write_sparse(io.BytesIO(data),io.BytesIO(),4096,hashlib.sha256(bytes(4096)).hexdigest())

    def test_truncated_gzip_trailer_is_refused(self):
        data=gzip.compress(bytes(4096))[:-3]
        with self.assertRaises((ValueError,OSError,EOFError,zlib.error)):
            restore.write_sparse(io.BytesIO(data),io.BytesIO(),4096,hashlib.sha256(bytes(4096)).hexdigest())

    def test_short_expanded_source_is_refused(self):
        with self.assertRaisesRegex(ValueError,'truncated'):
            restore.write_sparse(io.BytesIO(gzip.compress(bytes(4096))),io.BytesIO(),8192,hashlib.sha256(bytes(8192)).hexdigest())

    def test_space_refusal_stops_preparation(self):
        def deny(count):raise ValueError('floor')
        with self.assertRaisesRegex(ValueError,'floor'):
            restore.write_sparse(io.BytesIO(gzip.compress(bytes(4096))),io.BytesIO(),4096,hashlib.sha256(bytes(4096)).hexdigest(),check_space=deny)

    def test_complete_file_preparation_binds_pair_and_reads_back(self):
        import json
        base=Path('tmp/test-upgrade-restore');base.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=base) as directory:
            folder=Path(directory).resolve()
            record=self.fixture()
            raw=bytes(restore.CHUNK)+b'personal-data-placeholder'*1024
            raw += bytes((-len(raw)) % restore.BLOCK)
            compressed=gzip.compress(raw)
            row=record['captures'][0]
            row.update(source_bytes=len(raw),stored_bytes=len(compressed),
                source_sha256=hashlib.sha256(raw).hexdigest(),source_after_sha256=hashlib.sha256(raw).hexdigest(),
                stored_sha256=hashlib.sha256(compressed).hexdigest())
            (folder/'userdata.img.gz').write_bytes(compressed)
            capture=folder/'capture.json';capture.write_text(json.dumps(record))
            destination=folder/'prepared/userdata.sparse.img'
            with patch.object(restore.shutil,'disk_usage',return_value=SimpleNamespace(free=80*1024**3)):
                report=restore.prepare(capture,'userdata','owner','23b',destination)
            self.assertTrue(report['complete'])
            self.assertEqual(report['paired_data_hashes']['userdata'],row['source_sha256'])
            self.assertEqual(report['paired_data_hashes']['metadata'],'a'*64)
            self.assertTrue(destination.is_file())
            self.assertFalse(destination.with_suffix('.img.partial').exists())
            self.assertTrue(json.loads(destination.with_suffix('.img.json').read_text())['complete'])
            with destination.open('rb') as stream:
                self.assertEqual(restore.image_hash(stream,len(raw))['sha256'],row['source_sha256'])

    def test_prepare_refuses_low_space_before_creating_output(self):
        import json
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory).resolve();record=self.fixture()
            raw=bytes(4096);compressed=gzip.compress(raw);row=record['captures'][0]
            row.update(source_bytes=len(raw),stored_bytes=len(compressed),
                source_sha256=hashlib.sha256(raw).hexdigest(),source_after_sha256=hashlib.sha256(raw).hexdigest(),
                stored_sha256=hashlib.sha256(compressed).hexdigest())
            (folder/'userdata.img.gz').write_bytes(compressed)
            capture=folder/'capture.json';capture.write_text(json.dumps(record))
            destination=folder/'prepared.img'
            with patch.object(restore.shutil,'disk_usage',return_value=SimpleNamespace(free=0)):
                with self.assertRaisesRegex(ValueError,'free-space floor'):
                    restore.prepare(capture,'userdata','owner','23b',destination)
            self.assertFalse(destination.exists())
            self.assertFalse(destination.with_suffix('.img.partial').exists())

    def test_corrupted_stored_file_cannot_create_prepared_image(self):
        import json
        base=Path('tmp/test-upgrade-restore');base.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=base) as directory:
            folder=Path(directory).resolve()
            record=self.fixture()
            (folder/'userdata.img.gz').write_bytes(bytes(32))
            capture=folder/'capture.json';capture.write_text(json.dumps(record))
            destination=folder/'prepared.img'
            with self.assertRaisesRegex(ValueError,'stored backup size/hash'):
                restore.prepare(capture,'userdata','owner','23b',destination)
            self.assertFalse(destination.exists())


if __name__=='__main__':unittest.main()
