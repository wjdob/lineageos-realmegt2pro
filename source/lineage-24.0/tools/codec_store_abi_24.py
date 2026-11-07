"""Bind Qualcomm allocations to the independently measured Android17 provider ABI."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import zipfile

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / 'configs/codec-store-abi-24.0.json'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def executable_offset(data, va, size):
    """Translate a complete instruction range through one file-backed RX PT_LOAD."""
    if (len(data) < 64 or data[:7] != b'\x7fELF\x02\x01\x01' or
            struct.unpack_from('<H', data, 18)[0] != 183):
        raise ValueError('ELF64 little-endian AArch64 required')
    start = struct.unpack_from('<Q', data, 32)[0]
    stride, count = struct.unpack_from('<HH', data, 54)
    if stride != 56 or not count or start + stride * count > len(data):
        raise ValueError('invalid ELF program headers')
    if va < 0 or size <= 0 or va % 4:
        raise ValueError('invalid instruction range')
    matches = []
    for index in range(count):
        kind, flags, offset, address, _, filesz, memsz, _ = struct.unpack_from(
            '<IIQQQQQQ', data, start + stride * index)
        if kind != 1:
            continue
        if filesz > memsz or offset + filesz > len(data):
            raise ValueError('invalid ELF load extent')
        if address <= va and va + size <= address + filesz:
            if flags & 5 != 5 or flags & 2:
                raise ValueError('instruction mapping must be read/execute only')
            matches.append(offset + va - address)
    if len(matches) != 1:
        raise ValueError('instruction range has no unique file-backed load mapping')
    return matches[0]


def instruction(data, va, expected):
    expected = bytes.fromhex(expected)
    pos = executable_offset(data, va, len(expected))
    if data[pos:pos + len(expected)] != expected:
        raise ValueError('reviewed instruction mismatch')
    return pos


def movz_w(word, register):
    if word & 0xffe0001f != 0x52800000 | register:
        raise ValueError('unshifted MOVZ W immediate required')
    return (word >> 5) & 0xffff


def check_provider(data, contract):
    row = contract['provider']
    if digest(data) != row['sha256']:
        raise ValueError('ComponentStore provider changed; renewed ABI review required')
    pos = instruction(data, row['constructor_virtual_base_va'], row['constructor_virtual_base_hex'])
    word = struct.unpack_from('<I', data, pos)[0]
    if word & 0xffc003ff != 0x91000000:
        raise ValueError('reviewed constructor ADD X0, X0 immediate required')
    base_offset = (word >> 10) & 0xfff
    if base_offset != row['virtual_base_offset'] or base_offset >= contract['required_size']:
        raise ValueError('virtual RefBase offset exceeds reviewed class size')
    pos = instruction(data, row['deleting_size_va'], row['deleting_size_hex'])
    size = movz_w(struct.unpack_from('<I', data, pos)[0], 1)
    instruction(data, row['sized_delete_branch_va'], row['sized_delete_branch_hex'])
    if size != contract['required_size'] or size <= contract['legacy_size']:
        raise ValueError('ComponentStore sizeof differs from reviewed allocation correction')
    return {'sha256': digest(data), 'required_size': size, 'virtual_base_offset': base_offset}


def check_launcher(data, row, contract):
    if digest(data) != row['candidate_sha256']:
        raise ValueError('unreviewed or undersized Codec2 launcher: ' + row['name'])
    old, new = bytes.fromhex(row['old_hex']), bytes.fromhex(row['new_hex'])
    if len(old) != len(new) or sum(a != b for a, b in zip(old, new)) != 1:
        raise ValueError('allocation correction must change exactly one byte')
    pos = instruction(data, row['allocation_va'], row['new_hex'])
    if data.count(new) != 1 or old in data:
        raise ValueError('allocation correction is absent or ambiguous')
    restored = data[:pos] + old + data[pos + len(new):]
    if digest(restored) != row['base_sha256']:
        raise ValueError('bytes outside allocation correction changed')
    size = movz_w(struct.unpack_from('<I', data, pos)[0], 0)
    if size != contract['required_size'] or movz_w(struct.unpack_from('<I', old)[0], 0) != contract['legacy_size']:
        raise ValueError('launcher allocation size differs from reviewed class ABI')
    return {'name': row['name'], 'sha256': digest(data), 'allocation_size': size,
            'allocation_va': row['allocation_va'], 'file_offset': pos, 'changed_bytes': 1}


def load_contract():
    return json.loads(CONTRACT.read_text())


def bind_inputs(path, contract):
    inputs = json.loads(Path(path).read_text())
    recipe = inputs.get('recipe_snapshot', {})
    if (inputs.get('target') != 'otapackage' or
            recipe.get('manifest_sha256') != inputs.get('manifest_sha256') or
            inputs.get('manifest_sha256') != contract['probe']['manifest_sha256']):
        raise ValueError('Codec2 contract requires the measured Android17 source manifest')
    for file in (CONTRACT.resolve(), Path(__file__).resolve()):
        relative = str(file.relative_to(ROOT))
        if inputs.get('source_hashes', {}).get(relative) != digest(file.read_bytes()):
            raise ValueError('Codec2 checker/contract differs from same-run inputs: ' + relative)
    expected = [(contract['extraction']['path'], contract['extraction']['sha256'])]
    expected += [(row['source_path'], row['candidate_sha256']) for row in contract['launchers']]
    for source, canonical in expected:
        rows = [row for row in recipe.get('files', []) if row['path'] == source]
        if len(rows) != 1 or rows[0]['canonical_sha256'] != canonical:
            raise ValueError('Codec2 delivery differs from same-run recipe: ' + source)
    return {'candidate_inputs_sha256': digest(Path(path).read_bytes()),
            'contract_sha256': digest(CONTRACT.read_bytes()),
            'tool_sha256': digest(Path(__file__).read_bytes()),
            'manifest_sha256': inputs['manifest_sha256']}


def check_source(tree):
    contract = load_contract()
    extraction = contract['extraction']
    if digest((Path(tree) / extraction['path']).read_bytes()) != extraction['sha256']:
        raise ValueError('extraction recipe differs from reviewed Codec2 correction')
    return {'launchers': [check_launcher((Path(tree) / row['source_path']).read_bytes(), row, contract)
                          for row in contract['launchers']],
            'limits': 'Exact extraction/prebuilt delivery only. The compiled provider ABI is checked separately in collected target-files; device startup acceptance remains pending.'}


def check_package(target_files):
    contract = load_contract()
    with zipfile.ZipFile(target_files) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError('duplicate target-files member')
        provider = check_provider(archive.read(contract['provider']['target_member']), contract)
        launchers = [check_launcher(archive.read(row['target_member']), row, contract)
                     for row in contract['launchers']]
    return {'provider': provider, 'launchers': launchers, 'limits': contract['limits']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--source-tree', type=Path)
    group.add_argument('--target-files', type=Path)
    parser.add_argument('--candidate-inputs', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    binding = bind_inputs(args.candidate_inputs, load_contract())
    result = check_source(args.source_tree) if args.source_tree else check_package(args.target_files)
    result.update(binding)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
