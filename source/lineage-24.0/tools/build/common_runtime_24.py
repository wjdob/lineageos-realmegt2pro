"""Deliver the reviewed SM8450 performance runtime in a private build overlay."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import stat
import zipfile

from apply_recipe import isolated, safe_file
from storage_24 import STORE, BUILD_TREE, verify_store

REPO = Path(__file__).resolve().parents[2]
CONTRACT = REPO / 'configs/common-runtime-24.0.json'


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def rows(contract):
    result = contract['files']
    if contract.get('schema') != 1 or not result:
        raise ValueError('nonempty common runtime contract required')
    seen = set()
    for row in result:
        name = row['path']
        parts = PurePosixPath(name).parts
        if (name in seen or '\\' in name or ':' in name or
                any(p in ('', '.', '..') for p in name.split('/')) or
                len(parts) < 4 or parts[:2] != ('proprietary', 'vendor') or
                parts[2] not in ('bin', 'etc', 'lib64') or
                row['member'] != 'VENDOR/' + '/'.join(parts[2:])):
            raise ValueError('unsafe or duplicate common runtime destination: ' + name)
        seen.add(name)
    return result


def validate_provider(contract, provider):
    """Validate every source before a caller changes any destination."""
    for row in rows(contract):
        file = safe_file(provider, row['path'])
        if not file.is_file() or file.stat().st_size != row['bytes'] or sha(file) != row['sha256']:
            raise ValueError('common runtime input changed: ' + row['path'])
    return len(contract['files'])


def verify_provider(store=STORE):
    verify_store(store)
    contract = json.loads(CONTRACT.read_text())
    name = contract['provider']
    if (PurePosixPath(name).parts[:1] != ('inputs',) or '\\' in name or
            ':' in name or any(p in ('', '.', '..') for p in name.split('/'))):
        raise ValueError('common runtime provider must be under the dedicated inputs store')
    provider = safe_file(store, name)
    receipt_path = safe_file(provider, 'receipt.json')
    receipt = json.loads(receipt_path.read_text())
    if (receipt['contract_sha256'] != sha(CONTRACT) or
            receipt['preparer_sha256'] != sha(REPO / 'tools/build/prepare_common_runtime_24.py') or
            receipt['source_sha256'] != contract['source']['sha256'] or
            receipt['files'] != contract['files']):
        raise ValueError('common runtime receipt differs from the reviewed extraction')
    validate_provider(contract, provider)
    return contract, provider


def check_source(tree, contract):
    """Bind the source-selected interface APIs and generated build metadata."""
    for row in contract['metadata'] + contract['interface_sources']:
        file = safe_file(tree, row['path'])
        if not file.is_file() or sha(file) != row['sha256']:
            raise ValueError('common runtime source requires renewed review: ' + row['path'])


def materialize(tree, store=STORE):
    isolated(tree)
    if tree != BUILD_TREE:
        raise ValueError('24.0 private overlay required')
    contract, provider = verify_provider(store)
    check_source(tree, contract)
    vendor = tree / 'vendor/oneplus/sm8450-common'
    planned = []
    for row in rows(contract):
        dst = safe_file(vendor, row['path'])
        if dst.exists() and (not dst.is_file() or sha(dst) != row['sha256']):
            raise ValueError('unexpected common runtime preimage: ' + row['path'])
        planned.append((row, dst))
    written = []
    for row, dst in planned:
        if dst.exists():
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(provider / row['path'], dst)
        if sha(dst) != row['sha256']:
            raise ValueError('common runtime copy differs: ' + row['path'])
        written.append(row['path'])
    return {'contract_sha256': sha(CONTRACT), 'receipt_sha256': sha(provider / 'receipt.json'),
            'files_verified': len(planned), 'written': written,
            'limits': 'Private input/source delivery only; compiled interfaces, package and boot require verification.'}


def check_package(package, contract):
    issues = []
    with zipfile.ZipFile(package) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError('duplicate target-files member')
        for row in rows(contract):
            name = row['member']
            if name not in names:
                issues.append(name + ': missing'); continue
            info = archive.getinfo(name)
            if stat.S_ISLNK(info.external_attr >> 16):
                issues.append(name + ': unexpected symlink'); continue
            with archive.open(info) as stream:
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()
            if info.file_size != row['bytes'] or digest != row['sha256']:
                issues.append(name + ': differs from reviewed runtime')
        # These HIDL libraries are generated by the pinned Android17 source.
        # Their old23b binaries are not part of the private input provider.
        for name in contract['compiled_interfaces']:
            if name not in names:
                issues.append(name + ': vendor interface variant missing'); continue
            data = archive.read(name)
            if data[:6] != b'\x7fELF\x02\x01' or int.from_bytes(data[18:20], 'little') != 183:
                issues.append(name + ': expected ARM64 vendor interface')
    return {'common_runtime_pass': not issues, 'issues': issues,
            'private_files': len(contract['files']),
            'compiled_interfaces': len(contract['compiled_interfaces']),
            'limits': 'Exact runtime/configuration bytes and source-built interface delivery; no general ABI or runtime acceptance.'}
