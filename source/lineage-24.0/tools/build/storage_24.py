"""Verify the dedicated 24.0 bind mount belongs to the SSD-backed WSL root."""
import base64
import json
import os
from pathlib import Path
import subprocess

HOST = Path('/mnt/c')
STORE = Path('/mnt/lineage24-store')
BACKING = Path('/build/lineage24-store')
BUILD_TREE = Path('/build/lineage-24.0')


def prepare_mountpoint():
    if BUILD_TREE.is_symlink() or BUILD_TREE.resolve() != BUILD_TREE:
        raise ValueError('24.0 overlay mountpoint is redirected')
    if BUILD_TREE.exists() and (not BUILD_TREE.is_dir() or any(BUILD_TREE.iterdir())):
        raise ValueError('24.0 overlay mountpoint must be empty outside its private namespace')
    BUILD_TREE.mkdir(parents=True, exist_ok=True)


def fresh_lower(tree, store, run_name):
    """Bind an empty fresh overlay to its unchanged, separately checked lower."""
    marker=json.loads((tree/'.realme-next-isolated.json').read_text())
    run=store/'work'/run_name
    lower=store/'tree'
    if (marker.get('root')!=str(tree) or marker.get('lower')!=str(lower) or
            marker.get('run')!=str(run) or marker.get('base_run') is not None):
        raise ValueError('fresh24.0 overlay identity differs from the declared source')
    upper=run/'upper'
    if {p.name for p in upper.iterdir()}!={'.realme-next-isolated.json'}:
        raise ValueError('fresh24.0 overlay contains unchecked changes')
    mount=mounted(tree)
    options=dict(p.split('=',1) for p in mount['options'].split(',') if '=' in p)
    if (mount['fstype']!='overlay' or options.get('lowerdir')!=str(lower) or
            options.get('upperdir')!=str(upper) or options.get('workdir')!=str(run/'work')):
        raise ValueError('overlay mount does not bind the checked source and private upper')
    return lower


def mounted(path):
    value = subprocess.check_output(
        ['findmnt', '--json', '--mountpoint', str(path), '-o', 'TARGET,SOURCE,FSTYPE,OPTIONS'],
        text=True)
    rows = json.loads(value)['filesystems']
    if len(rows) != 1 or rows[0]['target'] != str(path):
        raise ValueError('ambiguous storage mount: ' + str(path))
    return rows[0]


def registration_on_ssd(rows, distribution):
    matches = [row for row in rows if row['name'] == distribution]
    if len(matches) != 1:
        raise ValueError('ambiguous WSL distribution registration')
    path = matches[0]['path'].removeprefix('\\\\?\\').removeprefix('\\??\\')
    if not path.upper().startswith('C:\\'):
        raise ValueError('WSL root is not registered on Windows C:')
    return {'distribution': distribution, 'host_drive': 'C'}


def root_on_ssd():
    script = ("$ProgressPreference='SilentlyContinue'; "
              "@(Get-ChildItem HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Lxss | "
              "ForEach-Object { $r=Get-ItemProperty $_.PSPath; "
              "@{name=$r.DistributionName;path=$r.BasePath} }) | ConvertTo-Json -Compress")
    encoded = base64.b64encode(script.encode('utf-16le')).decode()
    rows = json.loads(subprocess.check_output(
        ['/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe',
         '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded], text=True))
    if isinstance(rows, dict):
        rows = [rows]
    distribution = os.environ.get('WSL_DISTRO_NAME')
    if not distribution:
        unc = subprocess.check_output(['/usr/bin/wslpath', '-w', '/'], text=True).strip().rstrip('\\')
        distribution = unc.rsplit('\\', 1)[-1]
    return registration_on_ssd(rows, distribution)


def verify_store(store=STORE):
    if Path(store).absolute() != STORE or STORE.is_symlink() or BACKING.is_symlink():
        raise ValueError('24.0 requires the dedicated store and backing paths')
    host = mounted(HOST)
    if host['fstype'] not in ('9p', 'drvfs') or not host['source'].upper().startswith('C:'):
        raise ValueError('/mnt/c does not identify Windows C:')
    mount = mounted(STORE)
    if mount['fstype'] != 'ext4' or 'rw' not in mount['options'].split(','):
        raise ValueError('24.0 store must be a writable ext4 mount')
    root = mounted(Path('/'))
    if (root['fstype'] != 'ext4' or mount['source'].split('[', 1)[0] != root['source']
            or BACKING.stat().st_dev != Path('/').stat().st_dev
            or not STORE.samefile(BACKING)):
        raise ValueError('store is not backed by the dedicated WSL-root directory')
    identity = json.loads((BACKING / 'storage-identity.json').read_text())
    if identity.get('schema') != 1 or identity.get('branch') != 'lineage-24.0' or identity.get('host_drive') != 'C':
        raise ValueError('24.0 SSD storage identity differs')
    registration = root_on_ssd()
    for name in ('tree', 'work', 'records', 'evidence', 'tmp'):
        path = STORE / name
        if path.is_symlink() or not path.is_dir() or path.stat().st_dev != STORE.stat().st_dev:
            raise ValueError('store child is absent, redirected or on another filesystem: ' + name)
    return {'host': host, 'store': mount, 'backing': str(BACKING),
            'registration': registration, 'backing_verified': True}
