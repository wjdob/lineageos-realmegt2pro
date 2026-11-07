from pathlib import Path
import copy
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'build'))
from init_cached_graph_24 import cohort, graph_files, validate_inputs


class InitCachedGraph(unittest.TestCase):
    def inputs(self):
        return {'target': 'init-diagnostic', 'manifest_sha256': 'manifest',
                'recipe_sha256': 'recipe', 'vendor_inputs': {'contract_sha256': 'vendor', 'receipt_sha256': 'receipt'},
                'common_runtime':{'contract_sha256':'common','receipt_sha256':'common-receipt'},
                'output_cache': {'identity': {'product': 'lineage_ferrari'}}, 'release': 'cp2a'}

    def test_release_target_cannot_reuse_probe_graph(self):
        value=self.inputs();previous={'cohort':cohort(value)};value['target']='otapackage'
        with self.assertRaises(ValueError):validate_inputs(value, previous)

    def test_changed_recipe_or_vendor_requires_regeneration(self):
        value=self.inputs();previous={'cohort':cohort(value)}
        for key in ('recipe_sha256', 'manifest_sha256'):
            changed=copy.deepcopy(value);changed[key]='new'
            with self.assertRaises(ValueError):validate_inputs(changed, previous)
        changed=copy.deepcopy(value);changed['vendor_inputs']['contract_sha256']='new'
        with self.assertRaises(ValueError):validate_inputs(changed, previous)
        validate_inputs(value, previous)

    def test_changed_common_runtime_requires_regeneration(self):
        value=self.inputs();previous={'cohort':cohort(value)}
        for key in ('contract_sha256','receipt_sha256'):
            changed=copy.deepcopy(value);changed['common_runtime'][key]='new'
            with self.assertRaises(ValueError):validate_inputs(changed,previous)

    def test_old_inputs_without_common_identity_are_rejected(self):
        value=self.inputs();del value['common_runtime']
        with self.assertRaises(ValueError):cohort(value)

    def test_graph_include_escape_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'combined-lineage_ferrari.ninja').write_text('subninja out/../outside.ninja\n')
            with self.assertRaises(ValueError):graph_files(root)


if __name__=='__main__':unittest.main()
