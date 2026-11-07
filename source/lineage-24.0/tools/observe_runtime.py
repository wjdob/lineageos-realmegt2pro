"""Read-only engineering runtime checkpoints; elapsed time is not hardware acceptance."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import shlex
import subprocess
import sys


CAPTURES = {
    'battery': 'dumpsys battery',
    'thermal': 'dumpsys thermalservice',
    'power': 'dumpsys power',
    'fingerprint': 'dumpsys fingerprint',
    'crash': 'logcat -b crash -d -v threadtime -t 3000',
    'snapshot': 'snapshotctl dump',
    'suspend': 'dumpsys suspend_control_internal',
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_suspend(text):
    section = text.partition('----- Suspend Stats -----')[2].partition('Last Failures:')[0]
    info = text.partition('Suspend Info:')[2]
    result = {}
    for name in ('success', 'fail', 'failed_freeze', 'failed_suspend', 'failed_resume'):
        match = re.search(r'^' + name + r':\s*(\d+)\s*$', section, re.MULTILINE)
        if match:
            result[name] = int(match.group(1))
    match = re.search(r'^total suspend time:\s*(\d+) ms\s*$', info, re.MULTILINE)
    if match:
        result['total_suspend_ms'] = int(match.group(1))
    return result if 'success' in result and 'fail' in result else None


def compare_suspend(baseline, current):
    result = dict(progress_observed=False)
    if baseline['boot_id'] != current['boot_id']:
        return dict(result, status='not comparable: different boot')
    before, after = baseline.get('suspend_stats'), current.get('suspend_stats')
    fields = ('success', 'fail', 'total_suspend_ms')
    if not before or not after or any(key not in before or key not in after for key in fields):
        return dict(result, status='unavailable: missing comparable suspend counters')
    delta = {key: after[key] - before[key] for key in fields}
    if any(value < 0 for value in delta.values()):
        return dict(result, status='not comparable: counters reset or inconsistent', delta=delta)
    return dict(result, status='measured', delta=delta,
                progress_observed=delta['success'] > 0 and delta['total_suspend_ms'] > 0,
                limits='Successful kernel entry and recorded sleep time only. Aborted '
                       'attempts need context; these counters do not prove drain, '
                       'deepest SoC sleep, charging or 24-hour normal use.')


def compare(baseline, current, required_hours=None):
    if required_hours is not None and (not math.isfinite(required_hours) or required_hours <= 0):
        raise ValueError('Required observation hours must be finite and positive')
    required_seconds = required_hours * 3600 if required_hours is not None else None
    start = datetime.fromisoformat(baseline['observed_utc'])
    end = datetime.fromisoformat(current['observed_utc'])
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError('Checkpoint times must include timezones')
    elapsed = (end - start).total_seconds()
    if elapsed < 0:
        raise ValueError('Observation predates baseline; inspect host clock')
    same_boot = baseline['boot_id'] == current['boot_id']
    same_build = baseline['build_incremental'] == current['build_incremental']
    uptime_delta = (float(current['uptime'].split()[0]) -
                    float(baseline['uptime'].split()[0])) if same_boot else None
    if same_boot and uptime_delta < 0:
        raise ValueError('Same boot ID with decreased uptime is contradictory')
    return {
        'wall_elapsed_seconds': elapsed,
        'same_boot': same_boot,
        'same_build': same_build,
        'same_boot_uptime_delta_seconds': uptime_delta,
        'required_observation_hours': required_hours,
        'wall_clock_required_duration_elapsed': (
            elapsed >= required_seconds if required_seconds is not None else None),
        'same_build_uninterrupted_required_duration': (
            same_boot and same_build and elapsed >= required_seconds and
            uptime_delta >= required_seconds) if required_seconds is not None else None,
        'wall_clock_24_hours': elapsed >= 86400,
        'same_build_uninterrupted_24_hours': (
            same_boot and same_build and elapsed >= 86400 and uptime_delta >= 86400),
        'suspend': compare_suspend(baseline, current),
        'normal_use_acceptance': 'unproven: requires actual workload and hardware review',
        'limits': 'Reboots/build changes need review. Even uninterrupted uptime cannot prove '
                  'normal use, suspend drain, physical hardware, all-data retention or '
                  'absence of crashes that have rotated out of the log buffers.',
    }


def load_baseline(path):
    data = json.loads(path.read_text(encoding='utf-8-sig'))
    # Accept both the original private baseline and this tool's checkpoint format.
    for label, row in data['captures'].items():
        if label not in CAPTURES:
            raise ValueError('Unknown baseline capture label')
        name = row.get('file', label + '-start.txt')
        if Path(name).name != name or '/' in name or '\\' in name:
            raise ValueError('Baseline capture must be a filename in its own directory')
        if sha(path.parent / name) != row['sha256']:
            raise ValueError('Baseline capture hash mismatch: ' + label)
        if label == 'suspend':
            parsed = parse_suspend((path.parent / name).read_text())
            if data.get('suspend_stats') != parsed:
                raise ValueError('Baseline structured suspend counters differ from raw capture')
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--adb', required=True)
    parser.add_argument('--serial', required=True)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--baseline', type=Path)
    parser.add_argument('--required-hours', type=float,
                        help='Optional explicit comparison threshold; beta monitoring has no default duration gate')
    parser.add_argument('--marker', help='Optional non-sensitive test file; contents are not copied')
    args = parser.parse_args()
    if args.required_hours is not None and (not math.isfinite(args.required_hours) or args.required_hours <= 0):
        parser.error('--required-hours must be finite and positive')
    if args.marker and not re.fullmatch(r'/sdcard/Download/[A-Za-z0-9_.-]+', args.marker):
        parser.error('--marker must be a simple filename under /sdcard/Download/')
    baseline = load_baseline(args.baseline) if args.baseline else None
    args.output.mkdir(parents=True, exist_ok=False)
    report = dict(observed_utc=datetime.now(timezone.utc).isoformat(),
                  observation_complete=False, commands=[], captures={},
                  serial=args.serial, normal_use_acceptance='unproven',
                  required_observation_hours=args.required_hours,
                  scope='Read-only root-ADB checkpoint. No root toggle, reboot, setting, '
                        'permission, daemon, wakelock, media capture or partition write. '
                        'Private dumps may contain identifiers; report aggregates only.')

    def save():
        (args.output / 'observation.json').write_text(json.dumps(report, indent=2) + '\n')

    def shell(command):
        result = subprocess.run([args.adb, '-s', args.serial, 'shell', command],
                                capture_output=True, text=True, timeout=45)
        report['commands'].append(dict(command=command, exit_code=result.returncode,
                                       stderr=result.stderr))
        save()
        if result.returncode:
            raise ValueError('Read-only command failed: ' + command)
        return result.stdout.strip()

    try:
        report['identity'] = shell('id')
        if 'uid=0(root)' not in report['identity']:
            raise ValueError('Requires existing engineering root ADB; no automatic root toggle')
        report['device'] = shell('getprop ro.product.device')
        if report['device'] != 'RED8ACL1' or shell('getprop sys.boot_completed') != '1':
            raise ValueError('Expected booted RMX3301 Android')
        report['slot'] = shell('getprop ro.boot.slot_suffix')
        report['boot_id'] = shell('cat /proc/sys/kernel/random/boot_id')
        report['uptime'] = shell('cat /proc/uptime')
        report['build_incremental'] = shell('getprop ro.build.version.incremental')
        report['properties'] = {key: shell('getprop ' + key) for key in (
            'ro.boot.vbmeta.device_state', 'vendor.fingerprint.cali',
            'ro.crypto.state', 'ro.crypto.type', 'sys.user.0.ce_available')}
        report['selinux'] = shell('getenforce')
        for label, command in CAPTURES.items():
            text = shell(command)
            path = args.output / (label + '.txt')
            path.write_text(text + '\n')
            report['captures'][label] = dict(file=path.name, sha256=sha(path))
            if label == 'crash':
                report['fatal_patterns_present'] = bool(re.search(
                    r'Fatal signal|FATAL EXCEPTION|Abort message', text))
            if label == 'fingerprint':
                report['fingerprint_stats'] = next((json.loads(line) for line in
                    text.splitlines() if line.startswith('{"service":')), None)
                report['fingerprint_HAL_deaths_zero'] = 'HAL deaths since last reboot: 0' in text
            if label == 'suspend':
                report['suspend_stats'] = parse_suspend(text)
        if args.marker:
            if report['properties']['sys.user.0.ce_available'] == 'true':
                report['marker'] = dict(path=args.marker,
                    sha256=shell('sha256sum ' + shlex.quote(args.marker)).split()[0])
            else:
                report['marker'] = dict(path=args.marker, status='blocked: CE locked; no unlock attempted')
        if baseline is not None:
            report['baseline_sha256'] = sha(args.baseline)
            report['comparison'] = compare(baseline, report, args.required_hours)
            if baseline.get('marker', {}).get('sha256') and report.get('marker', {}).get('sha256'):
                report['marker_unchanged'] = baseline['marker'] == report['marker']
        report['observation_complete'] = True
    except Exception as error:
        report['error'] = repr(error)
        raise
    finally:
        report['tool_sha256'] = sha(Path(__file__))
        report['finished_utc'] = datetime.now(timezone.utc).isoformat()
        save()
    print(json.dumps({key: report.get(key) for key in (
        'observation_complete', 'boot_id', 'comparison', 'fatal_patterns_present',
        'fingerprint_HAL_deaths_zero')}))


if __name__ == '__main__':
    main()
