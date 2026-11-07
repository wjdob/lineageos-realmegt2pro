"""Read-only window/input/activity snapshot for a UI failure; keep output private."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess

REPO = Path(__file__).resolve().parents[2]
QUERIES = {
    'boot': ['shell', 'cat', '/proc/sys/kernel/random/boot_id'],
    'window': ['shell', 'dumpsys', 'window', 'windows'],
    'input': ['shell', 'dumpsys', 'input'],
    'activities': ['shell', 'dumpsys', 'activity', 'activities'],
    'last-anr': ['shell', 'dumpsys', 'activity', 'lastanr'],
    'overlays': ['shell', 'cmd', 'overlay', 'list'],
    'power': ['shell', 'dumpsys', 'power'],
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--adb', required=True)
    parser.add_argument('--serial', required=True)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    output = args.output.absolute()
    if (any(p.is_symlink() for p in [output, *output.parents]) or
            not output.resolve().is_relative_to((REPO / '.local').resolve())):
        parser.error('output must be a new private directory under workspace .local')
    output.mkdir(parents=True, exist_ok=False)
    report = {'started_utc': datetime.now(timezone.utc).isoformat(),
              'serial': args.serial, 'commands': {},
              'scope': 'Read-only snapshots, sequential rather than atomic. No credential '
                       'entry, unlock, root request, UI input, service restart or device write.'}
    for name, query in QUERIES.items():
        command = [args.adb, '-s', args.serial, *query]
        entry = {'command': command, 'started_utc': datetime.now(timezone.utc).isoformat()}
        try:
            process = subprocess.run(command, capture_output=True, timeout=8)
            stdout, stderr = process.stdout, process.stderr
            entry['exit_code'] = process.returncode
        except subprocess.TimeoutExpired as error:
            stdout, stderr = error.stdout or b'', error.stderr or b''
            entry['timeout'] = True
        for suffix, data in [('stdout', stdout), ('stderr', stderr)]:
            path = output / (name + '.' + suffix)
            path.write_bytes(data)
            entry[suffix] = {'file': path.name, 'bytes': len(data),
                             'sha256': hashlib.sha256(data).hexdigest()}
        report['commands'][name] = entry
    report['finished_utc'] = datetime.now(timezone.utc).isoformat()
    report['all_commands_pass'] = all(x.get('exit_code') == 0 for x in report['commands'].values())
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'all_commands_pass': report['all_commands_pass'], 'output': str(output)}))
    return 0 if report['all_commands_pass'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
