"""Check collected ferrari kernel modules, load lists and hard dependencies.

Packaging warnings are neither waived nor treated as boot failures. This checks
the resulting files; it never loads modules or accesses the device.
"""
import argparse
import datetime
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import struct
import zipfile

from payload_image_binding import collected, sha

POOLS = {
    'VENDOR_BOOT/RAMDISK/lib/modules': ('/lib/modules/', ('modules.load', 'modules.load.recovery')),
    'VENDOR_DLKM/lib/modules': ('/vendor_dlkm/lib/modules/', ('modules.load',)),
}


def modinfo(data):
    if (len(data) < 64 or data[:6] != b'\x7fELF\x02\x01'
            or struct.unpack_from('<HH', data, 16) != (1, 183)):
        raise ValueError('expected AArch64 ELF64 relocatable module')
    offset = struct.unpack_from('<Q', data, 40)[0]
    size, count, names_index = struct.unpack_from('<HHH', data, 58)
    if size != 64 or not count or names_index >= count or offset+size*count > len(data):
        raise ValueError('invalid module section table')
    sections = [struct.unpack_from('<IIQQQQIIQQ', data, offset+i*size) for i in range(count)]
    names = sections[names_index]
    if names[4]+names[5] > len(data):
        raise ValueError('invalid section names')
    strings = data[names[4]:names[4]+names[5]]
    selected = []
    for section in sections:
        start = section[0]
        if start >= len(strings) or b'\0' not in strings[start:]:
            raise ValueError('invalid section name offset')
        if strings[start:strings.index(0, start)] == b'.modinfo':
            selected.append(section)
    if len(selected) != 1:
        raise ValueError('one .modinfo section required')
    section = selected[0]
    if section[1] != 1 or section[4]+section[5] > len(data):
        raise ValueError('invalid .modinfo data')
    values = {}
    for raw in data[section[4]:section[4]+section[5]].split(b'\0'):
        if b'=' in raw:
            key, value = raw.decode().split('=', 1)
            values.setdefault(key, []).append(value)
    if len(values.get('vermagic', [])) != 1 or len(values.get('depends', [])) > 1:
        raise ValueError('missing/ambiguous vermagic or depends')
    return dict(vermagic=values['vermagic'][0], depends=values.get('depends', [''])[0])


def module_path(token, prefix):
    if token.startswith(prefix):
        token = token[len(prefix):]
    path = PurePosixPath(token)
    if (not token or path.is_absolute() or '..' in path.parts or str(path) != token
            or not re.fullmatch(r'[A-Za-z0-9_/-]+\.ko', token)):
        raise ValueError('module reference escapes pool or has invalid syntax')
    return token


def normalized(name):
    if not re.fullmatch(r'[A-Za-z0-9_-]+', name):
        raise ValueError('invalid module load/dependency name')
    return name.replace('-', '_')


def reachable(graph, start):
    visited, stack = set(), list(graph.get(start, ()))
    while stack:
        name = stack.pop()
        if name in visited:
            continue
        visited.add(name)
        stack.extend(graph.get(name, ()))
    return visited


