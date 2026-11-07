"""Verify and materialize the private .1410 Ferrari vendor supplement in an overlay."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil

from apply_recipe import isolated, safe_file
from storage_24 import STORE, BUILD_TREE, verify_store

REPO = Path(__file__).resolve().parents[2]
CONTRACT = REPO / 'configs/lineage-24.0-vendor-output.json'


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def relative(name):
    parts = PurePosixPath(name)
    if (not name or parts.is_absolute() or '\\' in name or ':' in name or
            any(p in ('', '.', '..') for p in name.split('/'))):
        raise ValueError('unsafe vendor input path: ' + name)
    return parts


def verify_provider(store=STORE):
    verify_store(store)
    contract = json.loads(CONTRACT.read_text())
    if contract.get('schema') != 1:
        raise ValueError('unsupported vendor output schema')
    name = relative(contract['provider'])
    if name.parts[0] != 'inputs':
        raise ValueError('vendor provider must be in the dedicated 24.0 inputs directory')
    provider = store / str(name)
    if provider.is_symlink() or not provider.resolve().is_relative_to(store / 'inputs'):
        raise ValueError('redirected vendor provider')
    if sha(REPO / 'configs/lineage-24.0-vendor-inputs.json') != contract['source_contract_sha256']:
        raise ValueError('vendor source contract changed')
    if sha(provider / 'receipt.json') != contract['receipt_sha256']:
        raise ValueError('vendor extraction receipt changed')
    receipt = json.loads((provider / 'receipt.json').read_text())
    if (receipt['source_contract_sha256'] != contract['source_contract_sha256'] or
            receipt['implementation_sha256'] != sha(REPO / 'tools/build/prepare_vendor_24.py') or
            receipt['files'] != [{k: row[k] for k in ('path', 'bytes', 'sha256')} for row in contract['files']]):
        raise ValueError('vendor output is not bound to the reviewed extraction')
    seen = set()
    for row in contract['files']:
        path = relative(row['path'])
        if row['path'] in seen:
            raise ValueError('duplicate vendor destination')
        seen.add(row['path'])
        if not (str(path) in ('Android.bp', 'Android.mk', 'BoardConfigVendor.mk', 'ferrari-vendor.mk')
                or path.parts[0] == 'proprietary'):
            raise ValueError('unreviewed vendor destination')
        file = safe_file(provider, str(path))
        if not file.is_file() or file.stat().st_size != row['bytes'] or sha(file) != row['sha256']:
            raise ValueError('vendor provider changed: ' + row['path'])
    return contract, provider


def materialize(tree, store=STORE):
    isolated(tree)
    if tree != BUILD_TREE:
        raise ValueError('24.0 private overlay required')
    contract, provider = verify_provider(store)
    vendor = tree / 'vendor/realme/ferrari'
    recipe = json.loads((REPO / 'tools/build/recipe-24.0.json').read_text())
    allowed = {row['path']: row['canonical_sha256'] for row in recipe['files']}
    # Verify every destination before replacing the first file. The old public
    # revision stays intact in the lower tree; only this private overlay changes.
    planned = []
    for row in contract['files']:
        dst = safe_file(vendor, row['path'])
        previous = sha(dst) if dst.is_file() else None
        expected = {row['base_sha256'], row['sha256'],
                    allowed.get('vendor/realme/ferrari/' + row['path'])}
        if previous not in expected or dst.exists() and not dst.is_file():
            raise ValueError('unexpected vendor preimage: ' + row['path'])
        planned.append((row, dst, previous))
    written = []
    for row, dst, previous in planned:
        if previous == row['sha256']:
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(provider / row['path'], dst)
        if sha(dst) != row['sha256']:
            raise ValueError('vendor write verification failed: ' + row['path'])
        written.append(row['path'])
    return {'contract_sha256': sha(CONTRACT), 'receipt_sha256': contract['receipt_sha256'],
            'files_verified': len(planned), 'written': written,
            'limits': 'Private offline vendor materialization only; no graph, build or hardware claim.'}
