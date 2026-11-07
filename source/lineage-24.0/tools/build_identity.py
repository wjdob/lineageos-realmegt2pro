"""Bind native build identity to the run and reject stale packaged properties."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import zipfile


METADATA = 'META-INF/com/android/metadata'


def fields(text, keys):
    result = {}
    for line in text.splitlines():
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        if key in keys:
            if key in result:
                raise ValueError('duplicate identity field: ' + key)
            result[key] = value
    return result


def read_metadata(ota):
    with zipfile.ZipFile(ota) as archive:
        if archive.namelist().count(METADATA) != 1:
            raise ValueError('exactly one OTA metadata member required')
        result = fields(archive.read(METADATA).decode(),
                        {'post-timestamp', 'post-build-incremental'})
    if not re.fullmatch(r'[0-9]+', result.get('post-timestamp', '')):
        raise ValueError('invalid previous/package OTA timestamp')
    if not result.get('post-build-incremental'):
        raise ValueError('missing OTA incremental identity')
    return result


def make_identity(run, timestamp, previous=None):
    if not re.fullmatch(r'candidate-[a-z0-9-]+', run):
        raise ValueError('invalid candidate run name')
    if type(timestamp) is not int or not 0 < timestamp < 2**32:
        raise ValueError('invalid UTC epoch seconds')
    old_timestamp = None
    if previous is not None:
        value = previous.get('post-timestamp', '')
        if not isinstance(value, str) or not re.fullmatch(r'[0-9]+', value):
            raise ValueError('invalid previous OTA timestamp')
        old_timestamp = int(value)
        if timestamp <= old_timestamp:
            raise ValueError('current UTC time does not advance previous OTA; inspect clock, do not alter timestamps')
    number = 'RMX3301.' + str(timestamp) + '.' + hashlib.sha256(run.encode()).hexdigest()[:12]
    if previous and number == previous.get('post-build-incremental'):
        raise ValueError('build number reuses previous OTA')
    return {'schema': 1, 'run': run, 'build_number': number,
            'build_datetime': timestamp, 'previous_timestamp': old_timestamp,
            'previous_incremental': previous.get('post-build-incremental') if previous else None}


def validate_identity(identity):
    previous = None
    if identity.get('previous_timestamp') is not None:
        previous = {'post-timestamp': str(identity['previous_timestamp']),
                    'post-build-incremental': identity.get('previous_incremental')}
    expected = make_identity(identity['run'], identity['build_datetime'], previous)
    if any(identity.get(key) != value for key, value in expected.items()):
        raise ValueError('run/build identity binding differs')
    return expected


def check(ota, target_files, identity):
    validate_identity(identity)
    metadata = read_metadata(ota)
    wanted = {'post-timestamp': str(identity['build_datetime']),
              'post-build-incremental': identity['build_number']}
    if metadata != wanted:
        raise ValueError('OTA identity differs from recorded build; cached properties are not accepted')
    with zipfile.ZipFile(target_files) as archive:
        names = archive.namelist()
        members = [name for name in names if name in ('SYSTEM/build.prop', 'SYSTEM/system/build.prop')]
        if len(members) != 1:
            raise ValueError('exactly one system build.prop required')
        member = members[0]
        expected = {'ro.build.date.utc': wanted['post-timestamp'],
                    'ro.system.build.date.utc': wanted['post-timestamp'],
                    'ro.build.version.incremental': wanted['post-build-incremental'],
                    'ro.system.build.version.incremental': wanted['post-build-incremental']}
        actual = fields(archive.read(member).decode(), set(expected))
        if actual != expected:
            raise ValueError('packaged system properties differ from recorded build identity')
    return {'pass': True, 'build_identity': identity, 'ota_metadata': metadata,
            'system_properties_member': member, 'system_identity_properties': actual,
            'limits': 'Run-bound OTA/system identity only. Signature, payload/image binding, '
                      'firmware policy, source/security coverage and runtime acceptance are separate.'}


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate-inputs', type=Path, required=True)
    parser.add_argument('--ota', type=Path, required=True)
    parser.add_argument('--target-files', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    if args.report.exists():
        raise ValueError('preserve existing identity report; use a new path')
    report = {'pass': False}
    try:
        inputs = json.loads(args.candidate_inputs.read_text())
        expected_source = inputs['source_hashes']['tools/build_identity.py']
        if sha(Path(__file__)) != expected_source:
            raise ValueError('identity checker differs from same-run input snapshot')
        report = check(args.ota, args.target_files, inputs['build_identity'])
        report.update(candidate_inputs_sha256=sha(args.candidate_inputs),
                      ota_sha256=sha(args.ota), target_files_sha256=sha(args.target_files),
                      tool_sha256=expected_source)
    except (ValueError, KeyError, OSError, zipfile.BadZipFile) as error:
        report['error'] = str(error)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))
    return 0 if report['pass'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
