"""Read-only, gzip-streamed pre-upgrade captures. Never restores or writes a device.

Quiet mode requires recovery, no mounted userdata/metadata and no pending OTA.
Probe mode reads only the current boot partition while Android is running.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess
import threading
import time
import zlib

BOOT_STACK = ('boot', 'dtbo', 'recovery', 'vendor_boot', 'vbmeta', 'vbmeta_system', 'vbmeta_vendor')
QUIET_PARTITIONS = ('userdata', 'metadata', 'super') + tuple(p+'_'+s for s in ('a', 'b') for p in BOOT_STACK)


def selected_partitions(mode, os_metadata_only=False):
    if os_metadata_only and mode != 'quiet':
        raise ValueError('OS/metadata component capture requires quiet recovery')
    if mode == 'quiet':
        return QUIET_PARTITIONS[1:] if os_metadata_only else QUIET_PARTITIONS
    return None  # Probe selects only the explicit current boot slot.


def require_quiet_mounts(text):
    os_mounts = {'/', '/system', '/system_root', '/product', '/system_ext', '/vendor', '/odm', '/vendor_dlkm'}
    for line in text.splitlines():
        fields = line.split()
        if len(fields) < 4:
            continue
        source, point, _, options = fields[:4]
        if any(point == p or point.startswith(p+'/') for p in ('/data','/metadata','/mnt/userdata')):
            raise ValueError('userdata and metadata must be unmounted before capture')
        if point in os_mounts and source.startswith('/dev/block/') and 'rw' in options.split(','):
            raise ValueError('OS filesystem is mounted writable during quiet capture')


def validate_quiet_snapshot_evidence(evidence, *, serial, build, slot, boot_id, metadata_sha, message):
    """Bind offline-empty libsnapshot state to fresh metadata and misc bytes.

    AOSP bootloader_message_core.h:64-byte packed Virtual A/B record at32KiB;
    version2, magic0x56740ab0, IBootControl MergeStatus.NONE=0. The selected
    libsnapshot proto defines an empty SnapshotUpdateStatus as UpdateState.None.
    This profile accepts only the exact empty, clean metadata state inspected
    off-device. It provides no device-write or restore capability.
    """
    if evidence.get('purpose') != 'quiet-recovery-vab-evidence':
        raise ValueError('reviewed quiet snapshot evidence required')
    expected = dict(serial=serial, build=build, slot=slot, boot_id=boot_id, metadata_sha256=metadata_sha,
                    metadata_state_bytes=0, metadata_state_sha256=hashlib.sha256(b'').hexdigest(),
                    metadata_filesystem_clean=True)
    if any(evidence.get(key) != value for key, value in expected.items()):
        raise ValueError('quiet snapshot evidence differs from current device/boot/metadata')
    if len(message) != 64 or message[0] != 2 or struct.unpack_from('<I', message, 1)[0] != 0x56740ab0:
        raise ValueError('unsupported Virtual A/B message')
    if message[5] != 0 or message[6] != {'a':0, 'b':1}[slot]:
        raise ValueError('Virtual A/B merge/source state is not the reviewed NONE state')
    if hashlib.sha256(message).hexdigest() != evidence.get('misc_message_sha256'):
        raise ValueError('Virtual A/B message changed')
    return dict(method='exact-empty-metadata-plus-live-virtual-ab-message', merge_status=0,
                source_slot=message[6], metadata_sha256=metadata_sha)


class GzipMeasurement:
    """Bound decompression memory, count all expanded bytes and reject truncation."""
    def __init__(self, expected):
        if not isinstance(expected, int) or expected <= 0:
            raise ValueError('positive exact source size required')
        self.expected = expected
        self.bytes = 0
        self.digest = hashlib.sha256()
        self.decoder = zlib.decompressobj(31)

    def feed(self, data):
        while data:
            expanded = self.decoder.decompress(data, 8*1024*1024)
            self.bytes += len(expanded)
            if self.bytes > self.expected:
                raise ValueError('expanded capture exceeds source size')
            self.digest.update(expanded)
            if self.decoder.unused_data:
                raise ValueError('trailing data or multiple gzip members')
            data = self.decoder.unconsumed_tail

    def finish(self):
        if not self.decoder.eof or self.bytes != self.expected:
            raise ValueError('truncated or incorrectly sized capture')
        return self.digest.hexdigest()


def capture(adb, serial, partition, destination, expected_bytes, expected_sha, floor, timeout):
    if partition not in QUIET_PARTITIONS:
        raise ValueError('unreviewed capture partition')
    partial = destination.with_suffix(destination.suffix+'.partial')
    if destination.exists() or partial.exists():
        raise ValueError('capture destination already exists')
    measurement = GzipMeasurement(expected_bytes)
    compressed = hashlib.sha256()
    started = time.monotonic()
    last_progress = started
    stderr = partial.with_suffix(partial.suffix+'.stderr')
    with stderr.open('xb') as errors, partial.open('xb') as output:
        command = [str(adb), '-s', serial, 'exec-out', 'gzip -1 -c /dev/block/by-name/'+partition]
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=errors)
        watchdog = threading.Timer(timeout, process.kill)
        watchdog.start()
        try:
            while True:
                data = process.stdout.read(1024*1024)
                if not data:
                    break
                if shutil.disk_usage(destination.parent).free < floor + len(data):
                    raise ValueError('host free-space floor reached')
                measurement.feed(data)
                output.write(data)
                compressed.update(data)
                if time.monotonic()-last_progress >= 60:
                    print(json.dumps(dict(partition=partition, phase='stream', source_bytes_read=measurement.bytes,
                        source_bytes=expected_bytes, stored_bytes=output.tell(), elapsed_seconds=round(time.monotonic()-started))), flush=True)
                    last_progress = time.monotonic()
            if process.wait() != 0:
                raise ValueError('read/compression transport failed; preserve partial capture and stderr')
            digest = measurement.finish()
            if digest != expected_sha:
                raise ValueError('expanded capture hash differs from quiet source')
        finally:
            watchdog.cancel()
            process.stdout.close()
            if process.poll() is None:
                process.kill()
                process.wait()
    # Re-read the stored gzip to verify disk bytes and CRC, not just the pipe.
    measured = GzipMeasurement(expected_bytes)
    stored = hashlib.sha256()
    with partial.open('rb') as stream:
        for data in iter(lambda: stream.read(1024*1024), b''):
            measured.feed(data)
            stored.update(data)
    if measured.finish() != expected_sha or stored.hexdigest() != compressed.hexdigest():
        raise ValueError('stored capture does not match stream/source')
    partial.rename(destination)
    return dict(partition=partition, source_bytes=expected_bytes, source_sha256=expected_sha,
        file=destination.name, stored_bytes=destination.stat().st_size, stored_sha256=stored.hexdigest(),
        elapsed_seconds=round(time.monotonic()-started, 3))


def run(args):
    if not re.fullmatch(r'[A-Za-z0-9]+', args.serial) or not re.fullmatch(r'[A-Za-z0-9._-]+', args.build):
        raise ValueError('explicit safe device/build identity required')
    selected = selected_partitions(args.mode, args.os_metadata_only)
    output = args.output.resolve()
    if not output.is_absolute() or output.exists():
        raise ValueError('new absolute private output directory required')
    output.mkdir(parents=True)
    record = dict(observed_utc=datetime.now(timezone.utc).isoformat(), mode=args.mode,
        serial=args.serial, expected_incremental=args.build, expected_slot=args.slot,
        tool_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        complete=False, commands=[], captures=[],
        capture_scope='os-and-metadata-components' if args.os_metadata_only else 'full-quiet' if args.mode == 'quiet' else 'boot-probe',
        limits='Read-only sequential image captures, no restore or userdata rollback guarantee. Hardware-backed key/credential state cannot be snapshotted by these files. Probe mode is not a complete backup.')

    def save():
        (output/'capture.json').write_text(json.dumps(record, indent=2)+'\n')

    def read(command, optional=False):
        result = subprocess.run([str(args.adb), '-s', args.serial, 'shell', command], capture_output=True, text=True, timeout=1800)
        record['commands'].append(dict(command=command, exit_code=result.returncode, stdout=result.stdout.strip(), stderr=result.stderr.strip()))
        if result.returncode and not optional:
            raise ValueError('read-only command failed: '+command)
        return result.stdout.strip()

    def state():
        if 'uid=0(root)' not in read('id') or read('getprop ro.product.model') != 'RMX3301':
            raise ValueError('expected rooted RMX3301 absent')
        if read('getprop ro.product.device') != 'RED8ACL1' or read('getprop ro.boot.slot_suffix') != '_'+args.slot:
            raise ValueError('device or slot changed')
        if read('getprop ro.build.version.incremental') != args.build:
            raise ValueError('expected23b source build changed')
        if read('getprop ro.boot.vbmeta.device_state') != 'unlocked':
            raise ValueError('expected unlocked state absent')
        boot_id = read('cat /proc/sys/kernel/random/boot_id')
        if 'boot_id' in record and record['boot_id'] != boot_id:
            raise ValueError('device rebooted during capture')
        record['boot_id'] = boot_id
        if args.mode == 'quiet' and args.quiet_snapshot_evidence is not None:
            evidence = json.loads(args.quiet_snapshot_evidence.read_text(encoding='utf-8-sig'))
            metadata_sha = read('sha256sum /dev/block/by-name/metadata').split()[0]
            # ADB exec-out merges remote stderr into stdout on this recovery.
            # Suppress dd's transfer statistics; exact length and digest still fail closed.
            command = 'dd if=/dev/block/by-name/misc bs=4096 skip=8 count=1 2>/dev/null'
            process = subprocess.run([str(args.adb), '-s', args.serial, 'exec-out', command], capture_output=True, timeout=30)
            if process.returncode != 0 or len(process.stdout) != 4096:
                raise ValueError('Virtual A/B record read failed')
            record['snapshot_check'] = validate_quiet_snapshot_evidence(evidence, serial=args.serial, build=args.build,
                slot=args.slot, boot_id=boot_id, metadata_sha=metadata_sha, message=process.stdout[:64])
            record['snapshot_evidence_sha256'] = hashlib.sha256(args.quiet_snapshot_evidence.read_bytes()).hexdigest()
        elif not re.search(r'^Update state: none$', read('snapshotctl dump'), re.M):
            raise ValueError('OTA snapshot state is not NONE')
        if args.mode == 'quiet':
            if not read('pidof recovery', optional=True) or read('pidof system_server', optional=True):
                raise ValueError('quiet recovery required')
            if read('pidof update_engine_sideload', optional=True):
                raise ValueError('active sideload process prevents quiet capture')
            require_quiet_mounts(read('cat /proc/mounts'))
        elif read('getprop sys.boot_completed') != '1':
            raise ValueError('Android probe requires completed boot')

    try:
        state()
        parts = selected if selected is not None else ('boot_'+args.slot,)
        plan = []
        for partition in parts:
            source = '/dev/block/by-name/'+partition
            resolved = read('readlink -f '+source)
            if not re.fullmatch(r'/dev/block/(?:sd[a-z]\d+|mmcblk\d+p\d+)', resolved):
                raise ValueError('unexpected physical source: '+partition)
            size = int(read('blockdev --getsize64 '+source))
            plan.append(dict(partition=partition, resolved_source=resolved, bytes=size))
        record['plan'] = plan
        # Compression savings are not assumed when reserving host headroom.
        raw_bytes = sum(p['bytes'] for p in plan)
        required = raw_bytes + (raw_bytes+99)//100 + len(plan)*1024*1024 + args.min_free_gib*1024**3
        if shutil.disk_usage(output).free < required:
            raise ValueError('insufficient host space for worst-case capture plus reserve')
        save()
        for row in plan:
            state()
            source = '/dev/block/by-name/'+row['partition']
            record['phase'] = 'hash-before:'+row['partition']
            save()
            print(json.dumps(dict(partition=row['partition'], phase='hash-before', source_bytes=row['bytes'])), flush=True)
            before = read('sha256sum '+source).split()[0]
            if not re.fullmatch('[a-f0-9]{64}', before):
                raise ValueError('invalid source digest')
            record['phase'] = 'stream:'+row['partition']
            save()
            item = capture(args.adb, args.serial, row['partition'], output/(row['partition']+'.img.gz'),
                row['bytes'], before, args.min_free_gib*1024**3, args.timeout)
            record['phase'] = 'hash-after:'+row['partition']
            save()
            after = read('sha256sum '+source).split()[0]
            if after != before:
                raise ValueError('source changed during capture')
            item['source_after_sha256'] = after
            record['captures'].append(item)
            save()
            print(json.dumps(dict(partition=row['partition'], stored_bytes=item['stored_bytes'], source_bytes=row['bytes'], verified=True)), flush=True)
        state()
        # A component capture never claims a complete pre-upgrade state.
        record['complete'] = not args.os_metadata_only
        record['components_complete'] = args.os_metadata_only
        record['phase'] = 'components-complete' if args.os_metadata_only else 'complete'
        record['finished_utc'] = datetime.now(timezone.utc).isoformat()
    finally:
        save()
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--adb', type=Path, required=True)
    parser.add_argument('--serial', required=True)
    parser.add_argument('--build', required=True)
    parser.add_argument('--slot', choices=('a','b'), required=True)
    parser.add_argument('--mode', choices=('probe','quiet'), required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--min-free-gib', type=int, default=20)
    parser.add_argument('--timeout', type=int, default=21600)
    parser.add_argument('--quiet-snapshot-evidence', type=Path,
                        help='Exact read-only metadata/misc evidence when recovery lacks snapshotctl; no skipped state check')
    parser.add_argument('--os-metadata-only', action='store_true',
                        help='Capture16 OS/metadata components without userdata; complete stays false. For reviewed composition with an independently verified userdata image only.')
    args = parser.parse_args()
    if args.min_free_gib < 20 or args.timeout <= 0:
        parser.error('at least20GiB reserve and a positive per-image timeout required')
    return run(args)


if __name__ == '__main__':
    raise SystemExit(main())
