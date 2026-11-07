"""Check candidate checkout identity, local changes and materialized LFS contents."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import subprocess

from manifest import read_pins
from reconstruct_candidate import contained, new_file_rows

REPO = Path(__file__).resolve().parents[2]
EXCLUDED = {'prebuilts/clang/host/darwin-x86', 'prebuilts/go/darwin-x86',
            'prebuilts/rust-toolchain/darwin'}


def sha_file(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def git(tree, *args):
    return subprocess.check_output(['git', '-C', str(tree), *args],
                                   env={**os.environ, 'GIT_OPTIONAL_LOCKS': '0'})


def check_project(tree, path, revision, allowed, additions=None):
    project = contained(tree, path)
    if git(project, 'rev-parse', 'HEAD').decode().strip() != revision:
        raise ValueError('HEAD mismatch: ' + path)
    changed = set(filter(None, git(project, 'diff', '--name-only', '-z', 'HEAD').decode().split('\0')))
    untracked = list(filter(None, git(project, 'ls-files', '--others', '--exclude-standard', '-z').decode().split('\0')))
    added = {row['relative']: row for row in (additions or []) if row['project'] == path}
    for name, row in added.items():
        contained(project, name)
        if git(project, 'ls-tree', '-z', revision, '--', name):
            raise ValueError('added file already tracked at pin: ' + row['path'])
        target = contained(project, name)
        if target.exists() and (not target.is_file() or
                sha_file(target) not in {row['canonical_sha256'], *row.get('previous_sha256', [])}):
            raise ValueError('unexpected added-file content: ' + row['path'])
    unexpected = sorted(set(untracked) - set(added))
    if unexpected:
        raise ValueError('untracked files: ' + path + ': ' + repr(untracked))
    for name in changed:
        full = path + '/' + name
        allowed_hashes = allowed.get(full)
        if allowed_hashes is None:
            raise ValueError('unexpected local change: ' + full)
        if isinstance(allowed_hashes, str):
            allowed_hashes = {allowed_hashes}
        if sha_file(contained(project, name)) not in allowed_hashes:
            raise ValueError('unexpected local change: ' + full)
    attributes = git(project, 'ls-files', '-z', '--', '.gitattributes', '**/.gitattributes').decode().split('\0')
    lfs = []
    if any('filter=lfs' in contained(project, name).read_text(errors='replace')
           for name in attributes if name):
        lfs = json.loads(git(project, 'lfs', 'ls-files', '--json'))['files'] or []
        for entry in lfs:
            file = contained(project, entry['name'])
            if entry['oid_type'] != 'sha256' or file.stat().st_size != entry['size'] or sha_file(file) != entry['oid']:
                raise ValueError('missing or corrupt LFS payload: ' + path + '/' + entry['name'])
    return {'path': path, 'revision': revision, 'modified': sorted(changed), 'lfs': lfs}


def check(tree, canonical=False, recipe_path=None):
    recipe = json.loads((recipe_path or REPO / 'tools/build/recipe-23.2.json').read_text())
    manifest = REPO / recipe['manifest']
    if sha_file(manifest) != recipe['manifest_sha256']:
        raise ValueError('candidate manifest hash mismatch')
    pins = read_pins(manifest)
    additions = new_file_rows(recipe, {path: rev for (_, path), rev in pins.items()}) if canonical else []
    allowed = {row['path']: {row['canonical_sha256'], *row.get('previous_sha256', [])}
               for row in recipe['files']} if canonical else {}
    if canonical:
        allowed.update({row['path']: row['result_sha256'] for row in recipe.get('binary_fixups', [])})
    selected = [(path, rev) for (_, path), rev in pins.items() if path not in EXCLUDED]
    project_list = tree / '.repo/project.list'
    if set(project_list.read_text().splitlines()) != {path for path, _ in selected}:
        raise ValueError('repo project list differs from selected candidate manifest')
    def inspect_project(item):
        try:
            return check_project(tree, *item, allowed, additions), None
        except (ValueError, OSError, subprocess.SubprocessError) as exc:
            return None, {'path': item[0], 'error': str(exc)}
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(inspect_project, selected))
    issues = [issue for _, issue in results if issue]
    if issues:
        raise ValueError('checkout verification failed: ' + json.dumps(issues, sort_keys=True))
    rows = [row for row, _ in results]
    return {'manifest_sha256': recipe['manifest_sha256'], 'projects': rows,
            'excluded_host_projects': sorted(EXCLUDED), 'lfs_content_verified': True,
            'limit': 'Source identity and working files only; no build or runtime claim.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--tree', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--canonical', action='store_true')
    parser.add_argument('--recipe', type=Path, help='recipe path; defaults to the 23.2 recipe')
    args = parser.parse_args()
    report = check(args.tree.resolve(), args.canonical, args.recipe)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + '\n')
    print('Verified', len(report['projects']), 'project HEADs, local changes and LFS payloads')
