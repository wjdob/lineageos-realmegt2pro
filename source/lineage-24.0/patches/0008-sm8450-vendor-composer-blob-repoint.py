#!/usr/bin/env python3
"""0008 sm8450-common vendor: repoint the display composer blob at android.hardware.common-V2-ndk.so.

GOAL1 (docs/GOAL1_BLOB_FIX.md). The prebuilt
    proprietary/vendor/bin/hw/vendor.qti.hardware.display.composer-service
has a DT_NEEDED entry "android.hardware.common-V2-ndk_platform.so". No module in the
LineageOS 23.0 tree builds that library; android.hardware.common-V2-ndk.so is built, has the
same interface, and is what patch 0003 makes the Android.bp declare. This script rewrites the
one string in .dynstr in place - the new name is shorter, the freed 9 bytes become NULs - so no
offset in the ELF changes and check_elf_files can stay ENABLED.

It is a script, not a diff, because the target is a binary. It only acts on the exact upstream
blob and proves its own output:

    upstream  Arman-ATI/proprietary_vendor_oneplus_sm8450-common @ 2e695fe2ad3d99fd6bfd386b1ab0764c7b115d2a
              sha256 fbd23e9b73784e52583b3301bd0082777d48e667e561d341261ef9c00a59df3f  (968,224 bytes)
    patched   sha256 e8d9be778fdc15b11e01d63c5265ee48d9cb3bfd9cd57a6ba10c0425e13e096e
              = the blob in the WSL build tree that passed the native ELF check (12 bytes differ)

Any other input is refused; an already-patched blob is left alone.

Usage (from the checkout root):
    python3 /path/to/patches/0008-sm8450-vendor-composer-blob-repoint.py vendor/oneplus/sm8450-common
"""

import hashlib
import os
import struct
import sys

REL = "proprietary/vendor/bin/hw/vendor.qti.hardware.display.composer-service"
UPSTREAM_SHA256 = "fbd23e9b73784e52583b3301bd0082777d48e667e561d341261ef9c00a59df3f"
PATCHED_SHA256 = "e8d9be778fdc15b11e01d63c5265ee48d9cb3bfd9cd57a6ba10c0425e13e096e"
OLD = b"android.hardware.common-V2-ndk_platform.so\x00"
NEW = b"android.hardware.common-V2-ndk.so\x00"


def dynstr_range(elf: bytes):
    """(offset, size) of .dynstr in a little-endian ELF64 file."""
    if elf[:4] != b"\x7fELF" or elf[4] != 2 or elf[5] != 1:
        raise SystemExit("error: not a little-endian ELF64 file")
    shoff = struct.unpack_from("<Q", elf, 0x28)[0]
    shentsize, shnum, shstrndx = struct.unpack_from("<HHH", elf, 0x3A)
    sections = [struct.unpack_from("<IIQQQQ", elf, shoff + i * shentsize) for i in range(shnum)]
    names_off = sections[shstrndx][4]
    for name, _type, _flags, _addr, off, size in sections:
        end = elf.index(b"\x00", names_off + name)
        if elf[names_off + name:end] == b".dynstr":
            return off, size
    raise SystemExit("error: no .dynstr section")


def main(argv):
    if len(argv) != 2:
        print(__doc__)
        return 2
    path = os.path.join(argv[1], REL) if os.path.isdir(argv[1]) else argv[1]
    data = open(path, "rb").read()
    digest = hashlib.sha256(data).hexdigest()
    print(f"blob   {path}")
    print(f"sha256 {digest}  ({len(data):,} bytes)")
    if digest == PATCHED_SHA256:
        print("already patched; nothing to do")
        return 0
    if digest != UPSTREAM_SHA256:
        print("error: not the upstream blob this patch was made for; refusing", file=sys.stderr)
        return 1
    if data.count(OLD) != 1:
        print(f"error: expected one occurrence of {OLD!r}, found {data.count(OLD)}", file=sys.stderr)
        return 1
    at = data.index(OLD)
    ds_off, ds_size = dynstr_range(data)
    if not (ds_off <= at and at + len(OLD) <= ds_off + ds_size):
        print("error: the string is not inside .dynstr", file=sys.stderr)
        return 1
    out = bytearray(data)
    out[at:at + len(OLD)] = NEW + b"\x00" * (len(OLD) - len(NEW))
    new_digest = hashlib.sha256(out).hexdigest()
    if new_digest != PATCHED_SHA256:
        print(f"error: result {new_digest} is not the expected {PATCHED_SHA256}; file left unchanged",
              file=sys.stderr)
        return 1
    tmp = path + ".0008.tmp"
    with open(tmp, "wb") as f:
        f.write(out)
    os.replace(tmp, path)
    print(f"patched at offset {at} (.dynstr {ds_off}-{ds_off + ds_size}); "
          f"{sum(a != b for a, b in zip(data, out))} bytes changed")
    print(f"sha256 {new_digest}  verified")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
