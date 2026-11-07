"""Whole-filesystem, file-level comparison of two ext4 images (persist). Read only.

An independent implementation of the C-07 comparison: it reads ext4 with dissect.extfs instead of
debugfs, walks EVERY directory (not only fingerprint/), counts regular files only (directories are not
files), and hashes each file's content.

Usage:
    python -I tools/review/persist_compare.py KIT.img FRESH.img [--only /fingerprint]
    python -I tools/review/persist_compare.py KIT.img --control

--control (rule G1): negative control = the image against itself must give 0 differences; positive
control = a copy with one byte flipped inside /fingerprint/gf_cali_0.so must give exactly that file.
The copy is written next to this script and deleted afterwards. The input image is never modified.

Requires dissect.extfs (pip install dissect.extfs). Written for
docs/CLAIMS_REMEDIATION_VALIDATION_2026-10-17.md.
"""
import hashlib
import os
import shutil
import sys

from dissect.extfs import ExtFS

S_IFMT, S_IFDIR, S_IFREG = 0o170000, 0o040000, 0o100000


def walk(fs):
    out, errors = {}, []
    stack = [('/', fs.get('/'))]
    while stack:
        path, node = stack.pop()
        try:
            entries = node.listdir()
        except Exception as e:
            errors.append((path, 'listdir', repr(e)))
            continue
        for name, child in entries.items():
            if name in ('.', '..'):
                continue
            p = path.rstrip('/') + '/' + name
            try:
                ft = child.filetype & S_IFMT
                if ft == S_IFDIR:
                    out[p] = ('dir', None, None)
                    stack.append((p, child))
                elif ft == S_IFREG:
                    data = child.open().read()
                    if len(data) != child.size:
                        errors.append((p, 'short read', '%d != %d' % (len(data), child.size)))
                    out[p] = ('file', child.size, hashlib.sha256(data).hexdigest())
                else:
                    out[p] = ('other', None, None)
            except Exception as e:
                errors.append((p, 'read', repr(e)))
    return out, errors


def compare(a_path, b_path, only=None, quiet=False):
    with open(a_path, 'rb') as fa, open(b_path, 'rb') as fb:
        a, ea = walk(ExtFS(fa))
        b, eb = walk(ExtFS(fb))
    if only:
        a = {k: v for k, v in a.items() if k.startswith(only + '/')}
        b = {k: v for k, v in b.items() if k.startswith(only + '/')}
    fa_ = {k: v for k, v in a.items() if v[0] == 'file'}
    fb_ = {k: v for k, v in b.items() if v[0] == 'file'}
    common = sorted(set(fa_) & set(fb_))
    same = [k for k in common if fa_[k][2] == fb_[k][2]]
    diff = [k for k in common if fa_[k][2] != fb_[k][2]]
    only_a = sorted(set(fa_) - set(fb_))
    only_b = sorted(set(fb_) - set(fa_))
    if not quiet:
        print('  A=%s' % a_path)
        print('  B=%s' % b_path)
        print('  scope=%s' % (only or 'whole filesystem'))
        print('  read errors A=%d B=%d' % (len(ea), len(eb)))
        for e in (ea + eb)[:10]:
            print('    ERR', e)
        print('  regular files A=%d B=%d  dirs A=%d B=%d' % (
            len(fa_), len(fb_), sum(v[0] == 'dir' for v in a.values()), sum(v[0] == 'dir' for v in b.values())))
        print('  common=%d identical=%d differing=%d only-in-A=%d only-in-B=%d' % (
            len(common), len(same), len(diff), len(only_a), len(only_b)))
        for k in diff:
            print('    DIFF %-60s A=%s(%s) B=%s(%s)' % (k, fa_[k][2][:12], fa_[k][1], fb_[k][2][:12], fb_[k][1]))
        for k in only_a:
            print('    ONLY-A %s (%s bytes)' % (k, fa_[k][1]))
        for k in only_b:
            print('    ONLY-B %s (%s bytes)' % (k, fb_[k][1]))
        print('  sample identical:', ', '.join(same[:5]))
    return dict(a=fa_, b=fb_, same=same, diff=diff, only_a=only_a, only_b=only_b, err=ea + eb)


def control(img, workdir):
    print('=== NEGATIVE CONTROL: image vs itself ===')
    r = compare(img, img, quiet=True)
    print('  files=%d differing=%d only=%d errors=%d' % (
        len(r['same']) + len(r['diff']), len(r['diff']), len(r['only_a']) + len(r['only_b']), len(r['err'])))
    neg_ok = not r['diff'] and not r['err'] and len(r['same']) > 0
    print('=== POSITIVE CONTROL: flip one byte in one file ===')
    target = '/fingerprint/gf_cali_0.so'
    with open(img, 'rb') as f:
        fs = ExtFS(f)
        node = fs.get(target)
        first_block = list(node.dataruns())[0][0]
        off = first_block * fs.block_size + 100
        print('  target=%s size=%d first block=%d byte offset=%d' % (target, node.size, first_block, off))
    copy = os.path.join(workdir, 'persist_control_copy.img')
    shutil.copyfile(img, copy)
    try:
        with open(copy, 'r+b') as f:
            f.seek(off)
            b = f.read(1)
            f.seek(off)
            f.write(bytes([b[0] ^ 0xFF]))
        r = compare(img, copy, quiet=True)
    finally:
        os.remove(copy)
    print('  differing=%d -> %s' % (len(r['diff']), r['diff']))
    pos_ok = r['diff'] == [target]
    print('  NEGATIVE CONTROL', 'PASS' if neg_ok else 'FAIL')
    print('  POSITIVE CONTROL', 'PASS' if pos_ok else 'FAIL')
    return neg_ok and pos_ok


if __name__ == '__main__':
    args = sys.argv[1:]
    if '--control' in args:
        args.remove('--control')
        sys.exit(0 if control(args[0], os.path.dirname(os.path.abspath(__file__))) else 1)
    only = None
    if '--only' in args:
        i = args.index('--only')
        only = args[i + 1]
        del args[i:i + 2]
    compare(args[0], args[1], only)
