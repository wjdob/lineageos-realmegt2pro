"""Select Ferrari-owned duplicates without installing two providers at one path."""
import re

NAMES = frozenset(('libcamera2ndk_vendor', 'libcvp2_1', 'libstfaceunlockocl',
                  'libziparchive_odm', 'manifest_oplus_face.xml',
                  'vendor.oplus.hardware.biometrics.face@1.0-service'))
FERRARI_NAMES = {'libcamera2ndk_vendor': 'libcamera2ndk_realme'}


def copy_destination(line):
    value = line.strip().removesuffix('\\').strip()
    if value.startswith('vendor/') and ':' in value:
        return value.split(':', 1)[1]
    return None


def select_ferrari(common_bp, common_mk, ferrari_mk):
    removed = []
    def block(match):
        text = match.group()
        name = re.search(r'^\s*name:\s*"([^"\n]+)"', text, re.M)
        if name and name[1] in NAMES:
            removed.append(name[1])
            return ''
        if name and name[1] == 'libmasc':
            # The source extraction list now enables the standard ELF check.
            # Also normalize the pinned pre-generated public vendor metadata.
            text = text.replace('    check_elf_files: false,\n', '')
        return text
    bp = re.sub(r'^[a-z_]+ \{\n.*?^\}\n', block, common_bp, flags=re.M | re.S)
    if set(removed) != NAMES or len(removed) != len(NAMES):
        raise ValueError('common duplicate provider set changed')
    for name in sorted(NAMES):
        target=FERRARI_NAMES.get(name,name)
        bp = bp.replace('"' + name + '"', '"//vendor/realme/ferrari:' + target + '"')
        if target!=name:
            bp = bp.replace('"' + target + '"', '"//vendor/realme/ferrari:' + target + '"')
    destinations = {copy_destination(l) for l in ferrari_mk.splitlines()} - {None}
    mk = []
    copies = []
    packages = []
    for line in common_mk.splitlines(keepends=True):
        token = line.strip().removesuffix('\\').strip()
        dest = copy_destination(line)
        if token in NAMES:
            packages.append(token)
        elif dest and dest in destinations:
            copies.append(dest)
        else:
            mk.append(line)
    # The common face library is an unselected empty stub, not a product package.
    if set(packages) != NAMES - {'libstfaceunlockocl'}:
        raise ValueError('common selected package set changed')
    return bp, ''.join(mk), {'providers': removed, 'copy_destinations': sorted(copies)}
