"""Bind an external-firmware OTA's target hashes to same-run images and recovery.

This compares manifest target hashes; it does not reconstruct/apply payload operations.
"""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

from firmware_policy import exact_partitions
from payload_range import Source, load_manifest
from sparse_hash import image_hash


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for data in iter(lambda: stream.read(64 * 1024), b''):
            digest.update(data)
    return digest.hexdigest()


def collected(record, suffix):
    entries = [e for e in record.get('artifacts', []) if e['path'].endswith(suffix)]
    if len(entries) != 1:
        raise ValueError('one collected '+suffix+' required')
    entry = entries[0]
    path = Path(entry['collected'])
    if path.stat().st_size != entry['bytes'] or sha(path) != entry['sha256']:
        raise ValueError('collected artifact changed: '+str(path))
    return path, entry


def verify(run_record, export_recovery=None):
    run_record = Path(run_record)
    record = json.loads(run_record.read_text())
    if record.get('state') != 'success':
        raise ValueError('successful collector record required')
    ota, ota_entry = collected(record, '/lineage_ferrari-ota.zip')
    target, target_entry = collected(record, '/lineage_ferrari-target_files.zip')
    recovery, recovery_entry = collected(record, '/recovery.img')
    before = {str(p): (p.stat().st_size, p.stat().st_mtime_ns) for p in (ota,target,recovery)}
    rows = []
    exported = None
    with Source(str(ota)) as source, zipfile.ZipFile(target) as archive:
        manifest, _ = load_manifest(source)
        exact_partitions((p.name for p in manifest.partitions), 'OTA payload')
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError('duplicate target-files member')
        for partition in manifest.partitions:
            member = 'IMAGES/'+partition.name+'.img'
            row = {'partition': partition.name, 'member': member, 'pass': False}
            if partition.size is None or partition.hash is None or member not in names:
                row['issue'] = 'missing manifest target size/hash or target-files image'
                rows.append(row)
                continue
            with archive.open(member) as stream:
                measured = image_hash(stream, partition.size)
            row.update(bytes=measured['bytes'], sparse=measured['sparse'],
                       payload_sha256=partition.hash.hex(), target_files_expanded_sha256=measured['sha256'],
                       **{'pass': measured['sha256']==partition.hash.hex()})
            if partition.name == 'recovery':
                row['collected_recovery_matches'] = (measured['sha256']==recovery_entry['sha256']
                                                     and measured['bytes']==recovery_entry['bytes'])
                if export_recovery is not None:
                    if measured['sparse'] or not row['pass']:
                        raise ValueError('cannot export an unbound or sparse recovery')
                    destination = Path(export_recovery)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(member) as source, destination.open('xb') as output:
                        for block in iter(lambda: source.read(65536), b''):
                            output.write(block)
                    exported = {'path': str(destination.resolve()), 'bytes': destination.stat().st_size,
                                'sha256': sha(destination), 'source_member': member}
                    row['exported_recovery_matches'] = (exported['sha256']==measured['sha256']
                                                        and exported['bytes']==measured['bytes'])
                    row['pass'] = row['pass'] and row['exported_recovery_matches']
                else:
                    row['pass'] = row['pass'] and row['collected_recovery_matches']
            rows.append(row)
    after = {str(p): (p.stat().st_size, p.stat().st_mtime_ns) for p in (ota,target,recovery)}
    if before != after:
        raise ValueError('collected artifact changed during inspection')
    tools = ('payload_image_binding.py','payload_range.py','sparse_hash.py','firmware_policy.py')
    return {'pass': bool(rows) and all(row['pass'] for row in rows),
            'run_id': run_record.parent.name, 'run_record_sha256': sha(run_record),
            'ota_sha256': ota_entry['sha256'], 'target_files_sha256': target_entry['sha256'],
            'recovery_sha256': exported['sha256'] if exported else recovery_entry['sha256'],
            'collected_build_recovery_sha256': recovery_entry['sha256'],
            'exported_recovery': exported, 'partitions': rows,
            'tool_sha256': {name: sha(Path(__file__).parent/name) for name in tools},
            'limits': 'Expanded target-files sizes/hashes vs payload manifest and same-run recovery; no operation reconstruction/application, recovery trust or device compatibility test.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-record', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--export-recovery', type=Path,
                        help='export the exact target-files recovery to a NEW file and bind it to the OTA; preserve the separately collected build image')
    args = parser.parse_args()
    result = verify(args.run_record, args.export_recovery)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({'pass': result['pass'], 'partitions': len(result['partitions']),
                      'failed': [r['partition'] for r in result['partitions'] if not r['pass']]}))
    return 0 if result['pass'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
