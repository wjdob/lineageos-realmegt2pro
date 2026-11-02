"""Bind the ferrari-only direct-backlight policy to source and target-files.

This checks packaging and scope, not a boot, SELinux grant or display acceptance.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import zipfile

ROOT = Path(__file__).resolve().parents[1]
RELATIVE = 'device/realme/ferrari/init/init.ferrari.display.rc'
TEMPLATE = 'overlays/lineage-23.2/ferrari/init/init.ferrari.display.rc'
MEMBER = 'VENDOR/etc/init/init.ferrari.display.rc'
TRIGGER = 'on property:ro.boot.prjname=21631 && property:sys.boot_completed=1'
COMMAND = 'write /sys/kernel/oplus_display/backlight_smooth 0'
COPY = ('$(LOCAL_PATH)/init/init.ferrari.display.rc:'
        '$(TARGET_COPY_OUT_VENDOR)/etc/init/init.ferrari.display.rc')


def validate(data):
    lines = [line.strip() for line in data.decode('utf-8').splitlines()
             if line.strip() and not line.lstrip().startswith('#')]
    if lines != [TRIGGER, COMMAND]:
        raise ValueError('expected one project21631/boot-complete scoped backlight write')
    return hashlib.sha256(data).hexdigest()


def check_source(tree):
    tree = Path(tree)
    data = (tree / RELATIVE).read_bytes()
    digest = validate(data)
    if data != (ROOT / TEMPLATE).read_bytes():
        raise ValueError('source policy differs from reviewed template')
    make = (tree / 'device/realme/ferrari/device.mk').read_text()
    logical = '\n'.join(line.split('#', 1)[0] for line in make.splitlines())
    logical = logical.replace('\\\n', ' ')
    copies = []
    for line in logical.splitlines():
        match = re.fullmatch(r'\s*PRODUCT_COPY_FILES\s*\+?=\s*(.*)', line)
        if match:
            copies.extend(match[1].split())
    if copies.count(COPY) != 1:
        raise ValueError('policy must be installed exactly once by ferrari device.mk')
    return {'backlight_source_pass': True, 'path': RELATIVE, 'sha256': digest,
            'limits': 'Source/wiring only; packaged boot execution and hardware untested.'}


def check_package(target_files):
    with zipfile.ZipFile(target_files) as archive:
        if archive.namelist().count(MEMBER) != 1:
            raise ValueError('expected exactly one vendor init backlight policy')
        data = archive.read(MEMBER)
    digest = validate(data)
    if data != (ROOT / TEMPLATE).read_bytes():
        raise ValueError('packaged policy differs from reviewed template')
    return {'backlight_package_pass': True, 'member': MEMBER, 'sha256': digest,
            'limits': 'Payload only; init execution, SELinux and display/fingerprint regressions require live acceptance.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--source-tree', type=Path)
    group.add_argument('--target-files', type=Path)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    result = check_source(args.source_tree) if args.source_tree else check_package(args.target_files)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))
