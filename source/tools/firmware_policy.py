"""Check the MVP OTA's write set against the external-firmware contract.

This is a packaging check, not firmware compatibility or device acceptance.
"""
import argparse
import hashlib
import json
from pathlib import Path
import tempfile
import zipfile

from payload_range import PayloadError, Source, load_manifest

OS_PARTITIONS = frozenset(('boot', 'dtbo', 'odm', 'product', 'recovery', 'system',
    'system_ext', 'vbmeta', 'vbmeta_system', 'vbmeta_vendor', 'vendor',
    'vendor_boot', 'vendor_dlkm'))


def exact_partitions(names, label):
    names = list(names)
    if len(names) != len(set(names)):
        raise ValueError(label + ': duplicate partition')
    found = set(names)
    if found != OS_PARTITIONS:
        raise ValueError(f'{label}: unexpected={sorted(found-OS_PARTITIONS)}, '
                         f'missing={sorted(OS_PARTITIONS-found)}')


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def check(ota, target_files, expected_cert=None):
    ota, target_files = Path(ota), Path(target_files)
    for path in (ota, target_files):
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)):
                raise ValueError('duplicate ZIP member: ' + str(path))
            if any(n.startswith('RADIO/') and not n.endswith('/') for n in names):
                raise ValueError('bundled RADIO member: ' + str(path))
            if path == ota and archive.getinfo('payload.bin').compress_type != zipfile.ZIP_STORED:
                raise ValueError('payload.bin must be stored uncompressed for direct parsing')
    with zipfile.ZipFile(target_files) as archive:
        exact_partitions(archive.read('META/ab_partitions.txt').decode().split(), 'target-files')
        for name in OS_PARTITIONS:
            archive.getinfo('IMAGES/' + name + '.img')
    with Source(str(ota)) as source:
        manifest, _ = load_manifest(source)
    exact_partitions((part.name for part in manifest.partitions), 'OTA payload')
    signing = None
    if expected_cert is not None:
        from verify_signapk_ota import signer_cert
        with tempfile.TemporaryDirectory(prefix='ota-policy-') as scratch:
            with zipfile.ZipFile(ota) as archive:
                signing = signer_cert(ota, archive, scratch, 'openssl')
        require_signer(signing, expected_cert)
    return {'state': 'passed', 'firmware_mode': 'external', 'signing': signing,
            'partitions': sorted(OS_PARTITIONS),
            'ota': str(ota), 'ota_sha256': sha(ota),
            'target_files': str(target_files), 'target_files_sha256': sha(target_files),
            'limits': 'Write set and optional pinned CMS signer only; image binding, recovery trust, AVB policy and runtime compatibility are separate.'}


def require_signer(result, expected_cert):
    from cryptography.hazmat.primitives import hashes
    from verify_signapk_ota import load_cert
    expected = load_cert(Path(expected_cert).read_bytes()).fingerprint(hashes.SHA256()).hex()
    if not result.get('signer_matches_otacert') or result.get('cms_signer_sha256') != expected:
        raise ValueError('OTA signer does not match the pinned project certificate')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ota', type=Path, required=True)
    parser.add_argument('--target-files', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--expected-cert', type=Path, required=True)
    args = parser.parse_args()
    try:
        report = check(args.ota, args.target_files, args.expected_cert)
    except (ValueError, OSError, KeyError, zipfile.BadZipFile, PayloadError) as error:
        report = {'state': 'failed', 'error': str(error)}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    return 0 if report['state'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
