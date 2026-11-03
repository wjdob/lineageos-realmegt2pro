"""Check Ferrari's wrapper/provider restart dependency, without device operations.

The device override preserves the common upstream wrapper definition. Its
onrestart command runs inline during init's Reap, before the wrapper is eligible
for restart. Source/package checks do not establish physical recovery acceptance.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import zipfile

ROOT = Path(__file__).resolve().parents[1]
RELATIVE = 'device/realme/ferrari/init/init.ferrari.fingerprint.rc'
TEMPLATE = 'overlays/lineage-23.2/ferrari/init/init.ferrari.fingerprint.rc'
MEMBER = 'VENDOR/etc/init/init.ferrari.fingerprint.rc'
COPY = ('$(LOCAL_PATH)/init/init.ferrari.fingerprint.rc:'
        '$(TARGET_COPY_OUT_VENDOR)/etc/init/init.ferrari.fingerprint.rc')
WRAPPER = 'vendor.fps_hal_oplus'
WRAPPER_EXE = '/vendor/bin/hw/android.hardware.biometrics.fingerprint@2.3-service.oplus'
PROVIDER_EXE = '/odm/bin/hw/vendor.oplus.hardware.biometrics.fingerprint@2.1-service'
WRAPPER_RC = 'VENDOR/etc/init/android.hardware.biometrics.fingerprint@2.3-service.oplus.rc'
PROVIDER_RC = 'ODM/etc/init/vendor.oplus.hardware.biometrics.fingerprint@2.1-service.rc'
REFERENCES = {
    WRAPPER_RC: '0966c9b82a03e2f291903c80ce416f1cd58bdfe65e476af72e3715e7c595b7b7',
    PROVIDER_RC: '1d9a101c7523ecd78a433477cf8f99c93f97f230ecdcde7bd1b33009f3f43919',
    'VENDOR' + WRAPPER_EXE.removeprefix('/vendor'): '6066f6bb531682febc16638fa7a0d57b0ef485a8143d45d00c9fc78e3cf39045',
    'ODM' + PROVIDER_EXE.removeprefix('/odm'): 'e20a9ec4b12feb33f6fa15341a169a066802e1512984ca5f4ec38bc4afaef12d',
}
SERVICE = 'service ' + WRAPPER + ' ' + WRAPPER_EXE
EXPECTED = [SERVICE, 'override', 'class late_start', 'user system',
            'group system', 'onrestart restart fps_hal']


def validate(data):
    lines = [line.strip() for line in data.decode('utf-8').splitlines()
             if line.strip() and not line.lstrip().startswith('#')]
    if lines != EXPECTED:
        raise ValueError('expected the exact Ferrari wrapper override and one provider restart')
    return hashlib.sha256(data).hexdigest()


def check_source(tree):
    tree = Path(tree)
    data = (tree / RELATIVE).read_bytes()
    digest = validate(data)
    if data != (ROOT / TEMPLATE).read_bytes():
        raise ValueError('source dependency differs from reviewed template')
    make = (tree / 'device/realme/ferrari/device.mk').read_text()
    logical = '\n'.join(line.split('#', 1)[0] for line in make.splitlines()).replace('\\\n', ' ')
    copies = []
    for line in logical.splitlines():
        match = re.fullmatch(r'\s*PRODUCT_COPY_FILES\s*\+?=\s*(.*)', line)
        if match:
            copies.extend(match[1].split())
    destination = COPY.split(':')[1]
    if copies.count(COPY) != 1 or sum(c.rsplit(':', 1)[-1] == destination for c in copies) != 1:
        raise ValueError('dependency must be installed exactly once by ferrari device.mk')
    return {'fingerprint_dependency_source_pass': True, 'path': RELATIVE,
            'sha256': digest, 'limits': 'Source/wiring only; automatic idle/active recovery untested.'}


def check_package(target_files):
    with zipfile.ZipFile(target_files) as archive:
        names = archive.namelist()
        for name in [MEMBER, *REFERENCES]:
            if names.count(name) != 1:
                raise ValueError('expected exactly one dependency/reference member: ' + name)
        data = archive.read(MEMBER)
        digest = validate(data)
        if data != (ROOT / TEMPLATE).read_bytes():
            raise ValueError('packaged dependency differs from reviewed template')
        for name, expected in REFERENCES.items():
            if hashlib.sha256(archive.read(name)).hexdigest() != expected:
                raise ValueError('fingerprint service/reference changed: ' + name)
        # Init sorts each directory. Both wrapper definitions must be in vendor,
        # with this device override last; reject an extra override or provider.
        declarations = {WRAPPER: [], 'fps_hal': []}
        for name in names:
            if not name.endswith('.rc') or not name.startswith(('VENDOR/etc/init/', 'ODM/etc/init/')):
                continue
            text = archive.read(name).decode('utf-8')
            for service in declarations:
                declarations[service].extend([name] * len(re.findall(
                    r'^service\s+' + re.escape(service) + r'\s+', text, re.MULTILINE)))
        if sorted(declarations[WRAPPER]) != [WRAPPER_RC, MEMBER] or declarations['fps_hal'] != [PROVIDER_RC]:
            raise ValueError('unexpected competing fingerprint service definition')
    return {'fingerprint_dependency_package_pass': True, 'member': MEMBER,
            'sha256': digest, 'references': REFERENCES,
            'limits': 'Payload and init definition order only; live idle/active recovery and retained unlock need UAT.'}


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
