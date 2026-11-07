"""Check same-run recovery certificate trust; no device contact or boot claim."""
import argparse
from io import BytesIO
import json
from pathlib import Path
import zipfile

from cryptography.hazmat.primitives import hashes
from bootimg import bootimage
from payload_image_binding import collected, sha
from verify_signapk_ota import load_cert

TRUST_PATH = 'system/etc/security/otacerts.zip'
PUBLIC_DEVELOPMENT_CERT = 'a40da80a59d170caa950cf15c18c454d47a39b26989d8b640ecd745ba71bf5dc'
LINEAGE_CERT = '518325ef7f96c0d1194c2e856b040d636166ffb846717d72fa87f4fae5be7bbb'


def inspect_archive(data, expected_pem, forbidden=frozenset((PUBLIC_DEVELOPMENT_CERT,))):
    expected = load_cert(expected_pem).fingerprint(hashes.SHA256()).hex()
    certificates = {}
    with zipfile.ZipFile(BytesIO(data)) as archive:
        if len(archive.namelist()) != len(set(archive.namelist())):
            raise ValueError('duplicate recovery trust entry')
        for member in archive.infolist():
            if member.is_dir():
                continue
            if member.file_size > 64 * 1024:
                raise ValueError('unexpectedly large certificate entry')
            cert = load_cert(archive.read(member))
            certificates[member.filename] = cert.fingerprint(hashes.SHA256()).hex()
    fingerprints = set(certificates.values())
    unexpected = fingerprints - {expected, LINEAGE_CERT}
    return {'trust_pass': expected in fingerprints and not (fingerprints & set(forbidden)) and not unexpected,
            'expected_certificate_der_sha256': expected, 'certificates': certificates,
            'expected_certificate_present': expected in fingerprints,
            'forbidden_certificates_present': sorted(fingerprints & set(forbidden)),
            'unexpected_certificates_present': sorted(unexpected),
            'allowed_certificate_der_sha256': sorted({expected, LINEAGE_CERT})}


def verify(run_record, expected_cert, image_binding_report=None):
    run_record, expected_cert = Path(run_record), Path(expected_cert)
    record = json.loads(run_record.read_text())
    if record.get('state') != 'success':
        raise ValueError('successful collector record required')
    recovery, entry = collected(record, '/recovery.img')
    binding_sha = None
    if image_binding_report is not None:
        binding_path = Path(image_binding_report)
        binding = json.loads(binding_path.read_text())
        if (binding.get('pass') is not True or binding.get('run_record_sha256') != sha(run_record)
                or binding.get('run_id') != run_record.parent.name):
            raise ValueError('successful same-run image binding required')
        entries = {e['path'].split('/')[-1]: e for e in record['artifacts']}
        if (binding.get('ota_sha256') != entries['lineage_ferrari-ota.zip']['sha256']
                or binding.get('target_files_sha256') != entries['lineage_ferrari-target_files.zip']['sha256']):
            raise ValueError('image binding refers to different packages')
        exported = binding.get('exported_recovery')
        if not exported or exported.get('source_member') != 'IMAGES/recovery.img':
            raise ValueError('image binding has no exported packaged recovery')
        recovery = Path(exported['path'])
        entry = exported
        rows = [r for r in binding['partitions'] if r['partition'] == 'recovery']
        if (len(rows) != 1 or rows[0].get('pass') is not True
                or entry['sha256'] != rows[0]['payload_sha256']
                or entry['bytes'] != rows[0]['bytes']
                or recovery.stat().st_size != entry['bytes'] or sha(recovery) != entry['sha256']):
            raise ValueError('exported recovery differs from bound payload image')
        binding_sha = sha(binding_path)
    image = bootimage.load(str(recovery), read_ramdisk=True)
    if image.sha256 != entry['sha256']:
        raise ValueError('loaded recovery differs from collector')
    if image.ramdisk.note or image.ramdisk.unpacked is None:
        raise ValueError('recovery ramdisk could not be decoded: '+str(image.ramdisk.note))
    files = {}
    for member in image.ramdisk_entries():
        name = member.name.removeprefix('./')
        if name in files:
            raise ValueError('duplicate recovery ramdisk path')
        files[name] = member
    if TRUST_PATH not in files or not files[TRUST_PATH].is_file:
        raise ValueError('recovery has no regular-file OTA trust archive')
    result = inspect_archive(files[TRUST_PATH].data, expected_cert.read_bytes())
    result.update(run_id=run_record.parent.name, run_record_sha256=sha(run_record),
                  recovery_sha256=entry['sha256'], expected_cert_file_sha256=sha(expected_cert),
                  trust_archive_path=TRUST_PATH,
                  embedded_kernel_bytes=image.kernel.size,
                  tool_sha256=sha(Path(__file__)),
                  parser_sha256=sha(Path(bootimage.__file__)),
                  image_binding_report_sha256=binding_sha,
                  limits='Packaged certificate trust only. No recovery boot, actual OTA/payload signature verification, install acceptance or restore test. A recovery with no embedded kernel uses the device boot stack.')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-record', type=Path, required=True)
    parser.add_argument('--expected-cert', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--image-binding-report', type=Path,
                        help='use the exact packaged recovery exported by a successful same-run image binding')
    args = parser.parse_args()
    result = verify(args.run_record, args.expected_cert, args.image_binding_report)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({k: result[k] for k in ('trust_pass','expected_certificate_present',
                     'forbidden_certificates_present','embedded_kernel_bytes')}))
    return 0 if result['trust_pass'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
