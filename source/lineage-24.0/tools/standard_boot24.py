"""Prepare package-bound expectations and capture read-only Android17 boot phases.

No root request, reboot, flash, service restart, mount, log clear or device write.
Hardware UAT and the reviewed installation/return procedure remain separate.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
KIND = 'lineage24-standard-observation-v1'
RECEIPT = 'lineage24-standard-observation-receipt-v1'
SERVICES = ('audioserver', 'zygote', 'keystore2', 'vold', 'fps_hal',
            'vendor.sensors-hal-multihal')
TEMPORARY = ('/system_ext/etc/init/lineage24-bootdiag.rc',
             '/system_ext/etc/lineage24-bootdiag.sh')
UUID = r'[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def full_hash(value):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value) is not None


def private(path):
    path = path.absolute()
    if (path.is_symlink() or any(p.is_symlink() for p in path.parents)
            or not path.resolve().is_relative_to((ROOT/'.local').resolve())):
        raise ValueError('output must stay in this checkout .local without symlinks')
    return path


def validate(config):
    if (set(config) != {'schema', 'kind', 'serial', 'source', 'target', 'evidence'}
            or config['schema'] != 1 or config['kind'] != KIND
            or not isinstance(config['serial'], str)
            or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9._:-]{0,63}', config['serial'])):
        raise ValueError('invalid Android17 observation config')
    for name, extra in [('source', set()), ('target', {'boot_sha256', 'boot_bytes'})]:
        row = config[name]
        if (not isinstance(row, dict) or set(row) != {'build', 'slot', 'sensor_sha256'} | extra
                or row['slot'] not in ('_a', '_b') or not full_hash(row['sensor_sha256'])
                or not isinstance(row['build'], str)
                or not re.fullmatch('[A-Za-z0-9._-]{1,160}', row['build'])):
            raise ValueError('invalid phase identity')
    if (config['source']['slot'] == config['target']['slot']
            or config['source']['build'] == config['target']['build']
            or not full_hash(config['target']['boot_sha256'])
            or type(config['target']['boot_bytes']) is not int
            or not 0 < config['target']['boot_bytes'] <= 512*1024**2):
        raise ValueError('distinct update identity and packaged boot required')
    evidence = config['evidence']
    if (not isinstance(evidence, dict) or set(evidence) != {'handoff_sha256', 'target_files_sha256', 'run', 'source_commit'}
            or not full_hash(evidence['handoff_sha256'])
            or not full_hash(evidence['target_files_sha256'])
            or not re.fullmatch(r'candidate-24-native-[0-9]+', evidence['run'])
            or not re.fullmatch('[0-9a-f]{40}', evidence['source_commit'])):
        raise ValueError('invalid package provenance')
    return config


def prepare(handoff, handoff_sha, target_files, target_sha, serial,
            source_build, source_slot, source_sensor, target_slot, output):
    output = private(output)
    if output.exists():
        raise ValueError('new expectation output required')
    if sha(handoff) != handoff_sha or sha(target_files) != target_sha:
        raise ValueError('package/handoff hash differs')
    staged = json.loads(handoff.read_text())
    if (staged['state'] != 'host-artifacts-staged'
            or staged['metadata']['post-sdk-level'] != '37'):
        raise ValueError('staged Android17 host handoff required')
    with zipfile.ZipFile(target_files) as archive:
        if len(archive.namelist()) != len(set(archive.namelist())):
            raise ValueError('duplicate target-files members')
        props = archive.read('SYSTEM/build.prop').decode().splitlines()
        build = staged['metadata']['post-build-incremental']
        if ([s for s in props if s.startswith('ro.build.version.sdk=')] != ['ro.build.version.sdk=37']
                or [s for s in props if s.startswith('ro.build.version.incremental=')] != [
                    'ro.build.version.incremental='+build]):
            raise ValueError('handoff/target Android identity differs')
        boot = archive.read('IMAGES/boot.img')
        if digest(boot) != staged['standard_packaged_boot_sha256']:
            raise ValueError('handoff/target packaged boot differs')
        sensor = archive.read('VENDOR/lib64/sensors.ssc.so')
    result = validate(dict(schema=1, kind=KIND, serial=serial,
        source=dict(build=source_build, slot=source_slot, sensor_sha256=source_sensor),
        target=dict(build=build, slot=target_slot, sensor_sha256=digest(sensor),
                    boot_sha256=digest(boot), boot_bytes=len(boot)),
        evidence=dict(handoff_sha256=handoff_sha, target_files_sha256=target_sha,
                      run=staged['run'], source_commit=staged['source_commit'])))
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('xb') as stream:
        stream.write((json.dumps(result, indent=2)+'\n').encode())
    return result


IDENTITY = {'boot_id': 'cat /proc/sys/kernel/random/boot_id',
            'build': 'getprop ro.build.version.incremental',
            'sdk': 'getprop ro.build.version.sdk', 'slot': 'getprop ro.boot.slot_suffix',
            'unlocked': 'getprop ro.boot.vbmeta.device_state'}


def parsed(reading):
    return reading.get('stdout', '').strip() if reading.get('exit_code') == 0 else None


def identity(config, phase, readings):
    values = {key: parsed(readings[key]) for key in IDENTITY}
    expected = config['source' if phase == 'baseline' else 'target']
    if (not values['boot_id'] or not re.fullmatch(UUID, values['boot_id'])
            or values['build'] != expected['build'] or values['sdk'] != '37'
            or values['slot'] != expected['slot'] or values['unlocked'] != 'unlocked'):
        raise ValueError('device/phase identity mismatch or unavailable')
    return values


def prior_receipt(path, expected_sha, config, config_sha, phase):
    if not path or not full_hash(expected_sha) or sha(path) != expected_sha:
        raise ValueError('matching prior phase receipt/hash required')
    row = json.loads(path.read_text())
    expected_phase = 'baseline' if phase == 'first-standard' else 'first-standard'
    if (row.get('kind') != RECEIPT or row.get('schema') != 1
            or row.get('phase') != expected_phase or row.get('serial') != config['serial']
            or row.get('config_sha256') != config_sha or row.get('capture_complete') is not True
            or row.get('checks', {}).get('same_boot', {}).get('status') != 'pass'
            or row.get('checks', {}).get('boot_completed', {}).get('status') != 'pass'):
        raise ValueError('prior phase is incomplete or belongs to another observation')
    raw = identity(config, expected_phase, row['readings'])
    if (row.get('identity') != raw or row.get('boot_id') != raw['boot_id']
            or parsed(row['readings'].get('boot_id_end', {})) != raw['boot_id']
            or parsed(row['readings'].get('boot_completed', {})) != '1'):
        raise ValueError('prior structured identity differs from raw observations')
    if expected_phase == 'first-standard' and (
            not re.fullmatch(UUID, row.get('baseline_boot_id', ''))
            or row['baseline_boot_id'] == row['boot_id']
            or not full_hash(row.get('prior_receipt_sha256'))):
        raise ValueError('prior first boot lacks its distinct baseline link')
    return row


def capture(config_path, config_sha, phase, output, adb='adb', prior=None,
            prior_sha=None, seconds=120, runner=subprocess.run):
    if not full_hash(config_sha) or sha(config_path) != config_sha:
        raise ValueError('expectation config hash differs')
    config = validate(json.loads(config_path.read_text()))
    if phase not in ('baseline', 'first-standard', 'second-standard') or not 1 <= seconds <= 120:
        raise ValueError('valid phase and1..120-second bound required')
    previous = None
    if phase != 'baseline':
        previous = prior_receipt(prior, prior_sha, config, config_sha, phase)
    elif prior is not None or prior_sha is not None:
        raise ValueError('baseline has no prior phase')
    output = private(output)
    output.mkdir(parents=True, exist_ok=False)
    result = dict(schema=1, kind=RECEIPT, observed_utc=datetime.now(timezone.utc).isoformat(),
        tool_sha256=sha(Path(__file__)), config_sha256=config_sha, serial=config['serial'],
        phase=phase, capture_complete=False, readings={}, checks={}, manual_uat='pending',
        limits='Read-only phase observations. Blocked privilege/transport reads remain blocked. '
               'Service properties and captured logs do not prove hardware, data retention or UAT.')
    if previous:
        result['prior_receipt_sha256'] = prior_sha
    deadline = time.monotonic()+seconds

    def read(label, command):
        remaining = deadline-time.monotonic()
        row = dict(command=command)
        if remaining <= 0:
            row['blocked'] = 'capture deadline'
        else:
            try:
                r = runner([adb, '-s', config['serial'], 'shell', command],
                           capture_output=True, text=True, timeout=min(8, remaining))
                row.update(exit_code=r.returncode, stdout=r.stdout, stderr=r.stderr)
                if r.returncode:
                    row['blocked'] = 'command returned nonzero'
            except subprocess.TimeoutExpired:
                row['blocked'] = 'observation timeout'
        result['readings'][label] = row
        return parsed(row)

    def check(name, value, detail=None):
        result['checks'][name] = dict(status='blocked' if value is None else 'pass' if value else 'fail')
        if detail:
            result['checks'][name]['detail'] = detail

    try:
        for name, command in IDENTITY.items():
            read(name, command)
        values = identity(config, phase, result['readings'])
        result.update(identity=values, boot_id=values['boot_id'])
        check('identity', True)
        if previous:
            distinct = values['boot_id'] != previous['boot_id']
            if phase == 'second-standard':
                distinct = distinct and values['boot_id'] != previous.get('baseline_boot_id')
            check('distinct_phase_boot', distinct)
            result['baseline_boot_id'] = previous['boot_id'] if phase == 'first-standard' else previous.get('baseline_boot_id')
        boot = read('boot_completed', 'getprop sys.boot_completed')
        check('boot_completed', None if boot is None else boot == '1')
        state = read('selinux', 'getenforce')
        check('selinux_enforcing', None if state is None else state == 'Enforcing')
        ce = read('ce_available', 'getprop sys.user.0.ce_available')
        check('credential_user_available', True if ce == 'true' else None, 'Unlock is a separate owner action')
        uid = re.match(r'^uid=([0-9]+)\([^)]*\)', read('uid', 'id') or '')
        result['root_observed'] = int(uid[1]) == 0 if uid else None
        read('uptime', 'cat /proc/uptime')
        for service in SERVICES:
            state = read('service_'+service, 'getprop init.svc.'+service)
            check('service_'+service, None if state is None else state == 'running')
            read('service_pid_'+service, 'getprop init.svc_debug_pid.'+service)
        sensor = read('sensor', 'sha256sum /vendor/lib64/sensors.ssc.so')
        match = re.fullmatch(r'([0-9a-f]{64})\s+/vendor/lib64/sensors\.ssc\.so', sensor or '')
        expected = config['source' if phase == 'baseline' else 'target']
        check('sensor_library', match[1] == expected['sensor_sha256'] if match else None)
        mounts = read('mounts', 'cat /proc/self/mountinfo')
        valid_mounts = mounts is not None and all(len(line.split()) >= 7 for line in mounts.splitlines()) and bool(mounts)
        check('no_sensor_bind_in_captured_namespace', not any(line.split()[4] == '/vendor/lib64/sensors.ssc.so' for line in mounts.splitlines()) if valid_mounts else None)
        command = ('for p in /system_ext/etc/init /system_ext/etc; do [ -r "$p" ] && [ -x "$p" ] || exit 13; done; '
                   'for f in '+ ' '.join(TEMPORARY) +'; do if [ -e "$f" ] || [ -L "$f" ]; then echo "$f"; fi; done; true')
        temporary = read('temporary_startup', command)
        if phase != 'baseline':
            check('temporary_startup_absent', None if temporary is None else not temporary)
            path = '/dev/block/by-name/boot'+config['target']['slot']
            value = read('physical_boot', 'sha256sum '+path)
            match = re.fullmatch(r'([0-9a-f]{64})\s+'+re.escape(path), value or '')
            check('standard_packaged_boot', match[1] == config['target']['boot_sha256'] if match else None)
        for name, command in [('sensors', 'dumpsys sensorservice'), ('fingerprint', 'dumpsys fingerprint'),
                              ('sound_cards', 'cat /proc/asound/cards'), ('snapshot', 'snapshotctl dump'),
                              ('crash', 'logcat -d -b crash -v epoch -t 200')]:
            value = read(name, command)
            meaningful = value is not None and (bool(value) or name == 'crash') and not re.search(
                r"(?im)^(?:Permission Denial:|Can't find service|Unknown command|usage:)", value or '')
            check('capture_'+name, True if meaningful else None)
        crash = parsed(result['readings']['crash'])
        check('no_captured_fatal_entries', not re.search(r'Fatal signal|FATAL EXCEPTION', crash)
              if crash is not None and result['checks']['capture_crash']['status'] == 'pass' else None)
        end = read('boot_id_end', IDENTITY['boot_id'])
        check('same_boot', end == values['boot_id'] if end and re.fullmatch(UUID, end) else None)
        result['capture_complete'] = True
    except ValueError as error:
        result['refused'] = str(error)
        available = all(parsed(result['readings'].get(name, {})) not in (None, '') for name in IDENTITY)
        available = available and re.fullmatch(UUID, parsed(result['readings'].get('boot_id', {})) or '') is not None
        check('identity', False if available else None)
    finally:
        result['automatic_checks_pass'] = result['capture_complete'] and all(r['status'] == 'pass' for r in result['checks'].values())
        result['failed_checks'] = [name for name, row in result['checks'].items() if row['status'] == 'fail']
        result['blocked_checks'] = [name for name, row in result['checks'].items() if row['status'] == 'blocked']
        result['finished_utc'] = datetime.now(timezone.utc).isoformat()
        (output/'capture.json').write_text(json.dumps(result, indent=2)+'\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action', required=True)
    p = commands.add_parser('prepare')
    for name in ['handoff', 'target-files', 'output']:
        p.add_argument('--'+name, type=Path, required=True)
    for name in ['handoff-sha256', 'target-files-sha256', 'serial', 'source-build', 'source-sensor-sha256']:
        p.add_argument('--'+name, required=True)
    for name in ['source-slot', 'target-slot']:
        p.add_argument('--'+name, choices=['_a', '_b'], required=True)
    p = commands.add_parser('capture')
    for name in ['config', 'output']:
        p.add_argument('--'+name, type=Path, required=True)
    p.add_argument('--config-sha256', required=True)
    p.add_argument('--phase', choices=['baseline', 'first-standard', 'second-standard'], required=True)
    p.add_argument('--prior', type=Path)
    p.add_argument('--prior-sha256')
    p.add_argument('--adb', default='adb')
    p.add_argument('--seconds', type=int, default=120)
    args = parser.parse_args()
    if args.action == 'prepare':
        result = prepare(args.handoff, args.handoff_sha256, args.target_files,
            args.target_files_sha256, args.serial, args.source_build, args.source_slot,
            args.source_sensor_sha256, args.target_slot, args.output)
        print(json.dumps({'run': result['evidence']['run'], 'config_sha256': sha(args.output)}))
    else:
        result = capture(args.config, args.config_sha256, args.phase, args.output,
                         args.adb, args.prior, args.prior_sha256, args.seconds)
        print(json.dumps({k: result[k] for k in ['phase', 'capture_complete', 'automatic_checks_pass', 'failed_checks', 'blocked_checks']}))
        raise SystemExit(0 if result['automatic_checks_pass'] else 2)


if __name__ == '__main__':
    main()
