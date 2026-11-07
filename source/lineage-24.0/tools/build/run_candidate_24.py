"""Verify, apply and build the pinned lineage-24.0 source graph.

This is the first-build path while the long-lived 23.2 runner remains untouched.
It requires a separately synced SSD-backed store mounted at /mnt/lineage24-store
and a private overlay at /build/lineage-24.0. Build records and artifacts stay
in that store; only the small runner inputs/scratch use the workspace.
"""
import argparse
from contextlib import ExitStack
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

from apply_candidate_recipe import apply
from apply_recipe import isolated
from check_candidate import check, sha_file, REPO
from run_build import execute, reset_run_metrics, write_json
from signing_keys import stage_identity
from storage_24 import verify_store, fresh_lower, HOST
from workspace_revision_24 import revision as workspace_revision
from vendor_input_24 import materialize, verify_provider
from common_runtime_24 import materialize as materialize_common, verify_provider as verify_common
from output_cache_24 import output_cache, vendor_freshness, record_vendor_success
from kernel_layout_24 import check as check_kernel_layout
sys.path.insert(0, str(REPO / 'tools'))
from build_identity import make_identity, read_metadata


def required_artifacts(target):
    """Collect actual build outputs; boot-stack acceptance uses target-files.

    This cohort creates vendor_boot inside target-files without a loose product
    image. Its absence outside that ZIP is not a missing packaged partition.
    The 13-image firmware policy and payload/image binding remain mandatory.
    """
    product = 'out/target/product/ferrari/'
    if target == 'otapackage':
        return [product + name for name in (
            'lineage_ferrari-ota.zip', 'module-info.json',
            'obj/PACKAGING/target_files_intermediates/lineage_ferrari-target_files.zip',
            'recovery.img', 'boot.img', 'dtbo.img', 'dtb.img')]
    if target == 'codec2-provider':
        return [product + 'vendor/lib64/libcodec2_hidl@1.0.so']
    if target == 'init-diagnostic':
        return [product + 'ramdisk/init', product + 'system/bin/init']
    if target in ('nothing', 'check-elf-files'):
        return []
    raise ValueError('unknown candidate artifact target')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--target', choices=['nothing', 'check-elf-files', 'codec2-provider', 'init-diagnostic', 'otapackage'], required=True)
    parser.add_argument('--run', required=True)
    parser.add_argument('--jobs', type=int, default=5)
    parser.add_argument('--timeout', type=int, default=43200,
                        help='build deadline in seconds; default 12 hours')
    parser.add_argument('--max-used-gib', type=int, default=300)
    parser.add_argument('--min-free-gib', type=int, default=40)
    parser.add_argument('--tree', type=Path, default=Path('/build/lineage-24.0'))
    parser.add_argument('--store', type=Path, default=Path('/mnt/lineage24-store'))
    parser.add_argument('--signing-dir', type=Path, required=True)
    parser.add_argument('--prepare-only', action='store_true',
                        help='verify and stage inputs in a private overlay, then stop before any build command')
    args = parser.parse_args()
    with ExitStack() as leases:
        return run(args,leases)


