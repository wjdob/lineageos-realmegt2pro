"""Lease one native 24.0 output cache inside an already isolated source view.

Each run reconstructs source from the pinned lower. Only compiled output is
shared, under a nonblocking lock. Installed product files are cleaned by the
driver before rebuilding; successful release artifacts have separate run copies.
"""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

from apply_recipe import safe_file

from apply_recipe import isolated
from storage_24 import BUILD_TREE, STORE, verify_store, mounted


def vendor_freshness(tree, output, contract):
    """Refresh changed prebuilt timestamps inside the private source overlay.

    A fresh overlay can expose an older lower-file mtime after a previous run
    overrode its contents. Ninja otherwise reuses an intermediate for the old
    bytes. Only a successful OTA may advance the cache's content receipt.
    """
    isolated(tree)
    output = Path(output)
    tag = output.parent / 'vendor-inputs-success.json'
    previous = {}
    if tag.is_symlink():
        raise ValueError('redirected vendor cache receipt')
    if tag.exists():
        receipt = json.loads(tag.read_text())
        if receipt.get('schema') != 1 or receipt.get('output') != str(output):
            raise ValueError('vendor cache receipt identity differs')
        record_path = Path(receipt['record'])
        if record_path.is_symlink() or not record_path.is_file():
            raise ValueError('vendor cache completion record absent')
        raw = record_path.read_bytes()
        result = json.loads(raw)
        if (hashlib.sha256(raw).hexdigest() != receipt['record_sha256'] or
                result.get('state') != 'success' or result.get('exit_code') != 0
                or not result.get('finished_ns')):
            raise ValueError('vendor cache completion record differs')
        previous = receipt['inputs']
        if not isinstance(previous, dict):
            raise ValueError('invalid vendor cache input map')
        inputs_path = Path(result['command'][-1])
        raw_inputs = inputs_path.read_bytes()
        if (hashlib.sha256(raw_inputs).hexdigest() != receipt['candidate_inputs_sha256']
                or json.loads(raw_inputs)['output_cache']['vendor_freshness']['inputs'] != previous):
            raise ValueError('vendor cache input record differs')
    current = {}
    planned = []
    for row in contract['files']:
        name = 'vendor/realme/ferrari/' + row['path']
        path = safe_file(tree, name)
        digest = row['sha256']
        if (name in current or not path.is_file()
                or hashlib.sha256(path.read_bytes()).hexdigest() != digest):
            raise ValueError('vendor freshness input differs: ' + name)
        current[name] = digest
        if previous.get(name) != digest:
            planned.append(path)
    # Verify the whole input set before touching the first source timestamp.
    stamp = time.time_ns()
    for path in planned:
        os.utime(path, ns=(path.stat().st_atime_ns, stamp))
    return {'schema': 1, 'output': str(output), 'inputs': current,
            'refreshed': [str(p.relative_to(tree)) for p in planned],
            'timestamp_ns': stamp, 'previous_success_available': tag.exists(),
            'limits': 'Private source timestamps only; no output or build acceptance.'}


def record_vendor_success(freshness, record_path):
    record_path = Path(record_path)
    raw = record_path.read_bytes()
    result = json.loads(raw)
    if (result.get('state') != 'success' or result.get('exit_code') != 0
            or not result.get('finished_ns')):
        raise ValueError('successful OTA completion required for vendor cache receipt')
    if result['command'][2] != 'otapackage':
        raise ValueError('successful OTA target required for vendor cache receipt')
    raw_inputs = Path(result['command'][-1]).read_bytes()
    if json.loads(raw_inputs)['output_cache']['vendor_freshness'] != freshness:
        raise ValueError('completed vendor input record differs')
    row = {'schema': 1, 'output': freshness['output'], 'inputs': freshness['inputs'],
           'record': str(record_path), 'record_sha256': hashlib.sha256(raw).hexdigest(),
           'candidate_inputs_sha256': hashlib.sha256(raw_inputs).hexdigest()}
    tag = Path(freshness['output']).parent / 'vendor-inputs-success.json'
    if tag.is_symlink():
        raise ValueError('redirected vendor cache receipt')
    partial = tag.with_suffix('.partial')
    with partial.open('x') as stream:
        stream.write(json.dumps(row, sort_keys=True, indent=2) + '\n')
    partial.replace(tag)


def directory(path, store):
    if path.is_symlink() or not path.resolve().is_relative_to(store.resolve()):
        raise ValueError('redirected output cache directory')
    path.mkdir(exist_ok=True)
    if not path.is_dir() or path.stat().st_dev != store.stat().st_dev:
        raise ValueError('output cache must stay on the SSD store filesystem')


def cache_identity(manifest_sha256, certificate_sha256):
    for digest in (manifest_sha256, certificate_sha256):
        if len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
            raise ValueError('full lower-case SHA-256 required for cache identity')
    return {'schema':1, 'manifest_sha256':manifest_sha256,
            'certificate_sha256':certificate_sha256,
            'product':'lineage_ferrari', 'release':'cp2a', 'variant':'userdebug',
            'policy':'fresh-source-installclean-v1'}


@contextmanager
def output_cache(tree, store, manifest_sha256, certificate_sha256):
    if tree != BUILD_TREE or store != STORE:
        raise ValueError('only the dedicated 24.0 source view and store are allowed')
    verify_store(store)
    isolated(tree)
    identity=cache_identity(manifest_sha256,certificate_sha256)
    encoded=(json.dumps(identity,sort_keys=True,indent=2)+'\n').encode()
    name='ferrari-cp2a-'+hashlib.sha256(encoded).hexdigest()[:20]
    parent=store/'build-cache';directory(parent,store)
    cache=parent/name;directory(cache,store)
    descriptor=os.open(cache/'lease.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    with os.fdopen(descriptor,'r+b') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as exc:raise ValueError('another run owns this output cache') from exc
        tag=cache/'identity.json'
        if tag.is_symlink():raise ValueError('redirected output cache identity')
        existed=tag.exists()
        if existed:
            if tag.read_bytes()!=encoded:raise ValueError('output cache identity changed')
        else:
            if set(p.name for p in cache.iterdir())!={'lease.lock'}:
                raise ValueError('unidentified existing output cache; retain its contents')
            with tag.open('xb') as stream:stream.write(encoded)
        data=cache/'out';directory(data,store)
        point=tree/'out'
        if point.is_symlink() or point.exists() and (not point.is_dir() or any(point.iterdir())):
            raise ValueError('output bind point must be empty in the fresh source view')
        point.mkdir(exist_ok=True)
        subprocess.run(['mount','--bind',str(data),str(point)],check=True)
        try:
            mount=mounted(point)
            if (mount['fstype']!='ext4' or 'rw' not in mount['options'].split(',')
                    or not point.samefile(data)):
                raise ValueError('native output bind differs from the leased cache')
            yield {'path':str(data),'identity':identity,
                   'identity_sha256':hashlib.sha256(encoded).hexdigest(),
                   'previously_identified':existed,
                   'policy':'Only output is reused. Fresh pinned source/recipe/vendor/signing checks precede binding. Driver installclean removes installed products; object/cache reuse is not successful-build evidence.'}
        finally:
            subprocess.run(['umount',str(point)],check=True)
