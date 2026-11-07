"""Run a task in a private overlay at the original build path (Linux/root only).

The caller MUST launch with unshare --mount --propagation private. Original build
files become the overlay's lower layer; all changes go to a new per-run upper layer.
No deletion of existing run directories or original outputs is implemented here.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


def cache_layers(base,allowed,records,allow_failed=False):
    layers=[];seen=set()
    while base:
        base=Path(base).resolve()
        if base.parent!=allowed or base in seen or not (base/'upper').is_dir():
            raise ValueError('invalid or cyclic cache run')
        seen.add(base)
        record=json.loads((records/base.name/'result.json').read_text())
        accepted=('success','failed') if allow_failed else ('success',)
        if record.get('state') not in accepted or not record.get('finished_ns'):
            raise ValueError('cache run must have an accepted terminal completion record')
        marker=json.loads((base/'upper/.realme-next-isolated.json').read_text())
        if Path(marker['run']).resolve()!=base:
            raise ValueError('cache marker does not identify its run')
        layers.append(base/'upper')
        base=marker.get('base_run')
    return layers


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--run-dir', type=Path, required=True)
    p.add_argument('--root', type=Path, default=Path('/build/lineage'),
                   help='overlay mount point; defaults to the 23.2 tree')
    p.add_argument('--lower', type=Path,
                   help='lower tree; defaults to --root for the 23.2 tree')
    p.add_argument('--work-root', type=Path, default=Path('/build/realmegt2pro-next-work'),
                   help='parent for run upper/work layers')
    p.add_argument('--records-root', type=Path,
                   help='completed run records used for --base-run validation')
    p.add_argument('--base-run', type=Path, help='completed immutable run whose upper layer supplies cached changes')
    p.add_argument('--allow-failed-cache',action='store_true',help='explicitly allow terminal failed runs as caches, never as successful results')
    p.add_argument('command', nargs=argparse.REMAINDER)
    a = p.parse_args()
    run = a.run_dir.resolve()
    allowed = a.work_root.resolve()
    if run.parent != allowed or run.exists():
        raise SystemExit('use a NEW direct child of the work root')
    if os.readlink('/proc/self/ns/mnt') == os.readlink('/proc/1/ns/mnt'):
        raise SystemExit('refusing to mount in the host mount namespace')
    if not a.command:
        raise SystemExit('missing command')
    command = a.command[1:] if a.command[0] == '--' else a.command
    if not command:
        raise SystemExit('missing command')
    root = a.root.resolve()
    if root.parent != Path('/build') or not root.is_dir():
        raise SystemExit('overlay mount point must be an existing direct child of /build')
    lower = a.lower.resolve() if a.lower else root
    if not lower.is_dir():
        raise SystemExit('lower tree must exist')
    if not allowed.is_dir():
        raise SystemExit('work root must exist')
    run.mkdir(parents=True)
    upper, work = run/'upper', run/'work'
    upper.mkdir(); work.mkdir()
    layers=[lower]
    if a.base_run:
        records = a.records_root.resolve() if a.records_root else Path(__file__).resolve().parents[2]/'.local/goals/runs'
        layers=cache_layers(a.base_run,allowed,records,a.allow_failed_cache)+layers
    subprocess.run(['mount', '-t', 'overlay', 'overlay', '-o',
                    f'lowerdir={":".join(map(str,layers))},upperdir={upper},workdir={work}', str(root)], check=True)
    marker = root/'.realme-next-isolated.json'
    marker.write_text(json.dumps({'run':str(run),'root':str(root),'lower':str(lower),'base_run':str(a.base_run.resolve()) if a.base_run else None,'allow_failed_cache':a.allow_failed_cache,'namespace':os.readlink('/proc/self/ns/mnt')}))
    os.chdir(root)
    # Avoid optional Git index writes; actual build writes stay in the overlay.
    os.environ['GIT_OPTIONAL_LOCKS'] = '0'
    return subprocess.call(command)


if __name__ == '__main__':
    sys.exit(main())
