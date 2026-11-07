#!/usr/bin/env python3
"""Verify the restore kit against the live phone. Read only.

For every <name>.img in the kit, hash the file on this PC and hash
/dev/block/by-name/<name> on the phone (adb + root `sha256sum` and
`blockdev --getsize64`), and report MATCH / DIFFER / NOT ON DEVICE with the
denominator. Two independent methods (rule G2): Python's hashlib here, toybox
sha256sum on the phone.

Nothing is written to the phone. Each partition is read with one
`su -c 'sha256sum ...; blockdev ...'` call; no file is pushed.

Some partitions are written by the running system, so a difference there is
expected and is labelled, not hidden:
  persist                    changes in normal use (FINDINGS_LEDGER 2026-10-17, measured)
  misc                       BCB / virtual-A/B message are rewritten (ledger, measured)
  modemst1 modemst2 fsg      modem EFS, written by the modem (inferred)
  frp keystore devinfo       written by the system on some events (inferred)

--ota-dir keeps the purpose of the earlier version of this file: compare an
image extracted from an OTA payload with the leading bytes of the kit image
(the "OTA image is a byte-identical prefix of the partition" check in
docs/RESTORE_PATH.md). Matching is by base name: boot.img vs boot_b.img etc.

Usage:
    python tools/verify_restore_kit.py [--kit DIR] [--adb PATH] [--only a,b] [--skip super]
    python tools/verify_restore_kit.py --ota-dir DIR [--slot b]

Replaces the 2026-10 version, which compared hard-coded PC1 paths
(backups/2026-10-08, D:/rmx3301-ota/out) and verified nothing on this PC
(review finding R-44).
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import subprocess
import sys

DEFAULT_KIT = r"C:\Users\wdob\realmeGT2Pro-dev\restore-kit"
DEFAULT_ADB = r"C:\Users\wdob\platform-tools\adb.exe"
MUTABLE = {
    "persist": "changes in normal use (measured)",
    "misc": "BCB / virtual-A/B message rewritten (measured)",
    "modemst1": "modem EFS (inferred)",
    "modemst2": "modem EFS (inferred)",
    "fsg": "modem EFS (inferred)",
    "frp": "system-written (inferred)",
    "keystore": "system-written (inferred)",
    "devinfo": "system-written (inferred)",
}
SAFE_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")

# Backlog item D02/D06, added 2026-10-18.
#
# The specified set, transcribed from docs/RESTORE_SEQUENCE.md section
# "Kit location and the files Tier 1 needs". A kit missing any of these cannot
# perform Tier 1, so its absence is a failure, not an untested case.
REQUIRED_TIER1 = (
    "super", "boot_b", "vendor_boot_b", "dtbo_b", "recovery_b",
    "vbmeta_b", "vbmeta_system_b", "vbmeta_vendor_b", "misc",
)

# A capture-time record. This is what makes the mutable partitions verifiable:
# their divergence from the LIVE phone is expected, but their divergence from
# the manifest is corruption. Without it a wrong-handset or truncated
# persist.img passes silently, which is the D02 defect.
MANIFEST_NAME = "kit-manifest.sha256"


def sha256_file(path: str, limit: int | None = None) -> tuple[str, int]:
    h = hashlib.sha256()
    n = 0
    with open(path, "rb") as f:
        while True:
            want = 1 << 20 if limit is None else min(1 << 20, limit - n)
            if want <= 0:
                break
            chunk = f.read(want)
            if not chunk:
                break
            h.update(chunk)
            n += len(chunk)
    return h.hexdigest(), n


def adb(adb_path: str, *args: str, timeout: int = 1800) -> subprocess.CompletedProcess:
    return subprocess.run([adb_path, *args], capture_output=True, text=True, timeout=timeout)


def device_hash(adb_path: str, name: str) -> tuple[str | None, int | None, str]:
    if not SAFE_NAME.match(name):
        return None, None, "unsafe partition name"
    node = f"/dev/block/by-name/{name}"
    r = adb(adb_path, "shell", f"su -c 'sha256sum {node}; blockdev --getsize64 {node}'")
    out = r.stdout.replace("\r", "").strip().splitlines()
    err = r.stderr.replace("\r", "").strip()
    digest = size = None
    for line in out:
        m = re.match(r"^([0-9a-f]{64})\s", line)
        if m:
            digest = m.group(1)
        elif line.strip().isdigit():
            size = int(line.strip())
    diag = err or ("" if digest else " / ".join(out)[:200])
    return digest, size, diag


def check_device(adb_path: str) -> str | None:
    r = adb(adb_path, "get-state", timeout=30)
    if r.stdout.strip() != "device":
        return f"adb get-state: {r.stdout.strip() or r.stderr.strip()}"
    r = adb(adb_path, "shell", "su -c id", timeout=30)
    if "uid=0" not in r.stdout:
        return f"no root: {r.stdout.strip() or r.stderr.strip()}"
    return None


def kit_names(kit):
    """Every partition the kit holds an image for."""
    return sorted(n[:-4] for n in os.listdir(kit) if n.endswith(".img"))


def missing_required(kit):
    """Tier 1 files the kit does not contain. Absence is a failure, not an untested case."""
    have = set(kit_names(kit))
    return [n for n in REQUIRED_TIER1 if n not in have]


def write_manifest(kit):
    """Record size and sha256 for every kit image, at a moment the kit is known good."""
    rows = []
    for n in kit_names(kit):
        path = os.path.join(kit, n + ".img")
        sha, size = sha256_file(path)
        rows.append("%s  %14d  %s" % (sha, size, n))
    out = os.path.join(kit, MANIFEST_NAME)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write("# restore-kit manifest: sha256  bytes  partition\n")
        fh.write("# written by tools/verify_restore_kit.py --write-manifest\n")
        fh.write("\n".join(rows) + "\n")
    print("wrote %s  (%d partitions)" % (out, len(rows)))
    missing = missing_required(kit)
    if missing:
        print("WARNING: kit still incomplete, %d of %d Tier 1 files absent: %s"
              % (len(missing), len(REQUIRED_TIER1), ", ".join(missing)))
    return 0


def load_manifest(kit):
    path = os.path.join(kit, MANIFEST_NAME)
    if not os.path.exists(path):
        return None
    m = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) != 3:
                continue
            sha, size, name = parts
            m[name] = (int(size), sha)
    return m


def verify_offline(kit):
    """Verify the kit against its capture-time manifest. Needs no device at all."""
    manifest = load_manifest(kit)
    if manifest is None:
        print("error: no %s in %s." % (MANIFEST_NAME, kit), file=sys.stderr)
        print("  Run --write-manifest once while the kit is known good. Without a"
              " baseline the mutable partitions cannot be verified.", file=sys.stderr)
        return 2
    missing = missing_required(kit)
    print("kit: %s  (%d recorded, %d required)" % (kit, len(manifest), len(REQUIRED_TIER1)))
    bad = []
    for name in sorted(manifest):
        want_size, want_sha = manifest[name]
        path = os.path.join(kit, name + ".img")
        if not os.path.exists(path):
            print("%-20s %14s  %s  MISSING" % (name, "-", want_sha[:16]))
            bad.append(name)
            continue
        sha, size = sha256_file(path)
        if size != want_size:
            print("%-20s %14d  %s  %s  SIZE, recorded %d"
                  % (name, size, want_sha[:16], sha[:16], want_size))
            bad.append(name)
        elif sha != want_sha:
            print("%-20s %14d  %s  %s  CORRUPT" % (name, size, want_sha[:16], sha[:16]))
            bad.append(name)
        else:
            print("%-20s %14d  %s  %s  MATCH" % (name, size, want_sha[:16], sha[:16]))
    for name in kit_names(kit):
        if name not in manifest:
            print("%-20s %14s  not in manifest" % (name, "-"))
    print("")
    if missing:
        print("COMPLETENESS: %d of %d Tier 1 files absent: %s"
              % (len(missing), len(REQUIRED_TIER1), ", ".join(missing)))
    else:
        print("COMPLETENESS: all %d Tier 1 files present" % len(REQUIRED_TIER1))
    if bad:
        print("needs attention: %s" % ", ".join(bad))
        return 1
    if missing:
        return 1
    return 0

def verify_kit(kit: str, adb_path: str, only: set, skip: set) -> int:
    # Completeness first. It needs no device, and a kit missing a mandatory file
    # cannot perform Tier 1 however well the files it does hold compare.
    missing = missing_required(kit)
    if missing:
        print("COMPLETENESS FAILURE: %d of %d Tier 1 files absent from the kit: %s"
              % (len(missing), len(REQUIRED_TIER1), ", ".join(missing)))
        print("A kit without these cannot restore slot b. Refusing to report a pass.")
        return 1

    problem = check_device(adb_path)
    if problem:
        print(f"error: {problem}", file=sys.stderr)
        return 2
    files = sorted(f for f in os.listdir(kit) if f.endswith(".img"))
    names = [f[:-4] for f in files]
    if only:
        names = [n for n in names if n in only]
    names = [n for n in names if n not in skip]
    print(f"kit: {kit}  ({len(files)} images; checking {len(names)})")
    print(f"{'partition':<20} {'bytes':>14}  {'pc sha256':<16}  {'phone sha256':<16}  result")
    counts = {"MATCH": 0, "DIFFER": 0, "DIFFER (mutable)": 0, "CORRUPT": 0, "UNVERIFIED (mutable)": 0, "NOT ON DEVICE": 0, "SIZE": 0}
    # G2 review finding 2, 2026-10-18: the D02 fix lived only in --offline, while the
    # documented pre-flight runs the live path. A mutable partition that disagrees with
    # its own manifest is corrupt, whatever the live phone says.
    manifest = load_manifest(kit)
    if manifest is None:
        print("WARNING: no %s. Mutable partitions CANNOT be verified on this path." % MANIFEST_NAME)
    unexpected = []
    for n in names:
        path = os.path.join(kit, n + ".img")
        pc, size = sha256_file(path)
        dev, dsize, diag = device_hash(adb_path, n)
        if dev is None:
            result = "NOT ON DEVICE"
            detail = diag
        elif dsize is not None and dsize != size:
            result = "SIZE"
            detail = f"phone {dsize:,} bytes"
        elif dev == pc:
            result = "MATCH"
            detail = ""
        elif n in MUTABLE:
            if manifest is not None and n in manifest:
                want_size, want_sha = manifest[n]
                if size != want_size or pc != want_sha:
                    result = "CORRUPT"
                    detail = "kit differs from its manifest"
                else:
                    result = "DIFFER (mutable)"
                    detail = MUTABLE[n] + "; kit intact vs manifest"
            else:
                # G2 delta re-review, new finding 1, 2026-10-18.
                # Previously this returned DIFFER (mutable), which the exit-code test
                # ignores. Run --skip super WITHOUT --offline and the original F2 defect
                # reproduced: a corrupt persist.img gave exit 0. That made the fix
                # procedural, dependent on the operator following the doc order.
                # With no manifest a mutable partition CANNOT be verified, so this is
                # not a pass. It is reported as unverified and it fails.
                result = "UNVERIFIED (mutable)"
                detail = MUTABLE[n] + "; NO MANIFEST - cannot verify, run --write-manifest"
        else:
            result = "DIFFER"
            detail = ""
        counts[result] += 1
        if result in ("DIFFER", "CORRUPT", "UNVERIFIED (mutable)", "NOT ON DEVICE", "SIZE"):
            unexpected.append(n)
        print(f"{n:<20} {size:>14,}  {pc[:16]:<16}  {(dev or '-')[:16]:<16}  {result} {detail}", flush=True)
    print()
    print("summary: " + ", ".join(f"{k} {v}" for k, v in counts.items()) + f"  (of {len(names)})")
    if unexpected:
        print("needs attention: " + ", ".join(unexpected))
        return 1
    return 0


def verify_ota_prefix(kit: str, ota_dir: str, slot: str) -> int:
    images = sorted(f for f in os.listdir(ota_dir) if f.endswith(".img"))
    print(f"OTA images: {ota_dir} ({len(images)}); kit slot _{slot}")
    compared = matched = 0
    for f in images:
        base = f[:-4]
        cand = [os.path.join(kit, base + f"_{slot}.img"), os.path.join(kit, base + ".img")]
        kit_img = next((c for c in cand if os.path.exists(c)), None)
        if kit_img is None:
            print(f"  {base:<20} no kit image")
            continue
        size = os.path.getsize(os.path.join(ota_dir, f))
        ota_sha, _ = sha256_file(os.path.join(ota_dir, f))
        kit_sha, n = sha256_file(kit_img, limit=size)
        compared += 1
        ok = n == size and ota_sha == kit_sha
        matched += ok
        print(f"  {base:<20} {size:>12,} bytes  ota {ota_sha[:16]}  kit-prefix {kit_sha[:16]}  "
              f"{'PREFIX MATCH' if ok else 'DIFFER'}  ({os.path.basename(kit_img)})")
    print(f"summary: {matched} of {compared} OTA images are byte-identical prefixes of the kit image")
    return 0 if compared and matched == compared else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--kit", default=DEFAULT_KIT)
    ap.add_argument("--adb", default=DEFAULT_ADB)
    ap.add_argument("--only", default="", help="comma-separated partition names")
    ap.add_argument("--skip", default="", help="comma-separated partition names, e.g. super")
    ap.add_argument("--ota-dir", help="compare OTA-extracted images with kit-image prefixes instead")
    ap.add_argument("--slot", default="b")
    ap.add_argument("--write-manifest", action="store_true",
                    help="record sha256 and size for every kit image, as a capture-time baseline")
    ap.add_argument("--offline", action="store_true",
                    help="verify the kit against its manifest only; needs no device")
    a = ap.parse_args(argv)
    if not os.path.isdir(a.kit):
        print(f"error: kit not found: {a.kit}", file=sys.stderr)
        return 2
    if a.write_manifest:
        return write_manifest(a.kit)
    if a.offline:
        return verify_offline(a.kit)
    if a.ota_dir:
        return verify_ota_prefix(a.kit, a.ota_dir, a.slot)
    split = lambda s: {x.strip() for x in s.split(",") if x.strip()}  # noqa: E731
    return verify_kit(a.kit, a.adb, split(a.only), split(a.skip))


if __name__ == "__main__":
    sys.exit(main())
