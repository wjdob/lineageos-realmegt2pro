"""One read-only SSD collector/unit observation; the Windows caller schedules it."""
import argparse
from collections import deque
import json
import re
import subprocess
from storage_24 import STORE, verify_store


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True)
    args = parser.parse_args()
    if not re.fullmatch(r'candidate-[a-z0-9-]+', args.run):
        raise ValueError('invalid run name')
    verify_store()
    directory = STORE / 'records' / args.run
    result = directory / 'result.json'
    report = {'run': args.run, 'collector': json.loads(result.read_text()) if result.is_file() else None}
    log = directory / 'build.log'
    if log.is_file():
        with log.open(errors='replace') as stream:
            report['build_tail'] = list(deque(stream, maxlen=12))
    unit = subprocess.run(['systemctl','show','realme-next-' + args.run + '.service',
                           '--property=LoadState,ActiveState,SubState,Result,ExecMainStatus'],
                          text=True, capture_output=True)
    report['unit_query_exit_code'] = unit.returncode
    report['unit'] = dict(line.split('=',1) for line in unit.stdout.splitlines() if '=' in line)
    print(json.dumps(report))


if __name__ == '__main__':
    main()
