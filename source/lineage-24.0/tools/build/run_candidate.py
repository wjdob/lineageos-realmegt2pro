"""Apply and build the 23.2 candidate only inside a verified private overlay."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

from apply_recipe import isolated, safe_file
from check_candidate import check, sha_file, REPO
from reconstruct_candidate import reconstruct
from run_build import execute, reset_run_metrics, write_json
from signing_keys import stage_identity
sys.path.insert(0, str(REPO / 'tools'))
from build_identity import make_identity, read_metadata


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--target', choices=['nothing', 'recoveryimage', 'dtboimage', 'otapackage', 'check-elf-files'], required=True)
    parser.add_argument('--run', required=True)
    parser.add_argument('--jobs', type=int, default=5)
    parser.add_argument('--timeout', type=int, default=43200,
                        help='build deadline in seconds; default 12 hours for cold OTA builds')
    parser.add_argument('--max-used-gib', type=int, default=400,
                        help='Linux allocation ceiling; physical reserve is enforced separately')
    parser.add_argument('--min-free-gib', type=int, default=20,
                        help='Windows emergency floor, 5..20 GiB; lowering requires owner-reviewed storage scope')
    parser.add_argument('--signing-dir', type=Path, required=True,
                        help='private identity outside repository and source tree')
    args = parser.parse_args()
    if not args.run.startswith('candidate-') or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789-' for c in args.run):
        raise ValueError('use a distinct candidate- run name')
    if args.jobs < 1 or args.timeout < 1:
        raise ValueError('positive job count and timeout required')
    if not 1 <= args.max_used_gib <= 500:
        raise ValueError('allocation ceiling must be between 1 and the 500 GiB project budget')
    if not 5 <= args.min_free_gib <= 20:
        raise ValueError('Windows emergency floor must be between 5 and 20 GiB')
    tree = Path('/build/lineage')
    isolated(tree)
    records = REPO / '.local/goals/runs' / args.run
    evidence = REPO / '.local/lineage-23.2' / (args.run + '-inputs.json')
    if records.exists() or evidence.exists():
        raise ValueError('run records already exist')
    # Freeze real UTC once. A unique BUILD_NUMBER is a normal build.prop dependency;
    # BUILD_DATETIME alone is order-only in the pinned Soong rules.
    cached_ota = tree / 'out/target/product/ferrari/lineage_ferrari-ota.zip'
    previous_identity = read_metadata(cached_ota) if cached_ota.is_file() else None
    identity = make_identity(args.run, int(time.time()), previous_identity)
    if previous_identity is not None:
        identity['previous_ota_sha256'] = sha_file(cached_ota)
    recipe_path = REPO / 'tools/build/recipe-23.2.json'
    recipe = json.loads(recipe_path.read_text())
    checked = check(tree, canonical=True)
    release = tree / 'vendor/lineage/vars/aosp_target_release'
    if sha_file(release) != 'ec96431a7a156d7d69ffc90403f7d7362589a6929b6c7fd340fab5f191ed01cf':
        raise ValueError('release selection differs from reviewed source')
    scratch = Path(tempfile.mkdtemp(prefix=args.run + '-', dir=REPO / 'tmp'))
    inputs = scratch / 'inputs'
    for row in recipe['files']:
        target = safe_file(inputs, row['path'])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(subprocess.check_output(['git', '-C', str(tree / row['project']),
                                                    'show', row['revision'] + ':' + row['relative']]))
    reconstructed = scratch / 'reconstructed'
    reconstruct(inputs, reconstructed)
    source_regressions = {}
    if args.target == 'otapackage':
        recording_report = scratch / 'camera-recording-source.json'
        subprocess.run([sys.executable, str(REPO / 'tools/camera_profiles.py'),
                        '--source-tree', str(reconstructed), '--report', str(recording_report)],
                       check=True)
        source_regressions['camera_recording'] = {
            'report': str(recording_report), 'sha256': sha_file(recording_report)}
        filter_report = scratch / 'camera-vendor-filter-source.json'
        subprocess.run([sys.executable, str(REPO / 'tools/camera_vendor_filter.py'),
                        '--source-tree', str(reconstructed), '--report', str(filter_report)],
                       check=True)
        source_regressions['camera_vendor_filter'] = {
            'report': str(filter_report), 'sha256': sha_file(filter_report)}
    if args.target in ('otapackage', 'dtboimage'):
        regression_report = scratch / 'agm-source-check.json'
        subprocess.run([sys.executable, str(REPO / 'tools/agm_calibration.py'),
                        '--source-tree', str(reconstructed),
                        '--contract', str(REPO / 'configs/agm-calibration-23.2.json'),
                        '--report', str(regression_report)], check=True)
        source_regressions['agm_calibration'] = {
            'report': str(regression_report), 'sha256': sha_file(regression_report)}
        memory_report = scratch / 'fingerprint-memory-source.json'
        subprocess.run([sys.executable, str(REPO / 'tools/fingerprint_memory.py'),
                        '--source-tree', str(reconstructed), '--report', str(memory_report)], check=True)
        source_regressions['fingerprint_memory'] = {
            'report': str(memory_report), 'sha256': sha_file(memory_report)}
        bootstate_report = scratch / 'fingerprint-bootstate-source.json'
        subprocess.run([sys.executable, str(REPO / 'tools/fingerprint_bootstate.py'),
                        '--source-tree', str(reconstructed), '--report', str(bootstate_report)], check=True)
        source_regressions['fingerprint_bootstate'] = {
            'report': str(bootstate_report), 'sha256': sha_file(bootstate_report)}
    if args.target in ('otapackage', 'recoveryimage'):
        health_report = scratch / 'health-current-source.json'
        subprocess.run([sys.executable, str(REPO / 'tools/health_current.py'),
                        '--source-tree', str(reconstructed), '--report', str(health_report)], check=True)
        source_regressions['health_current'] = {
            'report': str(health_report), 'sha256': sha_file(health_report)}
    # All preimages, HEADs, LFS data and reconstruction hashes pass before any source write.
    for row in recipe['files']:
        target = safe_file(tree, row['path'])
        accepted = {row['base_sha256'], row['canonical_sha256'], *row.get('previous_sha256', [])}
        if sha_file(target) not in accepted:
            raise ValueError('unexpected preimage: ' + row['path'])
    for row in recipe.get('new_files', []):
        target = safe_file(tree, row['path'])
        if target.exists() and sha_file(target) not in {
                row['canonical_sha256'], *row.get('previous_sha256', [])}:
            raise ValueError('unexpected added-file preimage: ' + row['path'])
    isolated(tree)
    for row in [*recipe['files'], *recipe.get('new_files', [])]:
        target = safe_file(tree, row['path'])
        if target.exists() and sha_file(target) == row['canonical_sha256']:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(reconstructed / row['path'], target)
        if sha_file(target) != row['canonical_sha256']:
            raise ValueError('written hash differs: ' + row['path'])
    for fixup in recipe.get('binary_fixups', []):
        target = safe_file(tree, fixup['path'])
        tool = safe_file(tree, fixup['tool'])
        if sha_file(tool) != fixup['tool_sha256']:
            raise ValueError('binary fixup tool hash mismatch: ' + fixup['tool'])
        needed = subprocess.check_output([str(tool), '--print-needed', str(target)], text=True).splitlines()
        operation = fixup.get('operation', 'replace_needed')
        if sha_file(target) == fixup['result_sha256']:
            if needed.count(fixup['new_needed']) != 1 or (
                    operation == 'replace_needed' and fixup['old_needed'] in needed):
                raise ValueError('binary fixup cached output has wrong DT_NEEDED state: ' + fixup['path'])
            continue
        if sha_file(target) != fixup['source_sha256']:
            raise ValueError('binary fixup source hash mismatch: ' + fixup['path'])
        if fixup['new_needed'] in needed:
            raise ValueError('binary fixup DT_NEEDED precondition failed: ' + fixup['path'])
        if operation == 'replace_needed':
            if needed.count(fixup['old_needed']) != 1:
                raise ValueError('binary fixup source dependency mismatch: ' + fixup['path'])
            command = [str(tool), '--replace-needed', fixup['old_needed'], fixup['new_needed'], str(target)]
        elif operation == 'add_needed':
            command = [str(tool), '--add-needed', fixup['new_needed'], str(target)]
        else:
            raise ValueError('unsupported binary fixup operation: ' + operation)
        subprocess.run(command, check=True)
        needed = subprocess.check_output([str(tool), '--print-needed', str(target)], text=True).splitlines()
        if needed.count(fixup['new_needed']) != 1 or (
                operation == 'replace_needed' and fixup['old_needed'] in needed):
            raise ValueError('binary fixup DT_NEEDED postcondition failed: ' + fixup['path'])
        if sha_file(target) != fixup['result_sha256']:
            raise ValueError('binary fixup output hash mismatch: ' + fixup['path'])
    signing = stage_identity(tree, args.signing_dir, REPO / 'certs/rmx3301-releasekey.x509.pem')
    reset_run_metrics(tree)
    checked.update({'recipe_sha256': sha_file(recipe_path), 'target': args.target,
                    'recipe_snapshot': recipe, 'signing': signing, 'build_identity': identity,
                    'source_regressions': source_regressions,
                    'release': 'bp4a', 'reconstruction': str(reconstructed),
                    'python': sys.version, 'uname': list(os.uname()),
                    'storage_limits': {'windows_min_free_bytes': args.min_free_gib*1024**3,
                                       'linux_max_used_bytes': args.max_used_gib*1024**3},
                    'isolation': json.loads((tree / '.realme-next-isolated.json').read_text()),
                    'repository_commit': subprocess.check_output(['git', '-c', 'safe.directory=' + str(REPO),
                        '-C', str(REPO), 'rev-parse', 'HEAD'], text=True).strip(),
                    'source_hashes': {str(p.relative_to(REPO)): sha_file(p)
                        for p in [* (REPO / 'tools/build').glob('*.py'),
                                  * (REPO / 'tools/build').glob('*.sh'), recipe_path,
                                  REPO / recipe['manifest'],
                                  * (REPO / 'tools').glob('*.py'),
                                  * (REPO / 'tools/bootimg').glob('*.py'),
                                  * (REPO / 'configs').glob('*.json'),
                                  * [REPO / row['source'] for row in recipe.get('new_files', [])],
                                  REPO / 'certs/rmx3301-releasekey.x509.pem',
                                  * (REPO / 'patches/lineage-23.2').glob('*.patch')]}})
    snapshots = REPO / '.local/goals/run-inputs' / args.run
    snapshots.mkdir(parents=True, exist_ok=False)
    for relative, expected in checked['source_hashes'].items():
        destination = snapshots / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO / relative, destination)
        if sha_file(destination) != expected:
            raise ValueError('input changed during snapshot: ' + relative)
    checked['input_snapshot'] = str(snapshots)
    write_json(evidence, checked)
    artifacts = []
    product = 'out/target/product/ferrari/'
    if args.target == 'recoveryimage':
        artifacts = [product + 'recovery.img']
    elif args.target == 'dtboimage':
        # execute hides these cached images only in this new private overlay.
        # Rebuild DTBs as well as repacking DTBO: kernel.mk's image rule does not
        # directly depend on changed DTS files. Lower cache runs are preserved.
        artifacts = [product + 'dtbo.img', product + 'dtb.img']
    elif args.target == 'otapackage':
        artifacts = [product + 'lineage_ferrari-ota.zip', product + 'module-info.json',
                     product + 'obj/PACKAGING/target_files_intermediates/lineage_ferrari-target_files.zip',
                     product + 'recovery.img', product + 'dtb.img']
    result = execute(['bash', str(REPO / 'tools/build/build_candidate.sh'), args.target, str(args.jobs),
                      str(records / 'firmware-policy.json'), identity['build_number'],
                      str(identity['build_datetime']), str(evidence)],
                     tree, artifacts, records, timeout=args.timeout,
                     min_free=args.min_free_gib*1024**3,
                     max_used=args.max_used_gib*1024**3, allocation_path=Path('/build'))
    if result['state'] == 'success' and args.target == 'otapackage':
        target_files, = [row['collected'] for row in result['artifacts']
                         if row['path'].endswith('/lineage_ferrari-target_files.zip')]
        report = records / 'camera-recording-package.json'
        gate = subprocess.run([sys.executable, str(REPO / 'tools/camera_profiles.py'),
                               '--target-files', target_files, '--report', str(report)])
        # Keep the native build result separate from the post-build package gate.
        post_build = {'camera_recording': {'exit_code': gate.returncode,
                      'report': str(report),
                      'sha256': sha_file(report) if gate.returncode == 0 else None}}
        filter_report = records / 'camera-vendor-filter-package.json'
        filter_gate = subprocess.run([sys.executable, str(REPO / 'tools/camera_vendor_filter.py'),
                                     '--target-files', target_files, '--report', str(filter_report)])
        post_build['camera_vendor_filter'] = {
            'exit_code': filter_gate.returncode, 'report': str(filter_report),
            'sha256': sha_file(filter_report) if filter_gate.returncode == 0 else None}
        write_json(records / 'package-regressions.json', post_build)
        if gate.returncode != 0 or filter_gate.returncode != 0:
            print(json.dumps({'build': result['state'], 'package_regressions': post_build}, indent=2))
            return 1
    print(json.dumps(result, indent=2))
    return 0 if result['state'] == 'success' else 1


if __name__ == '__main__':
    raise SystemExit(main())
