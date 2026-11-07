"""Create or stage private Android development signing identities.

Private files stay outside the repository and are never included in run snapshots.
This does not rekey prebuilt APEX payloads or establish production AVB security.
"""
import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

KEY_NAMES = ('releasekey', 'platform', 'shared', 'media', 'networkstack', 'sdk_sandbox', 'bluetooth', 'nfc')
REPO = Path(__file__).resolve().parents[2]
LEGACY_KEYS_MK = b'PRODUCT_DEFAULT_DEV_CERTIFICATE := vendor/lineage-priv/keys/releasekey\n'


def staging_files(directory):
    directory = Path(directory)
    files = {name+ext: (directory/(name+ext)).read_bytes()
             for name in KEY_NAMES for ext in ('.pk8', '.x509.pem')}
    # SELinux's @RELEASE entry uses this basename even for a private release identity.
    for ext in ('.pk8', '.x509.pem'):
        files['testkey'+ext] = files['releasekey'+ext]
    files['keys.mk'] = (LEGACY_KEYS_MK +
        b'PRODUCT_MAINLINE_BLUETOOTH_SEPOLICY_DEV_CERTIFICATES := vendor/lineage-priv/keys\n')
    return files


def create_identity(directory, names=KEY_NAMES, bits=4096):
    directory = Path(directory).absolute()
    if directory.resolve().is_relative_to(REPO) or directory.exists():
        raise ValueError('use a new private directory outside the repository')
    directory.mkdir(parents=True, mode=0o700)
    now = datetime.now(timezone.utc)
    for name in names:
        key = rsa.generate_private_key(public_exponent=65537, key_size=bits)
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'RMX3301 development '+name)])
        cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
                .public_key(key.public_key()).serial_number(x509.random_serial_number())
                .not_valid_before(now-timedelta(minutes=5)).not_valid_after(now+timedelta(days=7300))
                .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
                .sign(key, hashes.SHA256()))
        private = directory/(name+'.pk8')
        with private.open('xb') as stream:
            os.chmod(private, 0o600)
            stream.write(key.private_bytes(serialization.Encoding.DER,
                serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        (directory/(name+'.x509.pem')).write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return inspect_identity(directory, names)


def inspect_identity(directory, names=KEY_NAMES):
    directory = Path(directory)
    report = {}
    for name in names:
        key = serialization.load_der_private_key((directory/(name+'.pk8')).read_bytes(), password=None)
        cert = x509.load_pem_x509_certificate((directory/(name+'.x509.pem')).read_bytes())
        if key.public_key().public_numbers() != cert.public_key().public_numbers():
            raise ValueError('private key/certificate mismatch: '+name)
        report[name] = cert.fingerprint(hashes.SHA256()).hex()
    return report


def stage_identity(tree, directory, expected_cert):
    from apply_recipe import isolated, safe_file
    isolated(tree)
    directory = Path(directory).resolve()
    if directory.is_relative_to(REPO) or directory.is_relative_to(tree):
        raise ValueError('signing keys must be outside repository and checkout')
    identities = inspect_identity(directory)
    expected = x509.load_pem_x509_certificate(Path(expected_cert).read_bytes()).fingerprint(hashes.SHA256()).hex()
    if identities['releasekey'] != expected:
        raise ValueError('private signing identity differs from pinned public certificate')
    relative = 'vendor/lineage-priv/keys/'
    # Accept only the same identity when reusing a signed overlay cache.
    files = staging_files(directory)
    destination = safe_file(tree, relative+'keys.mk').parent
    if destination.exists() and {p.name for p in destination.iterdir()} - set(files):
        raise ValueError('unexpected files in cached signing directory')
    for name, data in files.items():
        target = safe_file(tree, relative+name)
        if target.exists() and target.read_bytes() != data and not (
                name == 'keys.mk' and target.read_bytes() == LEGACY_KEYS_MK):
            raise ValueError('unexpected cached signing file: '+name)
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    for name, data in files.items():
        target = destination/name
        if target.exists() and target.read_bytes() == data:
            continue
        with target.open('wb') as stream:
            os.chmod(target, 0o600 if name.endswith('.pk8') else 0o644)
            stream.write(data)
    return {'certificate_sha256': identities, 'key_directory': str(directory),
            'public_certificate': str(expected_cert),
            'limits': 'Private default APK/OTA identity; prebuilt APEX payload keys and AVB policy remain separately assessed.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--create', type=Path, required=True)
    parser.add_argument('--public-report', type=Path, required=True)
    args = parser.parse_args()
    result = create_identity(args.create)
    args.public_report.parent.mkdir(parents=True, exist_ok=True)
    args.public_report.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result, indent=2))
