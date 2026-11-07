"""Read-only preflight for the SSD-backed lineage-24.0 store.

Never syncs, applies or builds. It checks the dedicated SSD ext4 store, the
pinned tree identity and the signing identity so a later build refusal is
explicit.
"""
import argparse
import json
import shutil
import subprocess
from pathlib import Path
import sys
import tempfile
from datetime import datetime, timezone

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / 'tools/build'))
from apply_candidate_recipe import apply
from signing_keys import inspect_identity
from manifest import read_pins
from check_candidate import check as check_checkout, EXCLUDED, sha_file
from storage_24 import verify_store, HOST
from vendor_input_24 import verify_provider
from common_runtime_24 import verify_provider as verify_common
from kernel_layout_24 import check as check_kernel_layout

STORE = Path('/mnt/lineage24-store')
TREE = STORE / 'tree'
BUILD_TREE = Path('/build/lineage-24.0')
MANIFEST = REPO / 'manifests/lineage-24.0-candidate.xml'
RECIPE = REPO / 'tools/build/recipe-24.0.json'


def gib(value):
    return round(value / 1024**3, 2)


def mountpoint(path):
    return subprocess.run(['mountpoint', '-q', str(path)]).returncode == 0


def filesystem(path):
    return subprocess.run(['findmnt', '-n', '-o', 'FSTYPE', '-T', str(path)],
                          capture_output=True, text=True).stdout.strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase', choices=('sync', 'build'), required=True)
    parser.add_argument('--host-free-gib', type=float,
                        help='override the host C: floor (sync 120, build 40)')
    parser.add_argument('--store-free-gib', type=float,
                        help='override the store floor (sync 150, build 40)')
    parser.add_argument('--signing-dir', type=Path,
                        default=Path('/root/.local/share/realmegt2pro-next/signing/rmx3301-mvp'))
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    if args.report and args.report.exists():
        raise ValueError('use a new report path; previous evidence is preserved')
    host_required = args.host_free_gib if args.host_free_gib is not None else (
        120 if args.phase == 'sync' else 40)
    store_required = args.store_free_gib if args.store_free_gib is not None else (
        150 if args.phase == 'sync' else 40)
    if host_required <= 0 or store_required <= 0:
        raise ValueError('positive storage thresholds required')
    report = {
        'schema': 1, 'phase': args.phase, 'ok': True, 'checks': {},
        'recorded_utc': datetime.now(timezone.utc).isoformat(),
        'host': {'mount': str(HOST), 'required_gib': host_required},
        'store': {'mount': str(STORE), 'tree': str(TREE), 'build_tree': str(BUILD_TREE),
                  'required_gib': store_required},
        'limits': 'Read-only preflight; it does not sync, apply, build or touch the device.',
    }
    checks = report['checks']

    def fail(name, detail):
        checks[name] = {'ok': False, 'detail': detail}
        report['ok'] = False

    storage_ok = False
    try:
        report['storage_identity'] = verify_store()
        storage_ok = True
        checks['storage_identity'] = {'ok': True, 'detail': 'SSD WSL backing and ext4 paths verified'}
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        fail('storage_identity', str(exc))

    if not mountpoint(HOST):
        fail('host_mount', f'{HOST} is not mounted; run mount_24.sh')
    else:
        free = shutil.disk_usage(HOST).free
        report['host']['free_bytes'] = free
        report['host']['free_gib'] = gib(free)
        if free < host_required * 1024**3:
            fail('host_free', f'C: has {gib(free)} GiB free; {host_required} GiB required')
        else:
            checks['host_free'] = {'ok': True, 'detail': f'{gib(free)} GiB free'}

    if not mountpoint(STORE):
        fail('store_mount', f'{STORE} is not mounted; run mount_24.sh')
    else:
        fs = filesystem(STORE)
        checks['store_filesystem'] = {'ok': fs == 'ext4', 'detail': fs}
        if fs != 'ext4':
            report['ok'] = False
        free = shutil.disk_usage(STORE).free
        report['store']['free_bytes'] = free
        report['store']['free_gib'] = gib(free)
        if free < store_required * 1024**3:
            fail('store_free', f'24.0 store has {gib(free)} GiB free; {store_required} GiB required')
        else:
            checks['store_free'] = {'ok': True, 'detail': f'{gib(free)} GiB free'}

    if TREE == Path('/build/lineage'):
        fail('tree_separation', 'refusing the preserved 23.2 tree')
    elif not TREE.is_dir():
        if args.phase == 'sync':
            checks['tree'] = {'ok': True, 'detail': 'tree absent; sync may create it'}
        else:
            fail('tree', 'tree is absent; sync the pinned manifest first')
    else:
        checks['tree'] = {'ok': True, 'detail': 'tree exists'}
        project_list = TREE / '.repo/project.list'
        if not project_list.is_file():
            if args.phase == 'build':
                fail('project_list', 'missing .repo/project.list; sync is incomplete')
            else:
                checks['project_list'] = {'ok': False,
                                          'detail': 'missing; sync is incomplete'}
        else:
            count = len(project_list.read_text().splitlines())
            selected = {path for _, path in read_pins(MANIFEST) if path not in EXCLUDED}
            expected = len(selected)
            listed = project_list.read_text().splitlines()
            matches = len(listed) == len(set(listed)) and set(listed) == selected
            checks['project_list'] = {'ok': matches,
                                      'detail': f'{count} entries; expected {expected}'}
            if not matches:
                report['ok'] = False
            release = TREE / 'vendor/lineage/vars/aosp_target_release'
            if not release.is_file():
                fail('release', 'missing vendor/lineage/vars/aosp_target_release')
            else:
                lines = [line.strip() for line in release.read_text().splitlines()
                         if line.strip() and not line.strip().startswith('#')]
                value = lines[-1] if lines else ''
                checks['release'] = {'ok': value == 'aosp_target_release=cp2a',
                                     'detail': repr(value)}
                if value != 'aosp_target_release=cp2a':
                    report['ok'] = False
        if args.phase == 'build' and storage_ok:
            try:
                vendor, provider = verify_provider()
                checks['vendor_inputs'] = {'ok': True, 'files': len(vendor['files']),
                                           'provider': str(provider)}
            except Exception as exc:
                fail('vendor_inputs', repr(exc))
            common = None
            try:
                common, provider = verify_common()
                checks['common_runtime_inputs'] = {'ok': True, 'files': len(common['files']),
                                                   'provider': str(provider)}
            except Exception as exc:
                fail('common_runtime_inputs', repr(exc))
            try:
                scratch = Path(tempfile.mkdtemp(prefix='preflight-', dir=STORE / 'tmp')) / 'recipe'
                result = apply(TREE, RECIPE, scratch, write=False, scratch_root=STORE / 'tmp')
                checks['recipe'] = {'ok': result['reconstruction']['reconstruction'] == 'verified',
                                    'detail': f"{result['reconstruction']['files']} files reconstructed", 'scratch': str(scratch)}
                checks['kernel_layout']=check_kernel_layout(TREE,scratch)
                # Reconstructed metadata plus unchanged source-defined HIDL APIs.
                if common is not None:
                    for row in common['metadata']:
                        if sha_file(scratch / row['path']) != row['sha256']:
                            raise ValueError('common runtime metadata differs: ' + row['path'])
                    for row in common['interface_sources']:
                        if sha_file(TREE / row['path']) != row['sha256']:
                            raise ValueError('common HIDL source differs: ' + row['path'])
            except Exception as exc:
                fail('recipe', repr(exc))
            try:
                identity = check_checkout(TREE, canonical=False, recipe_path=RECIPE)
                checks['source_identity'] = {'ok': True, 'projects': len(identity['projects']),
                                             'lfs_content_verified': identity['lfs_content_verified']}
                report['source_identity'] = identity
            except Exception as exc:
                fail('source_identity', repr(exc))
            try:
                identities = inspect_identity(args.signing_dir)
                checks['signing'] = {'ok': True, 'detail': sorted(identities)}
            except Exception as exc:
                fail('signing', repr(exc))
    c_free = shutil.disk_usage('/mnt/c').free
    report['host_c'] = {'free_gib': gib(c_free),
                        'warning': None if c_free >= host_required * 1024**3 else 'below selected SSD reserve'}
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
