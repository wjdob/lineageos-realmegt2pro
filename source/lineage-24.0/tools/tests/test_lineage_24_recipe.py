"""Offline integrity checks for the pinned LineageOS 24.0 source recipe."""
import hashlib
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'build'))
from manifest import read_pins

REPO = Path(__file__).resolve().parents[2]
RECIPE = REPO / 'tools/build/recipe-24.0.json'
CONFIG = REPO / 'configs/lineage-24.0-candidate.json'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def patch_targets(data):
    for line in data.decode('utf-8').splitlines():
        if line.startswith(('--- ', '+++ ')):
            name = line[4:].split('\t', 1)[0]
            if name.startswith(('a/', 'b/')):
                yield name[2:]


class Lineage24RecipeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.recipe = json.loads(RECIPE.read_text())
        cls.manifest = REPO / cls.recipe['manifest']
        cls.pins = read_pins(cls.manifest)
        cls.by_path = {path: (name, rev) for (name, path), rev in cls.pins.items()}

    def test_manifest_hash_and_project_count(self):
        self.assertEqual(sha(self.manifest), self.recipe['manifest_sha256'])
        self.assertGreaterEqual(len(self.pins), 1200)
        self.assertEqual(len(self.pins),json.loads(CONFIG.read_text())['platform_projects'])
        for path in ('device/realme/ferrari', 'device/oneplus/sm8450-common',
                     'kernel/oneplus/sm8450-devicetrees', 'vendor/realme/ferrari'):
            self.assertIn(path, self.by_path)

    def test_required_cts_deqp_projects_are_in_the_lock(self):
        expected={'external/deqp':'eae519aaa6980b2a34ec07141bb19de3f6ddf69e',
                  'external/deqp-deps/SPIRV-Headers':'d425c460bde47239483e36ccbec5674cf39eb431',
                  'external/deqp-deps/SPIRV-Tools':'4e0aa7940f17b47e67f7be80442d526b4fc54142',
                  'external/deqp-deps/amber':'e2217d1616b410dc65f72d0cdd0b73f0b72a860d',
                  'external/deqp-deps/glslang':'14422bdc57fb93221192a0c542dde144980dfb69'}
        for name,revision in expected.items():self.assertEqual(self.by_path[name][1],revision)

    def test_recipe_files_bind_manifest_revisions(self):
        seen = set()
        for row in self.recipe['files']:
            self.assertRegex(row['path'], r'^[A-Za-z0-9._+@-]+(/[A-Za-z0-9._+@-]+)+$')
            self.assertNotIn(row['path'], seen)
            seen.add(row['path'])
            self.assertEqual(row['path'], row['project'] + '/' + row['relative'])
            self.assertIn(row['project'], self.by_path)
            self.assertEqual(self.by_path[row['project']][1], row['revision'])
            for key in ('base_sha256', 'canonical_sha256'):
                self.assertRegex(row[key], r'^[0-9a-f]{64}$')
            self.assertNotEqual(row['base_sha256'], row['canonical_sha256'])

    def test_patch_actions_are_hash_bound_and_target_recipe_files(self):
        actions = [a for a in self.recipe['actions'] if a['type'] == 'patch']
        self.assertEqual(len(actions), json.loads(CONFIG.read_text())['candidate_recipe']['text_patches'])
        files = {row['path'] for row in self.recipe['files']}
        names = set()
        for action in actions:
            path = REPO / action['file']
            self.assertNotIn(path.name, names)
            names.add(path.name)
            self.assertEqual(sha(path), action['sha256'])
            self.assertIn(action['project'], self.by_path)
            for relative in patch_targets(path.read_bytes()):
                self.assertIn(action['project'] + '/' + relative, files)

    def test_private_vendor_supersedes_public_binary_replacement(self):
        actions = [a for a in self.recipe['actions'] if a['type'] == 'replace_bytes']
        self.assertFalse(any(a['path'].startswith('vendor/realme/ferrari/') for a in actions))
        self.assertFalse(any(row['project'] == 'vendor/realme/ferrari' for row in self.recipe['files']))
        inputs = json.loads((REPO / 'configs/lineage-24.0-vendor-inputs.json').read_text())
        outputs = json.loads((REPO / 'configs/lineage-24.0-vendor-output.json').read_text())
        self.assertEqual(outputs['source_contract_sha256'], sha(REPO / 'configs/lineage-24.0-vendor-inputs.json'))
        destinations = {row['destination'] for row in inputs['files']}
        self.assertEqual({'proprietary/' + p for p in destinations},
            {row['path'] for row in outputs['files'] if row['path'].startswith('proprietary/')})

    def test_camera_compatibility_sources_reach_the_extractor_and_generated_provider(self):
        inputs = json.loads((REPO / 'configs/lineage-24.0-vendor-inputs.json').read_text())
        outputs = json.loads((REPO / 'configs/lineage-24.0-vendor-output.json').read_text())
        source_rows = {r['path']: r['canonical_sha256'] for r in self.recipe['files']}
        for name, digest in inputs['extraction_sources'].items():
            self.assertEqual(source_rows[name], digest,
                             'vendor generation must use the final reconstructed extractor')
        delivered = {r['path']: r['sha256'] for r in outputs['files']}
        self.assertEqual(set(inputs['expected_outputs']), {
            'proprietary/odm/lib64/libAlgoInterface.so',
            'proprietary/odm/lib64/libAlgoProcess.so',
            'proprietary/odm/lib64/libmsnativefilter.so',
            'proprietary/odm/lib/rfsa/adsp/libarcsoft_portraitSN_hvx_skel.so',
            'proprietary/odm/lib/rfsa/adsp/libarcsoft_portraitsn_hvx_skel.so',
            'proprietary/odm/bin/hw/vendor.qti.secure_element@1.2-service',
            'proprietary/odm/etc/init/vendor.qti.secure_element@1.2-service.rc',
            'proprietary/odm/lib64/android.hardware.secure_element@1.0-impl.so'})
        for name, digest in inputs['expected_outputs'].items():
            self.assertEqual(delivered[name], digest,
                             'private materialization must preserve the reviewed camera cohort')

    def test_camera_compatibility_headers_and_callback_are_delivered_without_oem_apps(self):
        additions = {r['path']: r for r in self.recipe['new_files']}
        for name in (
                'hardware/oplus/oplus-fwk/src/com/oplus/app/IOplusProtectConnection.aidl',
                'frameworks/av/services/camera/libcameraservice/device3/OplusCameraClientMetadata.h'):
            self.assertIn(name, additions)
            row = additions[name]
            self.assertEqual(sha(REPO / row['source']), row['canonical_sha256'])
        self.assertFalse(any(r['path'].endswith('.apk') for r in self.recipe['new_files']))
        actions = [r['file'] for r in self.recipe['actions'] if r['type'] == 'patch']
        self.assertEqual(sum(name.endswith('0037-ferrari-recording-profiles.patch')
                             for name in actions), 1)
        self.assertFalse(any(name.endswith('0093-ferrari-recording-profiles.patch')
                             for name in actions))

    def test_candidate_config_agrees_with_recipe_and_manifest(self):
        config = json.loads(CONFIG.read_text())
        self.assertEqual(config['platform_lock_sha256'], sha(self.manifest))
        self.assertEqual(config['candidate_recipe']['sha256'], sha(RECIPE))
        configured = {row['path']: row['revision'] for row in config['projects']}
        for path, revision in configured.items():
            self.assertEqual(self.by_path[path][1], revision)
        self.assertEqual(config['build_plan']['target_release'], 'cp2a')
        self.assertIn('not a build', config['limits'])

    def test_agm_contract_uses_the_selected_hidl_namespace(self):
        contract=json.loads((REPO/'configs/agm-calibration-24.0.json').read_text())
        selected='hardware/qcom-caf/sm8450/audio/agm/service'
        self.assertEqual(contract['module_source'],selected)
        self.assertEqual(contract['graph_source'],selected+'/src/graph.c')
        rows={row['path']:row['canonical_sha256'] for row in self.recipe['files']}
        for name,digest in contract['source_sha256'].items():
            self.assertEqual(rows[name],digest)


if __name__ == '__main__':
    unittest.main()
