"""Bind Ferrari's core display geometry and recording profiles to the candidate.

Source checks cannot prove delivery. Package checks inspect actual compiled RRO
resources and MediaProfiles precedence independently of source reconstruction.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
import zipfile

from package_coverage import bind_run_inputs
from payload_image_binding import collected

REPO = Path(__file__).resolve().parents[1]


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def bind_contract(inputs, contract_path):
    contract_path = Path(contract_path).resolve()
    expected = inputs.get('source_hashes', {})
    for path in (Path(__file__).resolve(), contract_path):
        if not path.is_relative_to(REPO):
            raise ValueError('checker/contract outside recorded repository')
        name = str(path.relative_to(REPO))
        if expected.get(name) != sha(path):
            raise ValueError('same-run checker/contract identity mismatch: '+name)
    contract = json.loads(contract_path.read_text())
    if contract.get('schema') != 1 or inputs.get('target') != 'otapackage':
        raise ValueError('reviewed core contract and OTA inputs required')
    rows = inputs.get('recipe_snapshot', {})
    recipe_files = {row['path']: row['canonical_sha256']
                    for row in [*rows.get('files', []), *rows.get('new_files', [])]}
    for row in contract['source_files']:
        if recipe_files.get(row['path']) != row['sha256']:
            raise ValueError('core source not bound to candidate recipe: '+row['path'])
    return contract


def check_source(tree, contract):
    tree = Path(tree).resolve()
    results = []
    issues = []
    for row in contract['source_files']:
        path = (tree/row['path']).resolve()
        if not path.is_relative_to(tree):
            raise ValueError('core path escapes source tree')
        actual = sha(path) if path.is_file() else None
        results.append(dict(path=row['path'], expected_sha256=row['sha256'], sha256=actual))
        if actual != row['sha256']:
            issues.append('core source missing or changed: '+row['path'])
    return dict(device_core_pass=not issues, issues=issues, source_files=results,
                limits='Exact reconstructed core source only; compiled package and runtime acceptance are separate.')


def resource_dimensions(dump):
    values = {}
    current = None
    for line in dump.splitlines():
        resource = re.search(r'\bresource 0x[0-9a-f]+ dimen/(\w+)\b', line)
        if resource:
            current = resource.group(1)
        elif re.search(r'\bresource 0x[0-9a-f]+ ', line):
            current = None
        elif current:
            match = re.fullmatch(r'\s*\(([^)]*)\)\s+(-?[0-9]+(?:\.[0-9]+)?)px\s*', line)
            if match:
                key = (current, match.group(1))
                if key in values:
                    raise ValueError('duplicate compiled dimension/configuration')
                values[key] = float(match.group(2))
    return values


def check_package(package, contract, aapt2, scratch):
    issues, overlays = [], []
    with zipfile.ZipFile(package) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError('duplicate target-files member')
        variants = set()
        for name in names:
            if (name.split('/')[0] in {'SYSTEM', 'SYSTEM_EXT', 'PRODUCT', 'VENDOR', 'ODM'}
                    and name.endswith('/build.prop')):
                for line in archive.read(name).decode().splitlines():
                    if line.startswith('ro.media.xml_variant.profiles='):
                        variants.add(line.split('=', 1)[1])
        if variants - {'_V1_0'}:
            issues.append('unreviewed MediaProfiles filename variant: '+str(sorted(variants)))
        candidates = ('PRODUCT/etc/media_profiles_V1_0.xml', 'ODM/etc/media_profiles_V1_0.xml',
                      'VENDOR/etc/media_profiles_V1_0.xml', 'SYSTEM/etc/media_profiles_V1_0.xml',
                      'SYSTEM/etc/media_profiles.xml')
        selected = next((name for name in candidates if name in names), None)
        profile = contract['profile']
        actual = hashlib.sha256(archive.read(selected)).hexdigest() if selected else None
        if selected != profile['member'] or actual != profile['sha256']:
            issues.append('actual MediaProfiles route/content differs from reviewed device profile')
        for index, row in enumerate(contract['overlays']):
            matches = [n for n in names if n.startswith('ODM/overlay/') and n.endswith('/'+row['apk'])]
            if len(matches) != 1:
                issues.append('one actual ODM overlay required: '+row['apk'])
                continue
            name = matches[0]
            path = Path(scratch)/(str(index)+'.apk')
            data = archive.read(name)
            path.write_bytes(data)
            run = subprocess.run([str(aapt2), 'dump', 'resources', str(path)],
                                 text=True, capture_output=True, timeout=60)
            if run.returncode:
                issues.append('unable to inspect compiled overlay: '+name)
                continue
            measured = resource_dimensions(run.stdout)
            local_issues = []
            for expected in row['dimensions']:
                key = (expected['name'], expected['configuration'])
                if measured.get(key) != expected['pixels']:
                    local_issues.append('compiled dimension differs: '+str(key))
            issues.extend(name+': '+issue for issue in local_issues)
            overlays.append(dict(member=name, sha256=hashlib.sha256(data).hexdigest(),
                                 issues=local_issues, resource_dump=run.stdout))
    return dict(device_core_pass=not issues, issues=issues, profile_member=selected,
                profile_sha256=actual, profile_variants=sorted(variants), overlays=overlays,
                limits='Actual recording-profile bytes/packaged precedence and compiled qualified RRO values. Runtime property overrides, idmap selection, physical camera limits and live display/recording acceptance remain separate.')


def main():
    parser = argparse.ArgumentParser()
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--source-tree', type=Path)
    modes.add_argument('--run-record', type=Path)
    modes.add_argument('--target-files', type=Path)
    parser.add_argument('--candidate-inputs', type=Path, required=True)
    parser.add_argument('--contract', type=Path, default=REPO/'configs/device-core-24.0.json')
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    inputs = json.loads(args.candidate_inputs.read_text())
    contract = bind_contract(inputs, args.contract)
    if args.source_tree:
        report = check_source(args.source_tree, contract)
    else:
        if args.run_record:
            bind_run_inputs(args.run_record, args.candidate_inputs)
            record = json.loads(args.run_record.read_text())
            if record.get('state') != 'success':
                raise ValueError('successful complete collector required')
            package, entry = collected(record, '/lineage_ferrari-target_files.zip')
        else:
            package = args.target_files
            entry = dict(sha256=sha(package))
        before = (package.stat().st_size, package.stat().st_mtime_ns)
        cache = Path(inputs['output_cache']['path'])
        if not cache.resolve().is_relative_to(Path('/mnt/lineage24-store/build-cache')):
            raise ValueError('unexpected native output cache')
        aapt2 = cache/'host/linux-x86/bin/aapt2'
        with tempfile.TemporaryDirectory(prefix='core24-') as scratch:
            report = check_package(package, contract, aapt2, scratch)
        if before != (package.stat().st_size, package.stat().st_mtime_ns):
            raise ValueError('target-files changed during core review')
        report.update(target_files_sha256=entry['sha256'], aapt2_sha256=sha(aapt2),
                      bound_to_successful_collector=bool(args.run_record))
    report.update(observed_utc=datetime.now(timezone.utc).isoformat(),
                  contract_sha256=sha(args.contract), candidate_inputs_sha256=sha(args.candidate_inputs),
                  checker_sha256=sha(Path(__file__)))
    args.report.write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(dict(device_core_pass=report['device_core_pass'], issues=report['issues'])))
    return 0 if report['device_core_pass'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
