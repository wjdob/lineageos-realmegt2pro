"""Prepare one verified backup as an Android sparse PC file. No device access.

Zero ranges use explicit FILL chunks, never DONT_CARE. A sparse hole that reads
as zero on a PC would otherwise leave older bytes on a flashed partition.
This is file preparation only, not approval or support for a device restore.
"""
import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sparse_hash import image_hash
from device.backup_upgrade_state import QUIET_PARTITIONS

BLOCK = 4096
CHUNK = 1024 * 1024
FLOOR = 20 * 1024**3


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def selected_capture(record, partition, serial, build):
    if (record.get('complete') is not True or record.get('phase') != 'complete'
            or record.get('mode') != 'quiet'):
        raise ValueError('completed quiet backup required')
    if record.get('serial') != serial or record.get('expected_incremental') != build:
        raise ValueError('backup device/build differs from reviewed source')
    captures = record.get('captures', [])
    names = [row.get('partition') for row in captures]
    if len(names) != len(QUIET_PARTITIONS) or set(names) != set(QUIET_PARTITIONS):
        raise ValueError('full quiet capture coverage required')
    if partition not in QUIET_PARTITIONS:
        raise ValueError('partition is outside the saved OS/data set')
    row = next(row for row in captures if row['partition'] == partition)
    if row.get('file') != partition+'.img.gz':
        raise ValueError('unexpected capture filename')
    size = row.get('source_bytes')
    if type(size) is not int or size <= 0 or size % BLOCK or size // BLOCK > 0xffffffff:
        raise ValueError('unsupported exact source size')
    for key in ('source_sha256', 'source_after_sha256', 'stored_sha256'):
        if not re.fullmatch('[a-f0-9]{64}', row.get(key, '')):
            raise ValueError('exact capture digests required')
    if row['source_sha256'] != row['source_after_sha256']:
        raise ValueError('quiet source changed')
    if type(row.get('stored_bytes')) is not int or row['stored_bytes'] <= 0:
        raise ValueError('exact stored size required')
    return row


def write_sparse(source, output, size, expected_sha, *, check_space=None):
    """Bounded conversion of gzip to RAW/FILL chunks with all source bytes defined."""
    digest = hashlib.sha256()
    expanded = chunks = 0
    zero = bytes(CHUNK)
    output.write(bytes(28))
    with gzip.GzipFile(fileobj=source, mode='rb') as stream:
        while expanded < size:
            data = stream.read(min(CHUNK, size-expanded))
            if not data or len(data) % BLOCK:
                raise ValueError('truncated or unaligned gzip output')
            if check_space is not None:
                check_space(len(data)+12)
            digest.update(data)
            expanded += len(data)
            if data == zero[:len(data)]:
                output.write(struct.pack('<2H2I', 0xCAC2, 0, len(data)//BLOCK, 16))
                output.write(bytes(4))
            else:
                output.write(struct.pack('<2H2I', 0xCAC1, 0, len(data)//BLOCK, 12+len(data)))
                output.write(data)
            chunks += 1
        if stream.read(1):
            raise ValueError('gzip output exceeds exact source size')
    if digest.hexdigest() != expected_sha:
        raise ValueError('expanded backup differs from quiet source digest')
    output.seek(0)
    output.write(struct.pack('<I4H4I', 0xed26ff3a, 1, 0, 28, 12, BLOCK, size//BLOCK, chunks, 0))
    output.seek(0, os.SEEK_END)
    return dict(source_bytes=expanded, source_sha256=digest.hexdigest(), sparse_chunks=chunks,
                chunk_types=['RAW', 'FILL'], dont_care_chunks=0)


def prepare(capture_path, partition, serial, build, destination):
    record = json.loads(capture_path.read_text(encoding='utf-8-sig'))
    row = selected_capture(record, partition, serial, build)
    root = capture_path.parent.resolve()
    source = root/row['file']
    if source.is_symlink() or source.resolve().parent != root or not source.is_file():
        raise ValueError('capture must be a regular file inside its backup directory')
    if source.stat().st_size != row['stored_bytes'] or sha(source) != row['stored_sha256']:
        raise ValueError('stored backup size/hash mismatch')
    if not destination.is_absolute():
        raise ValueError('new absolute PC destination required')
    destination = destination.resolve()
    partial = destination.with_suffix(destination.suffix+'.partial')
    receipt = destination.with_suffix(destination.suffix+'.json')
    if any(p.exists() for p in (destination,partial,receipt)):
        raise ValueError('restore preparation output already exists')
    destination.parent.mkdir(parents=True,exist_ok=True)
    def space(next_bytes):
        if shutil.disk_usage(destination.parent).free < FLOOR+next_bytes:
            raise ValueError('PC free-space floor reached; partial is not usable')
    space(CHUNK)
    report = dict(observed_utc=datetime.now(timezone.utc).isoformat(),complete=False,
        purpose='host-only-restore-file-preparation',partition=partition,
        serial=serial,source_build=build,source_slot=record['expected_slot'],
        source_boot_id=record['boot_id'],capture_receipt_sha256=sha(capture_path),
        tool_sha256=sha(Path(__file__)),source_compressed_sha256=row['stored_sha256'],
        paired_data_hashes={item['partition']:item['source_sha256'] for item in record['captures']
            if item['partition'] in ('userdata','metadata')},
        limits='PC file preparation only. No device access, restore approval, transport qualification or hardware-key rollback guarantee. Restore requires its own reviewed guard/normal-fastboot route and full readback.')
    try:
        with source.open('rb') as src, partial.open('xb') as output:
            report.update(write_sparse(src,output,row['source_bytes'],row['source_sha256'],check_space=space))
            output.flush()
            os.fsync(output.fileno())
        with partial.open('rb') as stream:
            checked=image_hash(stream,row['source_bytes'])
        if not checked['sparse'] or checked['sha256'] != row['source_sha256']:
            raise ValueError('independent sparse readback differs from saved source')
        report.update(stored_bytes=partial.stat().st_size,stored_sha256=sha(partial))
        partial.rename(destination)
        report.update(complete=True,file=str(destination))
    finally:
        with receipt.open('x',encoding='utf-8') as output:
            json.dump(report,output,indent=2)
            output.write('\n')
            output.flush()
            os.fsync(output.fileno())
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture',type=Path,required=True)
    parser.add_argument('--partition',choices=QUIET_PARTITIONS,required=True)
    parser.add_argument('--serial',required=True)
    parser.add_argument('--build',required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(prepare(args.capture,args.partition,args.serial,args.build,args.output),indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
