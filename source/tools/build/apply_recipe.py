"""Reconstruct pinned modifications and apply only inside a private build overlay."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from manifest import read_pins

REPO = Path(__file__).resolve().parents[2]


def digest(data):
    return hashlib.sha256(data).hexdigest()


def known_state(row, data):
    value = digest(data)
    for state in ('canonical', 'base', 'legacy'):
        if value == row[state + '_sha256']:
            return state
    raise ValueError('unexpected preimage: ' + row['path'])


def safe_file(root, relative):
    path = root / relative
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('path escapes tree: ' + relative)
    for item in [path, *path.parents]:
        if item == root:
            break
        if item.is_symlink():
            raise ValueError('symlink in recipe destination: ' + relative)
    return path


def isolated(tree):
    marker = tree / '.realme-next-isolated.json'
    if not marker.is_file():
        raise ValueError('missing isolation marker')
    namespace = os.readlink('/proc/self/ns/mnt')
    if namespace == os.readlink('/proc/1/ns/mnt'):
        raise ValueError('host namespace is not an isolated build')
    if json.loads(marker.read_text())['namespace'] != namespace:
        raise ValueError('isolation marker belongs to another namespace')
    fs = subprocess.check_output(['findmnt', '-n', '-o', 'FSTYPE', '-T', str(tree)], text=True).strip()
    if fs != 'overlay':
        raise ValueError('recipe writes require an overlay filesystem')


def apply(tree, scratch_root, write=False, profile='recovery'):
    recipe = json.loads((REPO/'tools/build/recipe.json').read_text())
    if recipe.get('historical_only'):
        raise ValueError('The 23.0 multi-ROM trust recipe is retired; use the 23.2 candidate workflow. Historical reproduction requires its recorded Git revision.')
    if profile not in ('recovery','rom'): raise ValueError('unknown recipe profile')
    if profile=='rom' and (not recipe.get('rom_patches') or not recipe.get('rom_overrides')):
        raise ValueError('ROM profile requires explicit patches and output hashes')
    patches=recipe['patches'] + (recipe.get('rom_patches',[]) if profile=='rom' else [])
    pins=read_pins(REPO/'manifests/lineage-23.0-locked.xml')
    needed={row['project'] for row in recipe['files']}
    selected={path:revision for (name,path),revision in pins.items() if path in needed}
    if set(selected)!=needed: raise ValueError('recipe project missing from locked manifest')
    for path,revision in selected.items():
        actual = subprocess.check_output(['git', '-C', str(tree/path), 'rev-parse', 'HEAD'], text=True).strip()
        if actual != revision:
            raise ValueError('revision mismatch: ' + path)
    if write:
        isolated(tree)
    states = {}
    for row in recipe['files']:
        data=safe_file(tree,row['path']).read_bytes()
        if profile=='rom' and digest(data)==recipe.get('rom_overrides',{}).get(row['path']):
            states[row['path']]='rom-canonical'
        else:
            states[row['path']] = known_state(row,data)
    for row in recipe['retired'] + recipe['certificates']:
        path = safe_file(tree,row['path'])
        if path.exists() and digest(path.read_bytes()) != row['sha256']:
            raise ValueError('unexpected content: '+row['path'])
    for patch in patches:
        if digest((REPO/patch['file']).read_bytes()) != patch['sha256']:
            raise ValueError('patch input changed: '+patch['file'])
    for cert in recipe['certificates']:
        if digest((REPO/'certs'/Path(cert['path']).name).read_bytes()) != cert['sha256']:
            raise ValueError('certificate input changed: '+cert['path'])
    scratch_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=scratch_root) as temp:
        stage = Path(temp)
        for row in recipe['files']:
            data = subprocess.check_output(['git','-C',str(tree/row['project']),'show','HEAD:'+row['relative']])
            if digest(data) != row['base_sha256']:
                raise ValueError('upstream preimage changed: '+row['path'])
            target = stage/row['path']
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(data)
        for patch in patches:
            source = REPO/patch['file']
            if source.suffix == '.patch':
                subprocess.run(['patch','--batch','--fuzz=0','-p1'],cwd=stage/patch['project'],input=source.read_text().encode(),check=True)
            else:
                subprocess.run([sys.executable,str(source),str(stage/patch['project'])],check=True)
        for row in recipe['files']:
            expected=recipe.get('rom_overrides',{}).get(row['path'],row['canonical_sha256']) if profile=='rom' else row['canonical_sha256']
            if digest((stage/row['path']).read_bytes()) != expected:
                raise ValueError('reconstruction mismatch: '+row['path'])
        if write:
            for row in recipe['files']:
                if digest(safe_file(tree,row['path']).read_bytes()) != digest((stage/row['path']).read_bytes()):
                    target = safe_file(tree,row['path'])
                    temp_path = target.with_name(target.name+'.next-tmp')
                    if temp_path.exists():
                        raise ValueError('temporary destination already exists')
                    shutil.copyfile(stage/row['path'],temp_path)
                    shutil.copymode(target,temp_path)
                    os.replace(temp_path,target)
            for cert in recipe['certificates']:
                target = safe_file(tree,cert['path'])
                if not target.exists():
                    target.parent.mkdir(parents=True,exist_ok=True)
                    shutil.copyfile(REPO/'certs'/target.name,target)
            for retired in recipe['retired']:
                target = safe_file(tree,retired['path'])
                if target.exists(): target.unlink()
    return {'profile':profile,'preimage_states':states,'canonical_reconstruction':'verified','applied':write}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--tree',type=Path,required=True)
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--profile',choices=['recovery','rom'],default='recovery')
    parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args()
    result=apply(args.tree, REPO/'tmp/goals/recipe',args.apply,args.profile)
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__ == '__main__':
    main()
