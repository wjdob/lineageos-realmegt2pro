"""Check the candidate's qualified portrait dimensions in actual packaged RRO tables."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
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
