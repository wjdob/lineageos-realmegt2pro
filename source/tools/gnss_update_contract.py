"""Bind the staged GNSS installer to reviewed source and packaged prerequisites.

This checks files only. It neither opens devices nor certifies actual migration,
recovery boot, restoration or OTA retention.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import zipfile

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / 'configs/gnss-nvbk-23.2.json'
MAX_MEMBER = 16 * 1024**2


def check_source(tree, contract=None):
    spec = contract or json.loads(CONTRACT.read_text())
    rows = {}
    for name, expected in spec['source_files'].items():
        path = Path(tree) / name
        if not path.is_file() or path.is_symlink():
            raise ValueError('missing regular GNSS source: ' + name)
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError('GNSS source differs: ' + name)
        rows[name] = actual
    return {'gnss_source_prerequisites_pass': True, 'source_files': rows,
            'limits': 'Exact source only; no native or runtime acceptance.'}


def check_package(target_files, contract=None):
    spec = contract or json.loads(CONTRACT.read_text())
    rows = {}
    with zipfile.ZipFile(target_files) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError('duplicate target-files member')
        def read(name):
            if name not in names or archive.getinfo(name).file_size > MAX_MEMBER:
                raise ValueError('missing or oversized GNSS prerequisite: ' + name)
            data = archive.read(name)
            rows[name] = hashlib.sha256(data).hexdigest()
            return data
        for name in spec['engine_members']:
            data = read(name)
            if (len(data) < 64 or data[:6] != b'\x7fELF\x02\x01'
                    or struct.unpack_from('<H', data, 18)[0] != 183):
                raise ValueError('AArch64 GNSS engine required: ' + name)
            if any(marker.encode() not in data for marker in spec['engine_markers']):
                raise ValueError('compiled GNSS migration marker missing: ' + name)
        for name, expected in spec['unchanged_policy_members'].items():
            read(name)
            if rows[name] != expected:
                raise ValueError('base policy changed; selected-add-on compatibility unresolved: ' + name)
    return {'gnss_package_prerequisites_pass': True, 'members': rows,
            'limits': 'Compiled markers and unchanged base policy are prerequisites; '
                      'not migration, activation/refusal, ioctl/DAC access, restore or OTA proof.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--source-tree', type=Path)
    group.add_argument('--target-files', type=Path)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    result = check_source(args.source_tree) if args.source_tree else check_package(args.target_files)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))
