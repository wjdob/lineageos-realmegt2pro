"""Retire only diagnostic init outputs after collection, preserving release caches.

Fresh source views can restore older mtimes. Removing the affected module keeps
its diagnostic mount-order object from being reused by a later normal OTA.
The caller of retire() must own the output-cache lease. The CLI acquires it.
"""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import shutil

from apply_recipe import safe_file
from storage_24 import STORE, verify_store

PATHS = {
    'soong/.intermediates/system/core/init/init_first_stage': 'directory',
    'soong/.intermediates/system/core/init/init_second_stage': 'directory',
    'soong/.intermediates/system/core/init/libinit': 'directory',
    'target/product/ferrari/ramdisk/init': 'file',
    'target/product/ferrari/system/bin/init': 'file',
    'target/product/ferrari/symbols/ramdisk/init': 'file',
    'target/product/ferrari/symbols/system/bin/init': 'file',
    'target/product/ferrari/obj/EXECUTABLES/init_first_stage_intermediates': 'directory',
    'target/product/ferrari/obj/EXECUTABLES/init_second_stage_intermediates': 'directory',
    'target/product/ferrari/obj/STATIC_LIBRARIES/libinit_intermediates': 'directory',
    'target/product/ferrari/obj/PACKAGING/elf_symbol_mapping_intermediates/ramdisk/init.textproto': 'file',
    'target/product/ferrari/obj/PACKAGING/elf_symbol_mapping_intermediates/system/bin/init.textproto': 'file',
}


def retire_paths(output):
    """Validate the whole fixed set before removing any owned compiled output."""
    selected = []
    for relative, kind in PATHS.items():
        path = safe_file(output, relative)
        if path.exists():
            if kind == 'directory' and not path.is_dir() or kind == 'file' and not path.is_file():
                raise ValueError('unexpected init cache output type: ' + relative)
            selected.append((relative, path, kind))
    for _, path, kind in selected:
        if kind == 'directory':
            shutil.rmtree(path)
        else:
            path.unlink()
    return [relative for relative, _, _ in selected]


def validate_cache(output):
    verify_store()
    output = Path(output)
    if output.name != 'out' or output.parent.parent != STORE / 'build-cache':
        raise ValueError('only a named native24 compiled output cache is allowed')
    if not re.fullmatch(r'ferrari-cp2a-[0-9a-f]{20}', output.parent.name):
        raise ValueError('unexpected native24 output cohort')
    safe_file(STORE, str(output.relative_to(STORE)))
    if not output.is_dir() or output.stat().st_dev != STORE.stat().st_dev:
        raise ValueError('output cache must remain on the verified native store')
    identity = json.loads(safe_file(output.parent, 'identity.json').read_text())
    if identity.get('product') != 'lineage_ferrari' or identity.get('release') != 'cp2a':
        raise ValueError('output cache identity differs')
    return output


def retire(output, report):
    if Path(report).exists():
        raise ValueError('use a new diagnostic cache retirement receipt')
    output = validate_cache(output)
    removed = retire_paths(output)
    receipt = {'cache': str(output), 'removed': removed,
               'scope': 'Only init_first_stage, init_second_stage and libinit diagnostic modules and their installed/symbol copies retired after collection. Collected artifacts, source, keys, other compiled modules and backups preserved.'}
    with Path(report).open('x') as stream:
        json.dump(receipt, stream, indent=2)
    return receipt


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--report', type=Path, required=True)
    args = p.parse_args()
    output = validate_cache(args.output)
    lease = safe_file(output.parent, 'lease.lock')
    fd = os.open(lease, os.O_RDWR | os.O_NOFOLLOW)
    with os.fdopen(fd, 'r+b') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        print(json.dumps(retire(output, args.report)))


if __name__ == '__main__':
    main()
