from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vendor_xml_abi import bind_loading_context


class LoadingContextTests(unittest.TestCase):
    def setUp(self):
        self.project = dict(path='display', revision='reviewed', source_sha256={'loader.cpp': 'reviewed-bytes'})
        self.contract = dict(loading_context=dict(projects=[self.project]))
        self.inputs = dict(target='otapackage', manifest_sha256='manifest',
                           recipe_snapshot=dict(manifest_sha256='manifest', files=[]),
                           projects=[dict(path='display', revision='reviewed', modified=[])])

    def test_loader_revision_and_recipe_are_bound(self):
        self.assertEqual(bind_loading_context(self.inputs, self.contract), self.contract['loading_context'])
        changed = deepcopy(self.inputs)
        changed['projects'][0]['revision'] = 'new-loader'
        with self.assertRaisesRegex(ValueError, 'revision requires renewed review'):
            bind_loading_context(changed, self.contract)

    def test_local_or_overlay_loader_change_requires_review(self):
        changed = deepcopy(self.inputs)
        changed['projects'][0]['modified'] = ['loader.cpp']
        with self.assertRaisesRegex(ValueError, 'unbound XML loader'):
            bind_loading_context(changed, self.contract)
        changed['recipe_snapshot']['files'] = [dict(path='display/loader.cpp', canonical_sha256='changed')]
        with self.assertRaisesRegex(ValueError, 'recipe modification'):
            bind_loading_context(changed, self.contract)
        changed['recipe_snapshot']['files'][0]['canonical_sha256'] = 'reviewed-bytes'
        self.assertEqual(bind_loading_context(changed, self.contract), self.contract['loading_context'])

    def test_different_manifest_snapshot_is_rejected(self):
        self.inputs['recipe_snapshot']['manifest_sha256'] = 'different'
        with self.assertRaisesRegex(ValueError, 'recipe/input identity'):
            bind_loading_context(self.inputs, self.contract)


if __name__ == '__main__':
    unittest.main()
