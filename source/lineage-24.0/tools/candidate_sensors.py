"""Check the 23.2 candidate's packaged sensor wiring; never contacts a device.

This is not ELF ABI, SELinux, full VINTF compatibility or runtime validation.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import xml.etree.ElementTree as ET
import zipfile

from package_coverage import sha

SERVICE = 'android.hardware.sensors-service.oplus-multihal'
EXECUTABLE = 'VENDOR/bin/hw/' + SERVICE
RC = 'VENDOR/etc/init/' + SERVICE + '.rc'
MANIFEST = 'VENDOR/etc/vintf/manifest/android.hardware.sensors.oplus-multihal.xml'
CONFIG = 'VENDOR/etc/sensors/hals.conf'
LIBRARIES = ['sensors.ssc.so', 'sensors.oplus.so']
SUB_HAL_CONFIG = ['sensors.dynamic_sensor_hal.so', *LIBRARIES]
REQUIRED = [EXECUTABLE, RC, MANIFEST, CONFIG,
            *['VENDOR/lib64/' + name for name in LIBRARIES],
            'VENDOR/lib64/hw/sensors.dynamic_sensor_hal.so']


def inspect(package):
    issues, members, services, declarations = [], {}, [], []
    with zipfile.ZipFile(package) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError('duplicate archive member')
        for name in REQUIRED:
            if name not in names or archive.getinfo(name).file_size == 0:
                issues.append('missing/empty member: ' + name)
                continue
            with archive.open(name) as stream:
                h = hashlib.sha256()
                for data in iter(lambda: stream.read(1024 * 1024), b''):
                    h.update(data)
            members[name] = {'bytes': archive.getinfo(name).file_size, 'sha256': h.hexdigest()}
        competitors = sorted(n for n in names if '/bin/hw/android.hardware.sensors' in n
                             and n != EXECUTABLE and not n.endswith('/'))
        if competitors:
            issues.append('competing sensor executables')
        for name in names:
            if '/etc/init/' in name and name.endswith('.rc'):
                for line in archive.read(name).decode().splitlines():
                    if not line.lstrip().startswith('service '):
                        continue
                    # Android init rc permits a trailing backslash to continue a
                    # service declaration. The checker only needs its first line's
                    # name and executable, so remove that continuation marker first.
                    directive = line.rstrip()
                    if directive.endswith('\\'):
                        directive = directive[:-1].rstrip()
                    fields = shlex.split(directive, comments=True)
                    if len(fields) >= 3 and fields[0] == 'service':
                        if 'sensors' in fields[1] or 'android.hardware.sensors' in fields[2]:
                            services.append({'member': name, 'name': fields[1], 'command': fields[2:]})
            if name.startswith(('VENDOR/etc/vintf/', 'ODM/etc/vintf/')) and name.endswith('.xml'):
                root = ET.fromstring(archive.read(name))
                if root.tag != 'manifest':
                    continue
                for hal in root.findall('hal'):
                    if hal.findtext('name') == 'android.hardware.sensors':
                        declarations.append({'member': name, 'format': hal.get('format'),
                                             'versions': [x.text for x in hal.findall('version')],
                                             'fqnames': [x.text for x in hal.findall('fqname')]})
        selected = [s for s in services if s['name'] == 'vendor.sensors-hal-multihal'
                    or s['command'][0] == '/vendor/bin/hw/' + SERVICE]
        expected = {'member': RC, 'name': 'vendor.sensors-hal-multihal',
                    'command': ['/vendor/bin/hw/' + SERVICE]}
        if selected != [expected]:
            issues.append('expected exactly one Oplus init service with the reviewed command')
        if any('android.hardware.sensors' in s['command'][0]
               and s['command'][0] != expected['command'][0] for s in services):
            issues.append('competing sensor init command')
        expected_hal = {'member': MANIFEST, 'format': 'aidl', 'versions': ['3'],
                        'fqnames': ['ISensors/default']}
        if declarations != [expected_hal]:
            issues.append('expected exactly one reviewed AIDL v3 sensors declaration')
        hals = []
        if CONFIG in names:
            hals = [s.split('#', 1)[0].strip() for s in archive.read(CONFIG).decode().splitlines()]
            hals = [s for s in hals if s]
        if hals != SUB_HAL_CONFIG:
            issues.append('sub-HAL configuration differs from reviewed source')
    return {'sensor_contract_pass': not issues, 'issues': issues, 'members': members,
            'competing_executables': competitors, 'init_services': services,
            'sensor_declarations': declarations, 'sub_hals': hals,
            'limits': 'Packaged paths, hashes, init command, device sensor declaration and sub-HAL configuration only; no ELF ABI, SELinux, full VINTF or runtime validation.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-record', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    record = json.loads(args.run_record.read_text())
    if record.get('state') != 'success':
        raise ValueError('successful collector record required')
    entries = [e for e in record['artifacts'] if e['path'].endswith('/lineage_ferrari-target_files.zip')]
    if len(entries) != 1:
        raise ValueError('one collected target-files archive required')
    entry = entries[0]
    package = Path(entry['collected'])
    if package.stat().st_size != entry['bytes'] or sha(package) != entry['sha256']:
        raise ValueError('collected archive changed')
    result = inspect(package)
    result['provenance'] = {'run_record_sha256': sha(args.run_record),
                            'target_files_sha256': entry['sha256'], 'tool_sha256': sha(Path(__file__))}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k: result[k] for k in ('sensor_contract_pass', 'issues')}))
    return 0 if result['sensor_contract_pass'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
