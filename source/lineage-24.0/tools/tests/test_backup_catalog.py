import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backup_catalog import verify


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.row={'file':'recovery_b_fresh.img','partition':'recovery_b','bytes':4,'sha256':hashlib.sha256(b'good').hexdigest(),'provenance':'historical-capture-unverified','observed_utc':'2026-10-24T00:00:00Z'}
        (self.root/self.row['file']).write_bytes(b'good')
        self.catalog={'schema':1,'purpose':'capture-integrity-inventory','captures':[self.row]}

    def test_dated_capture_maps_to_real_partition(self):
        r=verify(self.catalog,self.root,['recovery_b']);self.assertTrue(r['integrity_pass'])
        self.assertEqual(r['captures'][0]['provenance'],'historical-capture-unverified')

    def test_same_size_corruption(self):
        (self.root/self.row['file']).write_bytes(b'evil')
        self.assertEqual(verify(self.catalog,self.root)['captures'][0]['state'],'hash-mismatch')

    def test_truncation(self):
        (self.root/self.row['file']).write_bytes(b'bad')
        self.assertFalse(verify(self.catalog,self.root)['integrity_pass'])

    def test_missing(self):
        (self.root/self.row['file']).unlink()
        self.assertFalse(verify(self.catalog,self.root)['integrity_pass'])

    def test_missing_required_partition(self):
        self.assertEqual(verify(self.catalog,self.root,['boot_b'])['missing_required_captures'],['boot_b'])

    def test_interrupted_capture_is_not_promoted(self):
        self.catalog['complete']=False
        report=verify(self.catalog,self.root,['recovery_b'])
        self.assertFalse(report['integrity_pass'])
        self.assertEqual(report['captures'][0]['state'],'match')
        self.catalog['complete']=True
        self.assertTrue(verify(self.catalog,self.root,['recovery_b'])['integrity_pass'])

    def test_complete_flag_does_not_replace_planned_coverage(self):
        self.catalog['complete']=True
        self.catalog['plan']=[{'partition':'recovery_b','bytes':4}, {'partition':'boot_b','bytes':4}]
        report=verify(self.catalog,self.root)
        self.assertFalse(report['integrity_pass'])
        self.assertEqual(report['missing_required_captures'],['boot_b'])

    def test_duplicate_partition_is_not_duplicate_coverage(self):
        second=dict(self.row,file='recovery_b.img');(self.root/second['file']).write_bytes(b'good')
        self.catalog['captures'].append(second)
        r=verify(self.catalog,self.root);self.assertEqual(r['capture_count'],2);self.assertEqual(r['distinct_partitions'],1)

    def test_empty_or_duplicate_manifest_rejected(self):
        self.catalog['captures'].append(dict(self.row))
        with self.assertRaises(ValueError):verify(self.catalog,self.root)
        self.catalog['captures']=[]
        with self.assertRaises(ValueError):verify(self.catalog,self.root)

    def test_path_escape_rejected(self):
        self.row['file']='../outside.img'
        with self.assertRaises(ValueError):verify(self.catalog,self.root)
