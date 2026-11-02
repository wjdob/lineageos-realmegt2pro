"""Verify candidate modifications in new workspace scratch; never edit the input tree."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess

from manifest import read_pins

REPO = Path(__file__).resolve().parents[2]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def contained(root, relative):
    path = root / relative
    if Path(relative).is_absolute() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('path escapes root: ' + str(relative))
    if any(p.is_symlink() for p in [path, *path.parents] if p != root):
        raise ValueError('symlink in path: ' + str(relative))
    return path


def new_file_rows(recipe, pins):
    """Validate explicitly added source files independently of an existing checkout."""
    seen = {row['path'] for row in recipe['files']}
    rows = recipe.get('new_files', [])
    for row in rows:
        for key in ('project', 'relative', 'source'):
            name = row[key]
            if (not name or '\\' in name or ':' in name or
                    PurePosixPath(name).is_absolute() or
                    any(part in ('', '.', '..') for part in name.split('/'))):
                raise ValueError('invalid added-file path: ' + name)
        if row['path'] != row['project'] + '/' + row['relative'] or row['path'] in seen:
            raise ValueError('duplicate or inconsistent added-file path')
        seen.add(row['path'])
        if pins.get(row['project']) != row['revision']:
            raise ValueError('added-file revision differs from manifest')
        source = contained(REPO, row['source'])
        if sha(source.read_bytes()) != row['canonical_sha256']:
            raise ValueError('added-file template hash mismatch: ' + row['source'])
    return rows


def reconstruct(tree, output, recipe_path=None):
    tree, output = Path(tree).resolve(), Path(output).absolute()
    if output.exists() or output.is_symlink():
        raise ValueError('output must not exist')
    if not output.resolve().is_relative_to((REPO / 'tmp').resolve()):
        raise ValueError('output must be under workspace tmp')
    if output.resolve().is_relative_to(tree):
        raise ValueError('output must not be inside input tree')
    recipe = json.loads((recipe_path or REPO / 'tools/build/recipe-23.2.json').read_text())
    if recipe['schema'] != 2:
        raise ValueError('unsupported recipe schema')
    manifest = contained(REPO, recipe['manifest'])
    if sha(manifest.read_bytes()) != recipe['manifest_sha256']:
        raise ValueError('manifest hash mismatch')
    pins = {path: revision for (_, path), revision in read_pins(manifest).items()}
    additions = new_file_rows(recipe, pins)
    for row in additions:
        if contained(tree, row['path']).exists():
            raise ValueError('added-file input must be absent: ' + row['path'])
        contained(output, row['path'])
    inputs, patches = {}, {}
    for row in recipe['files']:
        if row['path'] in inputs or row['path'] != row['project'] + '/' + row['relative']:
            raise ValueError('duplicate or inconsistent recipe path')
        if pins.get(row['project']) != row['revision']:
            raise ValueError('recipe revision differs from manifest')
        data = contained(tree, row['path']).read_bytes()
        if sha(data) != row['base_sha256']:
            raise ValueError('unexpected preimage: ' + row['path'])
        contained(output, row['path'])
        inputs[row['path']] = data
    for action in recipe['actions']:
        if action['type'] == 'patch':
            contained(output, action['project'])
            data = contained(REPO, action['file']).read_bytes()
            if sha(data) != action['sha256']:
                raise ValueError('patch hash mismatch')
            for line in data.decode('utf-8').splitlines():
                if line.startswith(('--- ', '+++ ')):
                    name = line[4:].split('\t', 1)[0]
                    if not name.startswith(('a/', 'b/')):
                        raise ValueError('unsupported patch header')
                    relative = action['project'] + '/' + name[2:]
                    contained(output, relative)
                    if relative not in inputs:
                        raise ValueError('patch target outside recipe files')
            patches[action['file']] = data
        elif action['type'] == 'replace_bytes':
            if action['path'] not in inputs:
                raise ValueError('binary action outside recipe files')
        else:
            raise ValueError('unknown recipe action')
    # Inputs are fully checked before creating output. Partial failed output is kept
    # for diagnosis and cannot be silently reused by another invocation.
    output.mkdir(parents=True)
    for relative, data in inputs.items():
        target = contained(output, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    for action in recipe['actions']:
        if action['type'] == 'patch':
            subprocess.run(['patch', '--batch', '--fuzz=0', '-p1'],
                           input=patches[action['file']],
                           cwd=contained(output, action['project']), check=True)
        else:
            target = contained(output, action['path'])
            old, new = bytes.fromhex(action['old_hex']), bytes.fromhex(action['new_hex'])
            data = target.read_bytes()
            if not old or len(old) != len(new) or data.count(old) != action['expected_count']:
                raise ValueError('unexpected binary replacement input')
            target.write_bytes(data.replace(old, new))
    for row in recipe['files']:
        if sha(contained(output, row['path']).read_bytes()) != row['canonical_sha256']:
            raise ValueError('reconstruction mismatch: ' + row['path'])
    for row in additions:
        data = contained(REPO, row['source']).read_bytes()
        if sha(data) != row['canonical_sha256']:
            raise ValueError('added-file template changed during reconstruction')
        target = contained(output, row['path'])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    inputs.update({row['path']: None for row in additions})
    return {'reconstruction': 'verified', 'files': len(inputs),
            'limits': 'File hashes only; checkout HEADs, build graph, ABI and hardware untested.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tree', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(reconstruct(args.tree, args.output), indent=2))