def run(args,leases):
    if not args.run.startswith('candidate-') or any(
            c not in 'abcdefghijklmnopqrstuvwxyz0123456789-' for c in args.run):
        raise ValueError('use a distinct candidate- run name')
    if args.jobs < 1 or args.timeout < 1:
        raise ValueError('positive job count and timeout required')
    if not 1 <= args.max_used_gib <= 500:
        raise ValueError('allocation ceiling must be between 1 and the 500 GiB project budget')
    if not 20 <= args.min_free_gib <= 100:
        raise ValueError('SSD emergency floor must be between 20 and 100 GiB')
    tree = args.tree.resolve()
    store = args.store.resolve()
    storage_identity = verify_store(store)
    if tree == Path('/build/lineage'):
        raise ValueError('refusing the preserved 23.2 tree')
    isolated(tree)
    lower=fresh_lower(tree,store,args.run)
    repository_commit=workspace_revision(REPO)
    recipe_path = REPO / 'tools/build/recipe-24.0.json'
    records = store / 'records' / args.run
    evidence = store / 'evidence' / (args.run + '-inputs.json')
    source_record=store/'evidence'/(args.run+'-source.json')
    if records.exists() or evidence.exists() or source_record.exists():
        raise ValueError('run records already exist')
    recipe = json.loads(recipe_path.read_text())
    checked = check(lower, canonical=False, recipe_path=recipe_path)
    write_json(source_record,checked)
    checked['source_identity_record']={'path':str(source_record),'sha256':sha_file(source_record)}
    vendor_contract, _ = verify_provider(store)
    common_contract, _ = verify_common(store)
    required = sum(row['bytes'] for row in vendor_contract['files'] + common_contract['files'])
    for path in (store, HOST):
        if shutil.disk_usage(path).free < args.min_free_gib * 1024**3 + required:
            raise ValueError('insufficient staging and build reserve: ' + str(path))
    # Recipe reconstruction is verified again inside this process before a write.
    (store / 'tmp').mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix=args.run + '-', dir=store / 'tmp'))
    shutil.rmtree(scratch)
    applied = apply(tree, recipe_path, scratch, write=True, scratch_root=store / 'tmp')
    vendor = materialize(tree, store)
    common = materialize_common(tree, store)
    signing = stage_identity(tree, args.signing_dir, REPO / 'certs/rmx3301-releasekey.x509.pem')
    kernel_layout=check_kernel_layout(tree)
    cache = None
    if not args.prepare_only:
        cache=leases.enter_context(output_cache(tree,store,recipe['manifest_sha256'],
            sha_file(REPO/'certs/rmx3301-releasekey.x509.pem')))
        cache['vendor_freshness'] = vendor_freshness(tree, Path(cache['path']), vendor_contract)
    cached_ota = tree / 'out/target/product/ferrari/lineage_ferrari-ota.zip'
    previous_identity = read_metadata(cached_ota) if cached_ota.is_file() else None
    identity = make_identity(args.run, int(time.time()), previous_identity)
    if previous_identity is not None:
        identity['previous_ota_sha256'] = sha_file(cached_ota)
    reset_run_metrics(tree)
    checked.update({
        'target': args.target, 'recipe_sha256': sha_file(recipe_path),
        'storage_identity': storage_identity,
        'output_cache': cache,
        'kernel_layout':kernel_layout,
        'vendor_inputs': vendor,
        'common_runtime': common,
        'recipe_snapshot': recipe, 'signing': signing, 'build_identity': identity,
        'applied': applied, 'release': 'cp2a',
        'python': sys.version, 'uname': list(os.uname()),
        'storage_limits': {'host_drive': 'C', 'host_min_free_bytes': args.min_free_gib * 1024**3,
                           'host_max_growth_bytes': args.max_used_gib * 1024**3},
        'isolation': json.loads((tree / '.realme-next-isolated.json').read_text()),
        'repository_commit': repository_commit,
        'source_hashes': {str(p.relative_to(REPO)): sha_file(p) for p in [
            *sorted((REPO / 'tools').glob('*.py')),
            *sorted((REPO / 'tools/build').glob('*.py')),
            *sorted((REPO / 'tools/build').glob('*.sh')),
            recipe_path, REPO / recipe['manifest'],
            *sorted((REPO / 'patches/lineage-24.0').glob('*.patch')),
            *sorted((REPO / 'configs').glob('*24.0*.json')),
            REPO / 'certs/rmx3301-releasekey.x509.pem']},
    })
    write_json(evidence, checked)
    if args.prepare_only:
        records.mkdir(parents=True, exist_ok=False)
        report = {'state': 'prepared', 'native_build_started': False,
                  'candidate_inputs': str(evidence), 'candidate_inputs_sha256': sha_file(evidence),
                  'vendor_files': vendor['files_verified'], 'projects': len(checked['projects']),
                  'common_runtime_files': common['files_verified'],
                  'limits': 'Preparation only. No m, Soong, Ninja, compiler, package or device acceptance.'}
        write_json(records / 'preparation.json', report)
        print(json.dumps(report, indent=2))
        return 0
    artifacts = required_artifacts(args.target)
    baseline_used = shutil.disk_usage(HOST).used
    result = None
    try:
        result = execute(
            ['bash', str(REPO / 'tools/build/build_candidate_24.0.sh'), args.target, str(args.jobs),
             str(records / 'firmware-policy.json'), identity['build_number'],
             str(identity['build_datetime']), str(evidence)],
            tree, artifacts, records, timeout=args.timeout,
            min_free=args.min_free_gib * 1024**3,
            max_used=baseline_used + args.max_used_gib * 1024**3,
            allocation_path=HOST, space_path=HOST,
            extra_space_floors=((store, args.min_free_gib * 1024**3),))
    finally:
        if args.target == 'init-diagnostic':
            from init_diagnostic_cache_24 import retire
            try:
                retire(Path(cache['path']), records / 'init-cache-retired.json')
            except Exception as exc:
                if result is not None:
                    result['state'] = 'failed'
                    result['diagnostic_cleanup_error'] = str(exc)
                    write_json(records / 'result.json', result)
                raise
    if args.target == 'otapackage' and result['state'] == 'success':
        record_vendor_success(cache['vendor_freshness'], records / 'result.json')
    print(json.dumps(result, indent=2))
    return 0 if result['state'] == 'success' else 1


if __name__ == '__main__':
    raise SystemExit(main())