def check(target_files):
    issues, groups, vermagics = [], [], set()
    with zipfile.ZipFile(target_files) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError('duplicate target-files member')
        version = archive.read('META/kernel_version.txt').decode().strip()
        if not re.fullmatch(r'\d+\.\d+\.\d+[A-Za-z0-9._+-]*', version):
            raise ValueError('invalid exact packaged kernel release')
        all_modules = [n for n in names if n.endswith('.ko')]
        for member in all_modules:
            if not any(member.startswith(pool+'/') for pool in POOLS):
                issues.append(member+': unexpected module pool')
        for pool, (prefix, load_files) in POOLS.items():
            modules, aliases, graph, local_issues = {}, {}, {}, []
            for member in all_modules:
                if not member.startswith(pool+'/'):
                    continue
                relative = member[len(pool)+1:]
                try:
                    module_path(relative, prefix)
                    data = archive.read(member)
                    info = modinfo(data)
                    modules[relative] = dict(member=member, sha256=hashlib.sha256(data).hexdigest(), **info)
                    alias = normalized(PurePosixPath(relative).stem)
                    if alias in aliases:
                        raise ValueError('ambiguous normalized module name')
                    aliases[alias] = relative
                    vermagics.add(info['vermagic'])
                    if info['vermagic'].split()[0] != version:
                        raise ValueError('module release differs from packaged kernel release')
                except (ValueError, UnicodeError, IndexError, struct.error) as error:
                    local_issues.append(relative+': '+str(error))
            if not modules:
                local_issues.append('empty required module pool')
            dep_name = pool+'/modules.dep'
            if dep_name not in names:
                local_issues.append('missing modules.dep')
            else:
                for line in archive.read(dep_name).decode().splitlines():
                    if not line.strip() or line.lstrip().startswith('#'):
                        continue
                    try:
                        left, right = line.split(':', 1)
                        node = module_path(left.strip(), prefix)
                        if node in graph:
                            raise ValueError('duplicate dependency key')
                        graph[node] = [module_path(token, prefix) for token in right.split()]
                    except ValueError as error:
                        local_issues.append('modules.dep: '+str(error))
            for node, info in modules.items():
                if node not in graph:
                    local_issues.append(node+': no dependency record')
                for dep in graph.get(node, ()):
                    if dep not in modules:
                        local_issues.append(node+': packaged dependency missing: '+dep)
                closure = reachable(graph, node)
                if node in closure:
                    local_issues.append(node+': cyclic hard dependencies')
                for dependency in filter(None, info['depends'].split(',')):
                    try:
                        resolved = aliases.get(normalized(dependency))
                        if resolved is None or resolved not in closure:
                            local_issues.append(node+': modinfo dependency absent from files/depmod closure: '+dependency)
                    except ValueError as error:
                        local_issues.append(node+': '+str(error))
            loads = []
            for filename in load_files:
                member = pool+'/'+filename
                if member not in names:
                    local_issues.append('missing '+filename)
                    continue
                entries = []
                for line in archive.read(member).decode().splitlines():
                    token = line.split('#', 1)[0].strip()
                    if not token:
                        continue
                    try:
                        alias = normalized(token.removesuffix('.ko'))
                        if alias not in aliases:
                            raise ValueError('load root has no packaged module: '+token)
                        entries.append(alias)
                    except ValueError as error:
                        local_issues.append(filename+': '+str(error))
                if not entries:
                    local_issues.append('empty '+filename)
                loads.append(dict(member=member, entries=len(entries), unique=len(set(entries)),
                                  duplicates=sorted({n for n in entries if entries.count(n)>1})))
            groups.append(dict(pool=pool, module_count=len(modules), modules=modules, load_lists=loads,
                               unused_dependency_records=sorted(set(graph)-set(modules)), issues=local_issues))
            issues.extend(pool+': '+issue for issue in local_issues)
    if len(vermagics) != 1:
        issues.append('nonuniform full vermagic across packaged modules')
    return dict(kernel_modules_pass=not issues, kernel_release=version,
                module_count=len(all_modules), vermagic_values=sorted(vermagics), groups=groups, issues=issues,
                limits='Exact AArch64 ELF/modinfo release, uniform vermagic, packaged dependency/load-list closure only. '
                'Unused depmod keys may describe uninstalled staging modules; they are recorded, not mandatory files. '
                'Repeated valid load entries are reported, not failures. No module signature, exported-symbol CRC/kernel '
                'ABI compatibility, actual init loading, hardware, boot or recovery acceptance is implied.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-record', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    record = json.loads(args.run_record.read_text())
    if record.get('state') != 'success' or not record.get('finished_ns'):
        raise ValueError('successful terminal collector record required')
    package, artifact = collected(record, '/lineage_ferrari-target_files.zip')
    before = (package.stat().st_size, package.stat().st_mtime_ns)
    result = check(package)
    if before != (package.stat().st_size, package.stat().st_mtime_ns):
        raise ValueError('target-files changed during module check')
    result.update(observed_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  run_record_sha256=sha(args.run_record), target_files_sha256=artifact['sha256'],
                  tool_sha256=sha(Path(__file__)))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open('x') as stream:
        stream.write(json.dumps(result, indent=2)+'\n')
    print(json.dumps({k:result[k] for k in ('kernel_modules_pass','kernel_release','module_count','issues')}))
    return 0 if result['kernel_modules_pass'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
