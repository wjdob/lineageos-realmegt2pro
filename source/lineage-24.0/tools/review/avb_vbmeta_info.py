"""Minimal AVB vbmeta parser. Read only.

Prints algorithm, flags, rollback index, public-key digests and every descriptor
(hash / hashtree / chain / property) for vbmeta images, so it can be seen which
partitions a vbmeta attests directly and which it only chains to.

Usage:
    python -I tools/review/avb_vbmeta_info.py <dir> <image> [<image> ...]

Written for the 2026-10-17 claims review (docs/CLAIMS_REVIEW_2026-10-17.md).
"""
import hashlib
import os
import struct
import sys

ALG = {0: 'NONE', 1: 'SHA256_RSA2048', 2: 'SHA256_RSA4096', 3: 'SHA256_RSA8192',
       4: 'SHA512_RSA2048', 5: 'SHA512_RSA4096', 6: 'SHA512_RSA8192'}


def describe(path):
    d = open(path, 'rb').read()
    if d[:4] != b'AVB0':
        print(f'== {os.path.basename(path)}: not a vbmeta image')
        return
    (_maj, _min, auth_sz, aux_sz, alg, _ho, _hs, _so, _ss, pk_off, pk_sz,
     _pmo, _pms, desc_off, desc_sz, rb_idx, flags, _rbl) = struct.unpack('>IIQQIQQQQQQQQQQQII', d[4:128])
    aux = d[256 + auth_sz: 256 + auth_sz + aux_sz]
    pk = aux[pk_off: pk_off + pk_sz]
    print(f'== {os.path.basename(path)}: alg {ALG.get(alg, alg)} flags {flags} rollback_index {rb_idx} '
          f'pubkey sha1 {hashlib.sha1(pk).hexdigest()[:8] if pk else "-"} '
          f'sha256 {hashlib.sha256(pk).hexdigest()[:8] if pk else "-"}')
    i, end = desc_off, desc_off + desc_sz
    while i < end:
        tag, nb = struct.unpack('>QQ', aux[i:i + 16])
        body = aux[i + 16: i + 16 + nb]
        if tag == 2:      # hash descriptor
            img_sz, = struct.unpack('>Q', body[0:8])
            pnl, = struct.unpack('>I', body[40:44])
            print(f'   hash      {body[132:132 + pnl].decode():14s} image_size {img_sz}')
        elif tag == 1:    # hashtree descriptor
            off = 4 + 8 + 8 + 8 + 4 + 4 + 4 + 8 + 8 + 32
            pnl, = struct.unpack('>I', body[off:off + 4])
            print(f'   hashtree  {body[off + 16 + 60: off + 16 + 60 + pnl].decode()}')
        elif tag == 4:    # chain partition descriptor
            rbl, pnl, pkl = struct.unpack('>III', body[0:12])
            cpk = body[76 + pnl: 76 + pnl + pkl]
            print(f'   chain     {body[76:76 + pnl].decode():14s} rollback_loc {rbl} '
                  f'key sha1 {hashlib.sha1(cpk).hexdigest()[:8]}')
        elif tag == 0:    # property descriptor
            kl, _vl = struct.unpack('>QQ', body[0:16])
            print(f'   property  {body[16:16 + kl].decode()}')
        else:
            print('   tag', tag)
        i += 16 + nb


if __name__ == '__main__':
    for name in sys.argv[2:]:
        describe(os.path.join(sys.argv[1], name))
