"""Bounded host-only ADB log capture, including reconnects; never requests a reboot."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import time

REPO = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--adb', required=True)
    parser.add_argument('--serial', required=True)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--seconds', type=int, default=180)
    args = parser.parse_args()
    if not 1 <= args.seconds <= 900:
        parser.error('--seconds must be 1..900')
    output = args.output.absolute()
    if output.is_symlink() or any(p.is_symlink() for p in output.parents):
        parser.error('output must not traverse symlinks')
    if not output.resolve().is_relative_to((REPO / '.local').resolve()):
        parser.error('private logs must stay under workspace .local')
    output.mkdir(parents=True, exist_ok=False)
    adb = [args.adb, '-s', args.serial]
    report = {'started_utc': datetime.now(timezone.utc).isoformat(),
              'serial': args.serial, 'seconds': args.seconds, 'segments': [],
              'scope': 'Read-only logcat and boot identity; no root request, reboot, '
                       'service restart, log clearing, device file or partition write.'}
    deadline = time.monotonic() + args.seconds
    process = None
    streams = []
    limit = 32 * 1024 * 1024
    try:
        while time.monotonic() < deadline:
            if process is None or process.poll() is not None:
                if process is not None:
                    report['segments'][-1]['exit_code'] = process.returncode
                    for stream in streams:
                        stream.close()
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                try:
                    identity = subprocess.run(adb + ['shell', 'cat',
                        '/proc/sys/kernel/random/boot_id'], capture_output=True,
                        timeout=min(3, remaining))
                except subprocess.TimeoutExpired:
                    continue
                if identity.returncode:
                    time.sleep(min(.5, max(0, deadline - time.monotonic())))
                    continue
                index = len(report['segments'])
                name = f'logcat-{index:03d}.txt'
                streams = [(output / name).open('xb'),
                           (output / f'logcat-{index:03d}.stderr').open('xb')]
                report['segments'].append({'boot_id': identity.stdout.decode().strip(),
                    'file': name, 'started_utc': datetime.now(timezone.utc).isoformat()})
                process = subprocess.Popen(adb + ['logcat', '-b', 'all', '-v', 'threadtime'],
                                           stdout=streams[0], stderr=streams[1])
            if sum(p.stat().st_size for p in output.iterdir() if p.is_file()) >= limit:
                report['stop_reason'] = '32-MiB capture limit'
                break
            time.sleep(min(.25, max(0, deadline - time.monotonic())))
    finally:
        if process is not None:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
            report['segments'][-1]['exit_code'] = process.returncode
        for stream in streams:
            stream.close()
        report['finished_utc'] = datetime.now(timezone.utc).isoformat()
        report['artifacts'] = [{'name': p.name, 'bytes': p.stat().st_size,
            'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
            for p in sorted(output.iterdir()) if p.is_file()]
        (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'segments': len(report['segments']), 'output': str(output)}))
    return 0 if report['segments'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
