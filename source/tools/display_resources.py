"""Check the candidate's qualified portrait dimensions in actual packaged RRO tables."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET
import zipfile

REPO = Path(__file__).resolve().parents[1]
EXPECTED = {
    'OPlusFrameworksResTarget': {
        'status_bar_height_portrait': {'port-2412x1080': 114, 'port-3216x1440': 152}},
    'OPlusSystemUIResTarget': {
        'qs_header_row_min_height': {'port-2412x1080': 125, 'port-3216x1440': 166},
        # aapt2 may eliminate the redundant FHD entry identical to the default.
        'status_bar_padding_top': {'': 11, 'port-3216x1440': 14, 'land': 0}},
}


def dimensions(dump):
    result, current = {}, None
    for line in dump.splitlines():
        match = re.match(r'\s*resource 0x[0-9a-f]+ (\S+)', line)
        if match:
            current = match[1][6:] if match[1].startswith('dimen/') else None
            if current is not None:
                result[current] = {}
        match = re.match(r'\s*\(([^)]*)\) (-?[0-9.]+)px\s*$', line)
        if current is not None and match:
            if match[1] in result[current]:
                raise ValueError('duplicate dimension configuration')
            result[current][match[1]] = float(match[2])
    return result


def check_dump(module, dump):
    actual = dimensions(dump)
    for name, configurations in EXPECTED[module].items():
        for qualifier, expected in configurations.items():
            if actual.get(name, {}).get(qualifier) != expected:
                raise ValueError(f'{module}: {name} ({qualifier}) must be {expected}px')
    return actual


def check_keyguard_dump(dump):
    """Require the explicit font-padding choice on the actual carrier node."""
    sections = []
    lines = dump.splitlines()
    for index, line in enumerate(lines):
        match = re.match(r'(\s*)E: com\.android\.keyguard\.CarrierText(?:\s|\(|$)', line)
        if not match:
            continue
        section = []
        for child in lines[index+1:]:
            node = re.match(r'(\s*)E:', child)
            if node:
                break
            section.append(child)
        sections.append(section)
    if len(sections) != 1:
        raise ValueError('expected one keyguard CarrierText node')
    attributes = [line for line in sections[0] if 'android:includeFontPadding' in line]
    if len(attributes) != 1 or not re.search(
            r'android:includeFontPadding(?:\(0x[0-9a-fA-F]+\))?\s*=\s*'
            r'(?:(?:\(type 0x12\))?0x0|false)\s*$', attributes[0]):
        raise ValueError('keyguard CarrierText must explicitly disable font padding')
    return {'carrier_font_padding': False,
            'limit': 'Compiled layout attribute only; no rendered or physical-cutout acceptance.'}


def check_qqs_source(xml):
    """Require the initially inflated guideline in the configuration-reloaded set."""
    android = '{http://schemas.android.com/apk/res/android}'
    app = '{http://schemas.android.com/apk/res-auto}'
    root = ET.fromstring(xml)
    matches = [node for node in root.findall('Constraint')
               if node.get(android + 'id') in ('@id/qqs_header_bottom_guideline',
                                               '@+id/qqs_header_bottom_guideline')]
    if len(matches) != 1:
        raise ValueError('QQS must reload exactly one bottom guideline')
    layouts = matches[0].findall('Layout')
    if (len(layouts) != 1 or layouts[0].get(android + 'orientation') != 'horizontal' or
            layouts[0].get(app + 'layout_constraintGuide_begin') !=
            '@dimen/large_screen_shade_header_min_height'):
        raise ValueError('QQS guideline must use the horizontal live row dimension')
    return {'guideline_reloaded': True, 'dimension': 'large_screen_shade_header_min_height'}


def check_qqs_dump(dump, resources):
    """Bind the compiled guideline to its dimension, independently of resource IDs."""
    ids = {name: value.lower() for value, name in re.findall(
        r'^\s*resource (0x[0-9a-fA-F]+) (\S+)', resources, re.M)}
    required = ('id/qqs_header_bottom_guideline', 'dimen/large_screen_shade_header_min_height')
    if any(name not in ids for name in required):
        raise ValueError('QQS guideline resource identities are missing')
    sections = []
    lines = dump.splitlines()
    for index, line in enumerate(lines):
        match = re.match(r'(\s*)E: Constraint(?:\s|$)', line)
        if not match:
            continue
        section = []
        for child in lines[index+1:]:
            node = re.match(r'(\s*)E:', child)
            if node and len(node[1]) <= len(match[1]):
                break
            section.append(child)
        text = '\n'.join(section)
        identity = re.search(r'android:id(?:\([^)]*\))?\s*=\s*@(0x[0-9a-fA-F]+)', text)
        if identity and identity[1].lower() == ids[required[0]]:
            sections.append(text)
    if len(sections) != 1:
        raise ValueError('QQS must compile exactly one reloaded bottom guideline')
    references = re.findall(r'\blayout_constraintGuide_begin(?:\([^)]*\))?\s*=\s*'
                            r'@(0x[0-9a-fA-F]+)\s*$', sections[0], re.M)
    orientation = re.findall(r'android:orientation(?:\([^)]*\))?\s*=\s*'
                             r'(?:\(type 0x10\))?\s*(0x[0-9a-fA-F]+|[0-9]+)\s*$',
                             sections[0], re.M)
    # The pinned native aapt2 renders the linked enum as decimal0. Older dump
    # forms include an explicit integer type and hexadecimal0x0. Bind the same
    # integer value while rejecting strings, references and trailing garbage.
    values = [int(value, 16 if value.startswith('0x') else 10) for value in orientation]
    if ([value.lower() for value in references] != [ids[required[1]]] or
            values != [0]):
        raise ValueError('Compiled QQS guideline must use the horizontal row dimension')
    return {'guideline_reloaded': True, 'dimension_resource': ids[required[1]],
            'limit': 'Compiled XML binding only; physical resolution switching remains a UAT check.'}


def check_package(target_files, aapt2):
    reports = {}
    scratch_root = REPO / 'tmp'
    scratch_root.mkdir(exist_ok=True)
    with zipfile.ZipFile(target_files) as archive, tempfile.TemporaryDirectory(
            prefix='display-resources-', dir=scratch_root) as scratch:
        for module in EXPECTED:
            matches = [n for n in archive.namelist()
                       if n.startswith('ODM/overlay/') and n.endswith('/' + module + '.apk')]
            if len(matches) != 1:
                raise ValueError('expected one ODM overlay: ' + module)
            data = archive.read(matches[0])
            apk = Path(scratch) / (module + '.apk')
            apk.write_bytes(data)
            dump = subprocess.check_output([str(aapt2), 'dump', 'resources', str(apk)],
                                           text=True, timeout=60)
            reports[module] = {'member': matches[0], 'sha256': hashlib.sha256(data).hexdigest(),
                               'dimensions': check_dump(module, dump)}
        matches = [name for name in archive.namelist()
                   if name.startswith('SYSTEM_EXT/') and name.endswith('/SystemUI/SystemUI.apk')]
        if len(matches) != 1:
            raise ValueError('expected one packaged SystemUI APK')
        data = archive.read(matches[0])
        apk = Path(scratch)/'SystemUI.apk'; apk.write_bytes(data)
        dump = subprocess.check_output([str(aapt2), 'dump', 'xmltree', '--file',
            'res/layout/keyguard_status_bar.xml', str(apk)], text=True, timeout=60)
        reports['keyguard'] = {'member': matches[0], 'sha256': hashlib.sha256(data).hexdigest(),
                               **check_keyguard_dump(dump)}
        resource_dump = subprocess.check_output([str(aapt2), 'dump', 'resources', str(apk)],
                                               text=True, timeout=60)
        qqs_dump = subprocess.check_output([str(aapt2), 'dump', 'xmltree', '--file',
            'res/xml/qqs_header.xml', str(apk)], text=True, timeout=60)
        reports['qqs_header'] = {'member': matches[0], 'sha256': hashlib.sha256(data).hexdigest(),
                                **check_qqs_dump(qqs_dump, resource_dump)}
    return {'display_resources_pass': True, 'overlays': reports,
            'limit': 'Packaged dimensions only; idmap, drawing, interaction and QHD visual behavior untested.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target-files', required=True, type=Path)
    parser.add_argument('--aapt2', required=True, type=Path)
    parser.add_argument('--report', required=True, type=Path)
    args = parser.parse_args()
    result = check_package(args.target_files, args.aapt2)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'display_resources_pass': True}))
