"""Strict reader for flat, explicitly pinned repo manifests used by this project."""
import re
from pathlib import PurePosixPath
import xml.etree.ElementTree as ET


def read_pins(path):
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        raise ValueError(f'malformed manifest XML: {exc}') from exc
    if root.tag != 'manifest':
        raise ValueError('expected a manifest root')
    if any(root.findall(tag) for tag in ('include', 'submanifest', 'extend-project', 'remove-project')):
        raise ValueError('resolve manifest includes/overrides before checking pins')
    pins = {}
    paths = set()
    for project in root.findall('project'):
        if project.findall('project'):
            raise ValueError('nested projects must be flattened before checking pins')
        name = project.get('name', '')
        location = project.get('path', name)
        revision = project.get('revision', '')
        if not name or not location:
            raise ValueError('project name and path must be nonempty')
        parts = PurePosixPath(location)
        if parts.is_absolute() or '..' in parts.parts or '\\' in location or ':' in location or str(parts) == '.':
            raise ValueError(f'unsafe project path: {location}')
        location = str(parts)
        if not re.fullmatch(r'[0-9a-f]{40}', revision):
            raise ValueError(f'unpinned project: {name} at {location}')
        if location in paths:
            raise ValueError(f'duplicate project path: {location}')
        paths.add(location)
        pins[(name, location)] = revision
    if not pins:
        raise ValueError('manifest contains no pinned projects')
    return pins
