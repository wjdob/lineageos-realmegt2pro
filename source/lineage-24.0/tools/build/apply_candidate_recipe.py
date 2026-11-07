"""Verify and optionally apply a versioned source recipe in an isolated tree.

The recipe is reconstructed in workspace scratch first. No tree file is changed
until every recorded preimage and every reconstructed canonical hash matches.
Apply mode additionally requires the private overlay marker used by the build
runner; it never edits the preserved lower tree.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / 'tools/build'))
from apply_recipe import isolated, safe_file
from reconstruct_candidate import reconstruct


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def apply(tree, recipe_path, scratch, write=False, *, scratch_root=None):
    tree, scratch = Path(tree).resolve(), Path(scratch).absolute()
    recipe = json.loads(Path(recipe_path).read_text())
    if recipe.get('schema') != 2:
        raise ValueError('unsupported recipe schema')
    if not write and scratch.exists():
        raise ValueError('scratch output must not already exist')
    result = reconstruct(tree, scratch, recipe_path, scratch_root=scratch_root)
    # Reconstruct rejects any preimage that is not the recorded base. Accept a
    # previously applied canonical or recorded predecessor explicitly.
    for row in recipe['files']:
        target = safe_file(tree, row['path'])
        state = sha(target)
        if state not in {row['base_sha256'], row['canonical_sha256'], *row.get('previous_sha256', [])}:
            raise ValueError('unexpected preimage: ' + row['path'])
    for row in recipe.get('new_files', []):
        target = safe_file(tree, row['path'])
        if target.exists() and sha(target) not in {
                row['canonical_sha256'], *row.get('previous_sha256', [])}:
            raise ValueError('unexpected added-file preimage: ' + row['path'])
    written = []
    if write:
        isolated(tree)
        for row in [*recipe['files'], *recipe.get('new_files', [])]:
            target = safe_file(tree, row['path'])
            if target.exists() and sha(target) == row['canonical_sha256']:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(scratch / row['path'], target)
            if sha(target) != row['canonical_sha256']:
                raise ValueError('written hash differs: ' + row['path'])
            written.append(row['path'])
    return {'reconstruction': result, 'recipe': str(recipe_path),
            'manifest_sha256': recipe['manifest_sha256'],
            'files': len(recipe['files']), 'new_files': len(recipe.get('new_files', [])),
            'written': written, 'applied': bool(write),
            'limit': 'File hashes only; checkout HEADs, Soong graph, package and device are untested.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tree', type=Path, required=True)
    parser.add_argument('--recipe', type=Path, required=True)
    parser.add_argument('--scratch', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    result = apply(args.tree, args.recipe, args.scratch, args.apply)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
