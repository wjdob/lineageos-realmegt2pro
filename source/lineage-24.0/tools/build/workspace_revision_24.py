"""Read a Windows-created worktree's HEAD from Linux without editing Git metadata."""
import os
from pathlib import Path, PureWindowsPath
import re
import subprocess


def windows_gitdir(value):
    path=PureWindowsPath(value)
    if not path.is_absolute() or not re.fullmatch(r'[A-Za-z]:',path.drive):
        raise ValueError('expected a local Windows drive path')
    return Path('/mnt')/path.drive[0].lower()/Path(*path.parts[1:])


def revision(repo):
    repo=Path(repo).resolve()
    metadata=repo/'.git'
    if metadata.is_file():
        lines=metadata.read_text().splitlines()
        if len(lines)!=1 or not lines[0].startswith('gitdir: '):
            raise ValueError('unsupported workspace Git file')
        value=lines[0][8:]
        if re.match(r'^[A-Za-z]:[\\/]',value):
            metadata=windows_gitdir(value)
        else:
            metadata=(repo/value).resolve()
    if not metadata.is_dir():
        raise ValueError('workspace Git directory is missing')
    head=subprocess.check_output(['git','-c','safe.directory='+str(repo),
        '--git-dir='+str(metadata),'--work-tree='+str(repo),'rev-parse','HEAD'],
        env={**os.environ,'GIT_OPTIONAL_LOCKS':'0'},text=True).strip()
    if not re.fullmatch('[0-9a-f]{40}',head):
        raise ValueError('invalid workspace HEAD')
    return head
