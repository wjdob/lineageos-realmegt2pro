"""Private vendor corruption and unexpected preimages must stop before replacement."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'build'))
import vendor_input_24 as vendor


def digest(data):
    return hashlib.sha256(data).hexdigest()


class VendorTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.store = self.root / 'store'
        self.provider = self.store / 'inputs/provider'
        self.provider.mkdir(parents=True)
        self.repo = self.root / 'repo'
        (self.repo / 'configs').mkdir(parents=True)
        (self.repo / 'tools/build').mkdir(parents=True)
        self.source = self.repo / 'configs/lineage-24.0-vendor-inputs.json'
        self.source.write_text('{}')
        (self.repo / 'tools/build/prepare_vendor_24.py').write_bytes(b'generator')
        (self.repo / 'tools/build/recipe-24.0.json').write_text('{"files":[]}')
        self.tree = self.root / 'tree'
        self.target = self.tree / 'vendor/realme/ferrari'
        self.target.mkdir(parents=True)
        self.rows = []
        for name in ('Android.bp', 'ferrari-vendor.mk'):
            (self.provider / name).write_bytes(b'new')
            (self.target / name).write_bytes(b'base')
            self.rows.append(dict(path=name, bytes=3, sha256=digest(b'new'), base_sha256=digest(b'base')))
        receipt = dict(source_contract_sha256=vendor.sha(self.source), implementation_sha256=digest(b'generator'),
                       files=[{k: r[k] for k in ('path','bytes','sha256')} for r in self.rows])
        (self.provider / 'receipt.json').write_text(json.dumps(receipt))
        self.contract = self.repo / 'configs/lineage-24.0-vendor-output.json'
        self.contract.write_text(json.dumps(dict(schema=1,provider='inputs/provider',files=self.rows,
            source_contract_sha256=vendor.sha(self.source),receipt_sha256=vendor.sha(self.provider/'receipt.json'))))
        self.enterContext(patch.object(vendor,'REPO',self.repo))
        self.enterContext(patch.object(vendor,'CONTRACT',self.contract))
        self.enterContext(patch.object(vendor,'BUILD_TREE',self.tree))
        self.enterContext(patch.object(vendor,'verify_store'))
        self.enterContext(patch.object(vendor,'isolated'))

    def test_valid_materialization_and_idempotent_recheck(self):
        result = vendor.materialize(self.tree,self.store)
        self.assertEqual(len(result['written']),2)
        self.assertEqual(vendor.materialize(self.tree,self.store)['written'],[])

    def test_one_corrupt_provider_stops_all_destination_writes(self):
        (self.provider/'ferrari-vendor.mk').write_bytes(b'bad')
        with self.assertRaisesRegex(ValueError,'provider changed'):
            vendor.materialize(self.tree,self.store)
        self.assertEqual((self.target/'Android.bp').read_bytes(),b'base')

    def test_unknown_later_preimage_leaves_earlier_destination_intact(self):
        (self.target/'ferrari-vendor.mk').write_bytes(b'unknown')
        with self.assertRaisesRegex(ValueError,'unexpected vendor preimage'):
            vendor.materialize(self.tree,self.store)
        self.assertEqual((self.target/'Android.bp').read_bytes(),b'base')

    def test_changed_source_contract_refused(self):
        self.source.write_text('{"changed":true}')
        with self.assertRaisesRegex(ValueError,'source contract changed'):
            vendor.verify_provider(self.store)


if __name__ == '__main__':
    unittest.main()
