"""Read-only WSL/ADB partition capture; streams directly to private host storage.

Never stages files on the phone. A verified capture is not a restore procedure.
"""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import select
import shlex
import shutil
import subprocess
import sys
import time

STREAM_CHUNK_BYTES = 64 * 1024


def copy_chunks(chunks, target, expected, reserve, free):
    digest, count = hashlib.sha256(), 0
    for chunk in chunks:
        if free() < reserve + len(chunk):
            raise ValueError('physical storage reserve reached')
        count += len(chunk)
        if count > expected:
            raise ValueError('capture exceeds measured partition size')
        target.write(chunk)
        digest.update(chunk)
    if count != expected:
        raise ValueError('truncated capture')
    return digest.hexdigest()


def matching_hashes(before, captured, after):
    if not all(re.fullmatch('[a-f0-9]{64}', x) for x in (before, captured, after)):
        raise ValueError('invalid source/capture hash')
    if len({before, captured, after}) != 1:
        raise ValueError('source changed or capture hash differs')


class Device:
    def __init__(self, adb, serial):
        self.command = [str(adb), '-s', serial]

    def shell(self, command, root=False, timeout=180):
        if root:
            command = 'su -c ' + shlex.quote(command)
        result = subprocess.run(self.command + ['shell', command], capture_output=True,
                                timeout=timeout, check=True)
        return result.stdout.decode().strip()

    def identity(self):
        return {key: self.shell('getprop ' + key) for key in
                ('ro.product.model', 'ro.product.device', 'ro.boot.slot_suffix',
                 'ro.build.display.id', 'ro.build.oplus_nv_id')}

    def snapshot(self):
        value = self.shell('snapshotctl dump', root=True)
        if not re.search(r'^Update state: none\s*$', value, re.MULTILINE):
            raise ValueError('snapshot state is not confirmed none')
        return value

    def describe(self, name):
        if not re.fullmatch('[A-Za-z0-9_]+', name) or name == 'userdata':
            raise ValueError('invalid or excluded partition name')
        path = '/dev/block/by-name/' + name
        resolved = self.shell('readlink -f ' + path, root=True)
        if not resolved.startswith('/dev/block/'):
            raise ValueError('partition path did not resolve to a block device')
        size = int(self.shell('blockdev --getsize64 ' + path, root=True))
        if size <= 0:
            raise ValueError('invalid partition size')
        return {'partition': name, 'device_path': path, 'resolved_path': resolved, 'bytes': size}

    def hash(self, path):
        return self.shell('sha256sum ' + path, root=True, timeout=600).split()[0]

    def chunks(self, path, stderr, timeout=1800):
        command = 'su -c ' + shlex.quote('cat ' + path)
        process = subprocess.Popen(self.command + ['exec-out', command], stdout=subprocess.PIPE, stderr=stderr)
        deadline = time.monotonic() + timeout
        try:
            while True:
                if time.monotonic() >= deadline:
                    raise TimeoutError('ADB stream timed out')
                if not select.select([process.stdout], [], [], 1)[0]:
                    continue
                data = os.read(process.stdout.fileno(), STREAM_CHUNK_BYTES)
                if not data:
                    break
                yield data
            if process.wait(timeout=10):
                raise ValueError('ADB stream exited nonzero')
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()
            process.stdout.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--adb', type=Path, required=True)
    parser.add_argument('--serial', required=True)
    parser.add_argument('--partitions', required=True, help='explicit comma-separated by-name IDs')
    parser.add_argument('--output', type=Path, required=True, help='new private host directory')
    parser.add_argument('--plan-only', action='store_true')
    args = parser.parse_args()
    if os.name != 'posix':
        raise ValueError('run with WSL Python; streaming uses POSIX pipe polling')
    names = args.partitions.split(',')
    if not names or len(names) != len(set(names)):
        raise ValueError('empty or duplicate partition list')
    device = Device(args.adb, args.serial)
    identity = device.identity()
    if identity['ro.product.model'] != 'RMX3301' or identity['ro.product.device'] != 'RED8ACL1':
        raise ValueError('unexpected device identity')
    snapshot = device.snapshot()
    plan = [device.describe(name) for name in names]
    reserve = 20 * 1024**3
    report = {'schema': 1, 'purpose': 'capture-integrity-inventory',
              'observed_utc': datetime.now(timezone.utc).isoformat(),
              'serial': args.serial, 'identity': identity, 'snapshot_before': snapshot,
              'python': sys.version, 'tool_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'required_bytes': sum(row['bytes'] for row in plan),
              'reserve_bytes': reserve, 'plan': plan, 'captures': [], 'complete': False}
    if args.plan_only:
        print(json.dumps(report, indent=2))
        return 0
    output = args.output.absolute()
    if output.exists() or output.is_symlink():
        raise ValueError('output directory must be new')
    output.parent.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(output.parent).free < reserve + report['required_bytes']:
        raise ValueError('insufficient space for complete capture plus reserve')
    output.mkdir(mode=0o700)
    record = output / 'catalog.json'
    record.write_text(json.dumps(report, indent=2)+'\n')
    try:
        for row in plan:
            before = device.hash(row['device_path'])
            report['active_partition'] = {'partition': row['partition'], 'source_sha256_before': before}
            record.write_text(json.dumps(report, indent=2)+'\n')
            partial = output / (row['partition'] + '.img.partial')
            with partial.open('xb') as target, (output/(row['partition']+'.stderr.log')).open('xb') as stderr:
                with closing(device.chunks(row['device_path'], stderr)) as chunks:
                    captured = copy_chunks(chunks, target, row['bytes'], reserve,
                                           lambda: shutil.disk_usage(output).free)
                target.flush()
                os.fsync(target.fileno())
            after = device.hash(row['device_path'])
            matching_hashes(before, captured, after)
            if device.describe(row['partition']) != row:
                raise ValueError('partition path or size changed')
            # Re-read the stored file; stream hashing alone does not check persisted bytes.
            with partial.open('rb') as stream:
                stored = hashlib.file_digest(stream, 'sha256').hexdigest()
            matching_hashes(before, stored, after)
            final = output / (row['partition'] + '.img')
            partial.rename(final)
            report['captures'].append({'file': final.name, 'partition': row['partition'],
                'bytes': row['bytes'], 'sha256': stored, 'device_sha256_before': before,
                'device_sha256_after': after, 'provenance': 'fresh-device-hash-verified',
                'observed_utc': datetime.now(timezone.utc).isoformat()})
            report.pop('active_partition', None)
            record.write_text(json.dumps(report, indent=2)+'\n')
            print('Verified '+row['partition'], flush=True)
        report['snapshot_after'] = device.snapshot()
        if device.identity() != identity:
            raise ValueError('device identity/build/slot changed during capture')
        report['complete'] = True
    except Exception as error:
        report['error'] = str(error)
    finally:
        record.write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps({'complete': report['complete'], 'captures': len(report['captures']),
                      'error': report.get('error'), 'catalog': str(record)}))
    return 0 if report['complete'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
