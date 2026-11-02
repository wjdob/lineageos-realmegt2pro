"""Check Ferrari's trusted-app reservation after applying its packaged DT overlay.

Read-only: never contacts a phone. Uses libfdt command-line tools, whose identities
are recorded, rather than treating the first FDT in vendor_boot as the whole DTB.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import zipfile

REPO = Path(__file__).resolve().parents[1]
MAGIC = b'\xd0\x0d\xfe\xed'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def call(*args):
    return subprocess.check_output(args, text=True, stderr=subprocess.PIPE, timeout=30).strip()


def cells(path, node, prop):
    return [int(v, 16) for v in call('fdtget', '-t', 'x', str(path), node, prop).split()]


def number(path, node, prop):
    result = 0
    values = cells(path, node, prop)
    if len(values) != 2:
        raise ValueError('expected two-cell ' + prop)
    for value in values:
        result = (result << 32) | value
    return result


def trees(data, scratch, prefix):
    """Validate every plausible FDT with libfdt, retaining distinct concatenated trees."""
    result = []
    offset = 0
    while True:
        offset = data.find(MAGIC, offset)
        if offset < 0:
            return result
        start = offset
        offset += 4
        if start + 40 > len(data):
            continue
        _, size, off_struct, off_strings, off_rsv, version, compat, _, size_strings, size_struct = struct.unpack_from('>10I', data, start)
        if not (40 <= size <= len(data)-start and version >= 16 and compat <= 17
                and 40 <= off_rsv < size and 40 <= off_struct <= size-size_struct
                and 40 <= off_strings <= size-size_strings):
            continue
        path = scratch / (prefix + '-' + str(start) + '.dtb')
        path.write_bytes(data[start:start+size])
        try:
            call('fdtget', '-l', str(path), '/')
            model = call('fdtget', '-t', 's', str(path), '/', 'model')
        except subprocess.CalledProcessError:
            continue
        result.append(dict(path=path, offset=start, size=size, model=model, sha256=sha(path.read_bytes())))


def check_images(vendor_boot, dtbo, contract, *, raw_dtb=False):
    expected_magic = MAGIC if raw_dtb else b'VNDRBOOT'
    if not vendor_boot.startswith(expected_magic) or dtbo[:4] != bytes.fromhex('d7b7ab1e'):
        raise ValueError('expected vendor_boot and Android DTBO images')
    report = dict(dtbo_sha256=sha(dtbo), effective_trees=[])
    report['dtb_sha256' if raw_dtb else 'vendor_boot_sha256'] = sha(vendor_boot)
    with tempfile.TemporaryDirectory(prefix='fingerprint-memory-', dir=REPO/'tmp') as directory:
        scratch = Path(directory)
        bases = trees(vendor_boot, scratch, 'base')
        overlays = trees(dtbo, scratch, 'overlay')
        selected = [t for t in overlays if 'ferrari' in t['model'].lower()]
        if len(selected) != 1 or cells(selected[0]['path'], '/', 'qcom,board-id') != contract['board_id']:
            raise ValueError('expected exactly one Ferrari board overlay')
        overlay = selected[0]
        report['overlay'] = {k:v for k,v in overlay.items() if k != 'path'}
        for base in bases:
            ids = cells(base['path'], '/', 'qcom,msm-id')
            if not ids or ids[0] not in contract['soc_ids']:
                continue
            merged = scratch / ('merged-' + str(base['offset']) + '.dtb')
            call('fdtoverlay', '-i', str(base['path']), '-o', str(merged), str(overlay['path']))
            node = '/reserved-memory/qseecom_ta_region'
            actual = number(merged, node, 'size')
            if actual != contract['ta_bytes']:
                raise ValueError('trusted-app pool is %d bytes; expected %d' % (actual, contract['ta_bytes']))
            if number(merged, node, 'alignment') != contract['alignment_bytes']:
                raise ValueError('trusted-app alignment differs')
            if cells(merged, node, 'alloc-ranges') != contract['alloc_ranges']:
                raise ValueError('trusted-app allocation range differs')
            if call('fdtget', '-t', 's', str(merged), node, 'compatible') != 'shared-dma-pool':
                raise ValueError('trusted-app pool type differs')
            call('fdtget', str(merged), node, 'reusable')
            if number(merged, '/reserved-memory/qseecom_region', 'size') != contract['qseecom_bytes']:
                raise ValueError('unrelated qseecom reservation changed')
            phandle = cells(merged, node, 'phandle')
            if cells(merged, '/soc/qseecom@c1700000', 'qseecom_ta_mem') != phandle:
                raise ValueError('QSEE driver references another pool')
            if cells(merged, '/soc/qcom,dma-heaps/qcom,qseecom_ta', 'memory-region') != phandle:
                raise ValueError('DMA heap references another pool')
            report['effective_trees'].append(dict(base_sha256=base['sha256'], model=base['model'], soc_ids=ids,
                merged_sha256=sha(merged.read_bytes()), ta_bytes=actual))
        if len(report['effective_trees']) != contract['expected_base_trees']:
            raise ValueError('unexpected number of Ferrari-compatible base trees')
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--contract', type=Path, default=REPO/'configs/fingerprint-memory-23.2.json')
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument('--source-tree', type=Path)
    mode.add_argument('--target-files', type=Path)
    mode.add_argument('--vendor-boot', type=Path)
    mode.add_argument('--dtb-image', type=Path)
    p.add_argument('--dtbo', type=Path)
    p.add_argument('--report', required=True, type=Path)
    args = p.parse_args()
    c = json.loads(args.contract.read_text())
    report = dict(passed=False, contract_sha256=sha(args.contract.read_bytes()), limit=c['limit'])
    try:
        if args.source_tree:
            path = args.source_tree / c['source']
            if sha(path.read_bytes()) != c['source_sha256']:
                raise ValueError('unreviewed Ferrari overlay source')
            report['source_sha256'] = c['source_sha256']
        else:
            report['tools'] = {name:sha(Path(shutil.which(name)).read_bytes()) for name in ('fdtget','fdtoverlay')}
            if args.target_files:
                with zipfile.ZipFile(args.target_files) as z:
                    vendor_boot, dtbo = (z.read('IMAGES/'+name+'.img') for name in ('vendor_boot','dtbo'))
                report['target_files_sha256'] = hashlib.file_digest(args.target_files.open('rb'), 'sha256').hexdigest()
            else:
                if not args.dtbo:
                    raise ValueError('--dtbo required with --vendor-boot')
                vendor_boot, dtbo = (args.dtb_image or args.vendor_boot).read_bytes(), args.dtbo.read_bytes()
            report.update(check_images(vendor_boot, dtbo, c, raw_dtb=bool(args.dtb_image)))
        report['passed'] = True
    except Exception as error:
        report['error'] = str(error)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
