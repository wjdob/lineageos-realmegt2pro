from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'build'))
from firmware_policy import require_signer
from signing_keys import KEY_NAMES, create_identity, inspect_identity, staging_files


class SigningIdentityTests(unittest.TestCase):
    def test_release_alias_and_bluetooth_policy_use_private_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in KEY_NAMES:
                for ext in ('.pk8', '.x509.pem'):
                    (root/(name+ext)).write_bytes((name+ext).encode())
            files = staging_files(root)
            self.assertEqual(files['testkey.x509.pem'], files['releasekey.x509.pem'])
            self.assertEqual(files['testkey.pk8'], files['releasekey.pk8'])
            self.assertIn(b'PRODUCT_MAINLINE_BLUETOOTH_SEPOLICY_DEV_CERTIFICATES := vendor/lineage-priv/keys\n',files['keys.mk'])

    def test_identity_key_pair_and_ota_signer_binding(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = create_identity(root/'first', ('releasekey',), 2048)
            second = create_identity(root/'second', ('releasekey',), 2048)
            result = {'signer_matches_otacert': True, 'cms_signer_sha256': first['releasekey']}
            require_signer(result, root/'first/releasekey.x509.pem')
            with self.assertRaisesRegex(ValueError, 'pinned project'):
                require_signer(result, root/'second/releasekey.x509.pem')
            (root/'first/releasekey.pk8').write_bytes((root/'second/releasekey.pk8').read_bytes())
            with self.assertRaisesRegex(ValueError, 'key/certificate mismatch'):
                inspect_identity(root/'first', ('releasekey',))


if __name__ == '__main__':
    unittest.main()
