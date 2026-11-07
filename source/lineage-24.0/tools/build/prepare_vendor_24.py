"""Re-extract the 24.0 Ferrari vendor project offline inside a private overlay.

The source contract contains hashes, never proprietary bytes. Inputs and outputs
are kept in the dedicated SSD ext4 store. No compiler, repo sync or device command.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys

from apply_recipe import isolated
from storage_24 import STORE, verify_store

REPO = Path(__file__).resolve().parents[2]
CONTRACT = REPO / 'configs/lineage-24.0-vendor-inputs.json'


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def vendor_inputs(source, contract):
    source = Path(source).resolve()
    result = []
    directory_names = {}
    for row in contract['files']:
        # Case-insensitive staging can silently alias distinct OEM filenames.
        # Resolve each component by its actual directory entry before hashing.
        exact_source_name(source, row['source'], directory_names)
        path = source / row['source']
        if not path.resolve().is_relative_to(source) or not path.is_file():
            raise ValueError('missing or escaped stock input: ' + row['source'])
        if path.stat().st_size != row['bytes'] or sha(path) != row['sha256']:
            raise ValueError('stock input differs from reviewed source: ' + row['source'])
        result.append(row)
    return result


def exact_source_name(root, name, directory_names=None):
    parts = PurePosixPath(name).parts
    if (not name or name.startswith('/') or '\\' in name or ':' in name
            or any(part in ('', '.', '..') for part in name.split('/'))):
        raise ValueError('unsafe stock input name: ' + name)
    directory_names = {} if directory_names is None else directory_names
    current = Path(root)
    for part in parts:
        if current not in directory_names:
            directory_names[current] = {entry.name for entry in current.iterdir()}
        if part not in directory_names[current]:
            raise ValueError('missing exact-case stock input: ' + name)
        current = current / part
    return current


def expected_outputs(vendor, contract):
    """Require the reviewed deferred-provider cohort before publishing its copy."""
    for name, expected in contract.get('expected_outputs', {}).items():
        parts = PurePosixPath(name).parts
        if (not name or name.startswith('/') or '\\' in name or ':' in name
                or any(p in ('', '.', '..') for p in name.split('/'))
                or not parts or parts[0] != 'proprietary'
                or not re.fullmatch('[0-9a-f]{64}', expected)):
            raise ValueError('invalid expected vendor output binding')
        path = vendor / name
        if not path.resolve().is_relative_to(vendor.resolve()) or not path.is_file():
            raise ValueError('missing or escaped expected vendor output: ' + name)
        if sha(path) != expected:
            raise ValueError('extracted vendor cohort differs: ' + name)


def prepare(tree, source, output):
    verify_store()
    isolated(tree)
    if tree != Path('/build/lineage-24.0'):
        raise ValueError('24.0 private overlay required')
    if output.exists() or not output.resolve().is_relative_to(STORE / 'inputs'):
        raise ValueError('new output under the dedicated SSD input store required')
    contract = json.loads(CONTRACT.read_text())
    vendor_inputs(source, contract)
    for relative, digest in contract['extraction_sources'].items():
        if sha(tree / relative) != digest:
            raise ValueError('extraction implementation changed: ' + relative)
    sys.path.insert(0, str(tree / 'tools/extract-utils'))
    # Import the hash-bound device recipe. It owns the complete fixups, including
    # tuple-flattened ziparchive handling and the distinct OEM Camera NDK ABI.
    module_path = tree / 'device/realme/ferrari/extract-files.py'
    spec = importlib.util.spec_from_file_location('ferrari_vendor24', module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    from extract_utils.main import ExtractUtils
    # Upstream explicitly permits this option for private/local extraction.
    # These OEM inputs are not committed or approved for redistribution.
    sys.argv = [str(module_path), '--only-target', '--allow-prohibited-files', str(source)]
    ExtractUtils.device(module.module).run()
    vendor = tree / 'vendor/realme/ferrari'
    destinations = {row['destination'] for row in contract['files']}
    names = ['Android.bp', 'Android.mk', 'BoardConfigVendor.mk', 'ferrari-vendor.mk']
    names += ['proprietary/' + name for name in sorted(destinations)]
    for name in names:
        if not (vendor / name).is_file():
            raise ValueError('extraction did not produce required file: ' + name)
    expected_outputs(vendor, contract)
    # The upstream firmware extractor is not selected. Independently ensure no
    # low-level OTA/radio registration survived the generated makefiles.
    for name in ('Android.mk', 'BoardConfigVendor.mk', 'ferrari-vendor.mk'):
        data = (vendor / name).read_text()
        if 'AB_OTA_PARTITIONS' in data or 'add-radio-file' in data or '/radio/' in data:
            raise ValueError('generated vendor tries to register firmware: ' + name)
    output.mkdir(parents=True, exist_ok=False)
    files = []
    for name in names:
        src = vendor / name
        dst = output / name
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        digest = sha(src)
        if sha(dst) != digest:
            raise ValueError('vendor output copy differs: ' + name)
        files.append({'path': name, 'bytes': dst.stat().st_size, 'sha256': digest})
    report = {'schema': 1, 'source_contract_sha256': sha(CONTRACT),
              'distribution_scope': 'Private local engineering only; OEM assets are not approved for redistribution.',
              'input_files': len(contract['files']), 'files': files,
              'implementation_sha256': sha(Path(__file__)),
              'fixups': ['hash-bound 24.0 device extraction recipe', 'retain ziparchive alias fixup',
                         'use reviewed v33 camera NDK foundation ABI',
                         'isolate OEM Camera NDK SONAME and its face-service caller',
                         'retain .1410 AlgoInterface/AlgoProcess cohort with one optional LUT resource path change',
                         'restore the hash-bound deferred native filter provider'],
              'expected_outputs': contract.get('expected_outputs', {}),
              'limits': 'Offline extraction only; no Soong, compilation, package or hardware acceptance.'}
    (output / 'receipt.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tree', type=Path, default=Path('/build/lineage-24.0'))
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = prepare(args.tree, args.source, args.output)
    print(json.dumps({'files': len(report['files']), 'output': str(args.output)}))


if __name__ == '__main__':
    main()
