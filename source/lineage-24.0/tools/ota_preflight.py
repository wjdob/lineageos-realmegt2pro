#!/usr/bin/env python3
"""
Preflight an OTA package for this device, entirely offline.

Answers the questions that decide whether the LineageOS recovery on this phone
would ACCEPT a given package, before anything is flashed and without touching
the device.

Why this exists
---------------
The recovery's acceptance gates are in its source (LineageOS 23.0
bootable/recovery). Every gate compares a value in the package with a value in
the recovery's own build properties. Both sides are available offline:

  - the package's metadata is in the zip
  - the recovery's properties are in the built recovery image ramdisk, which is
    on disk, or can be given with --prop

So the decision can be reproduced without a phone.

Gates, in the order recovery applies them
------------------------------------------
Transcribed from install/install.cpp (TryUpdateBinary, CheckPackageMetadata,
CheckAbSpecificMetadata, isInStringList) and install/spl_check.cpp
(ViolatesSPLDowngrade), lineage-23.0. Revised 2026-10-17 for review finding
R-12; the previous version diverged from the source in three places.
What this does NOT check, and cannot
------------------------------------
A package can pass every gate here and still be unusable. This tool reads
metadata only. It does not look inside the payload, so it says nothing about
whether the ROM actually works.

On 2026-10-17 a package passed every gate in this file while its vendor image
was missing roughly 105 PRODUCT_PACKAGES entries, including qseecomd,
cnss-daemon (Wi-Fi), pd-mapper and vendor_modprobe. The cause was unrelated to
the gates. A green run here means "recovery would accept this", never
"this is a good build".

Check vendor completeness separately: compare out/target/product/ferrari/
installed-files-vendor.txt against the package list, and confirm that binaries
are present, not just their .rc files.

  1. META-INF/com/android/metadata. The package is A/B only if this file is
     present AND ota-type == "AB". Otherwise recovery takes the non-A/B path
     and runs META-INF/com/google/android/update-binary.
  2. SPL gate (spl_check.cpp). Reads META-INF/com/android/metadata.pb ONLY,
     never the text metadata. Absent or unparsable metadata.pb -> PERMIT.
     Device SPL empty -> PERMIT. postcondition.security_patch_level older than
     the device -> violation, unless OtaMetadata.spl_downgrade or .downgrade is
     set. A violation is DENIED unless persist.vendor.recovery_allow_spl_downgrade
     is true and the text UI is visible, in which case the operator is asked.
  3. CheckPackageMetadata(AB):
       ota-type must be "AB";
       pre-device must be NON-EMPTY and contain ro.product.device
       (split on any of '|', ':', ','); absent pre-device is FATAL;
       serialno, if present, must contain ro.serialno (split on '|').
  4. CheckAbSpecificMetadata:
       pre-build-incremental, if present, must equal ro.build.version.incremental;
       pre-build, if present, must contain ro.build.fingerprint (split on '|') -
         FATAL only on MISMATCH, not on presence;
       post-timestamp empty, unparsable, or older than ro.build.date.utc and
         ota-downgrade != "yes" -> undeclared downgrade; ota-downgrade == "yes"
         without pre-build is also treated as undeclared;
       on a "user" build, the last '/' token of post-build must equal ro.build.tags;
       an undeclared downgrade needs the operator's confirmation in the text UI
         (PROMPT), unless an SPL downgrade was already approved.

Verdicts: ok, FATAL (recovery refuses), PROMPT (recovery asks the operator),
UNKNOWN (the recovery property was not supplied), info.

Not checked here: the whole-file signature (verify_package), which recovery runs
before these gates and which also only prompts on failure.

Usage
  python tools/ota_preflight.py <package.zip> [--recovery-prop-dir DIR] [--prop KEY=VALUE ...]

Tests: tools/tests/test_ota_preflight.py builds one package per install.cpp /
spl_check.cpp branch and checks the verdict the source code gives.
"""

from __future__ import annotations

import argparse
import re
import sys
import zipfile
from pathlib import Path

_METADATA_ENTRY = "META-INF/com/android/metadata"
_METADATA_PB_ENTRY = "META-INF/com/android/metadata.pb"
_UPDATE_BINARY = "META-INF/com/google/android/update-binary"
_PROPS_ENTRY = "payload_properties.txt"
_PAYLOAD_ENTRY = "payload.bin"

# install.cpp: #define FINGERPRING_SEPARATOR "|"; device list uses "|" ":" ","
FINGERPRINT_SEPARATOR = "|"
DEVICE_SEPARATORS = "|:,"

RECOVERY_PROPS = (
    "ro.product.device",
    "ro.serialno",
    "ro.build.version.incremental",
    "ro.build.fingerprint",
    "ro.build.date.utc",
    "ro.build.type",
    "ro.build.tags",
    "ro.build.version.security_patch",
    "persist.vendor.recovery_allow_spl_downgrade",
)


# ---------------------------------------------------------------- metadata

def parse_metadata(text: str) -> dict:
    """ReadMetadataFromPackage: split on '\\n', key = trim(before '='), value = trim(after).

    std::map::emplace keeps the FIRST occurrence of a repeated key."""
    out: dict = {}
    for line in text.split("\n"):
        eq = line.find("=")
        if eq == -1:
            continue
        key, value = line[:eq].strip(), line[eq + 1:].strip()
        out.setdefault(key, value)
    return out


def read_zip_bytes(zf: zipfile.ZipFile, name: str):
    try:
        return zf.read(name)
    except KeyError:
        return None


def is_in_string_list(target: str, str_list: str, delimiters: str) -> bool:
    """install.cpp isInStringList, including its length shortcuts.

    android::base::Split splits at ANY character of `delimiters`."""
    if len(target) > len(str_list):
        return False
    if len(target) == len(str_list) or not delimiters:
        return target == str_list
    parts = re.split("[" + re.escape(delimiters) + "]", str_list)
    return target in parts


def parse_int64(text: str):
    """android::base::ParseInt: optional sign, decimal digits, no surrounding junk."""
    if not re.fullmatch(r"[+-]?\d+", text or ""):
        return None
    value = int(text)
    if value < -(1 << 63) or value >= (1 << 63):
        return None
    return value


# ------------------------------------------------- metadata.pb (OtaMetadata)

class PbError(Exception):
    pass


def _varint(buf: bytes, pos: int):
    result = shift = 0
    while True:
        if pos >= len(buf):
            raise PbError("truncated varint")
        b = buf[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if not b & 0x80:
            return result, pos
        shift += 7
        if shift > 63:
            raise PbError("varint too long")


def _fields(buf: bytes):
    pos = 0
    while pos < len(buf):
        key, pos = _varint(buf, pos)
        field, wire = key >> 3, key & 7
        if wire == 0:
            value, pos = _varint(buf, pos)
        elif wire == 2:
            length, pos = _varint(buf, pos)
            if pos + length > len(buf):
                raise PbError("truncated length-delimited field")
            value = buf[pos:pos + length]
            pos += length
        elif wire == 5:
            value, pos = buf[pos:pos + 4], pos + 4
        elif wire == 1:
            value, pos = buf[pos:pos + 8], pos + 8
        else:
            raise PbError(f"unsupported wire type {wire}")
        if pos > len(buf):
            raise PbError("truncated field")
        yield field, wire, value


def parse_ota_metadata(blob: bytes) -> dict:
    """The fields of build/make/tools/releasetools/ota_metadata.proto that spl_check.cpp reads.

    OtaMetadata: downgrade = 3 (bool), postcondition = 6 (DeviceState), spl_downgrade = 9 (bool).
    DeviceState: security_patch_level = 6 (string)."""
    out = {"downgrade": False, "spl_downgrade": False, "post_spl": ""}
    for field, wire, value in _fields(blob):
        if field == 3 and wire == 0:
            out["downgrade"] = bool(value)
        elif field == 9 and wire == 0:
            out["spl_downgrade"] = bool(value)
        elif field == 6 and wire == 2:
            for f2, w2, v2 in _fields(value):
                if f2 == 6 and w2 == 2:
                    out["post_spl"] = v2.decode("utf-8", "replace")
    return out


# ----------------------------------------------------------- recovery props

PROP_RE = re.compile(r"^([A-Za-z0-9_.\-]+)=(.*)$")


def load_props(directory: Path) -> dict:
    """Read prop.default and *.prop out of an extracted recovery ramdisk."""
    props: dict = {}
    candidates = []
    for pat in ("prop.default", "*.prop", "default.prop"):
        candidates.extend(directory.rglob(pat))
    for f in candidates:
        try:
            for line in f.read_text(errors="replace").splitlines():
                m = PROP_RE.match(line.strip())
                if m:
                    props.setdefault(m.group(1), m.group(2))
        except OSError as e:
            print(f"warning: cannot read {f}: {e}", file=sys.stderr)
    return props


# ------------------------------------------------------------------- checks

class Report:
    def __init__(self):
        self.rows = []

    def add(self, gate, verdict, detail):
        self.rows.append((gate, verdict, detail))

    def render(self):
        w = max(len(r[0]) for r in self.rows) if self.rows else 10
        return "\n".join(f"  {g:<{w}}  {v:<8}  {d}" for g, v, d in self.rows)

    def verdicts(self):
        return [r[1] for r in self.rows]

    def get(self, gate):
        return [r for r in self.rows if r[0] == gate]


def evaluate(names: set, meta_text, pb_blob, payload_props_text, props: dict) -> Report:
    """The gate logic, separated from zip I/O so the tests can drive every branch.

    props holds the RECOVERY's properties; a key that is absent was not supplied."""
    rep = Report()

    def prop(key):
        return props.get(key)

    # ---- 1. text metadata and the A/B decision (TryUpdateBinary)
    has_metadata = meta_text is not None
    meta = parse_metadata(meta_text) if has_metadata else {}
    ota_type = meta.get("ota-type", "")
    package_is_ab = has_metadata and ota_type == "AB"
    if not has_metadata:
        rep.add("metadata", "info", "absent - not an A/B package; recovery takes the non-A/B path")
    else:
        rep.add("metadata", "ok", f"present, {len(meta)} keys")
    if ota_type == "BRICK":
        rep.add("ota-type", "info", "BRICK - recovery runs WipeAbDevice, not an install")
        return rep

    # ---- 2. SPL gate (spl_check.cpp) - metadata.pb only. Runs for every non-BRICK package,
    # before the A/B decision.
    spl_downgrade_approved = False
    current_spl = prop("ro.build.version.security_patch")
    if pb_blob is None:
        rep.add("SPL gate", "ok", "metadata.pb absent - spl_check.cpp PERMITS; the text "
                                  "post-security-patch-level is never read. Operator-bypassable")
    else:
        try:
            om = parse_ota_metadata(pb_blob)
        except PbError as e:
            om = None
            rep.add("SPL gate", "ok", f"metadata.pb unparsable ({e}) - spl_check.cpp PERMITS")
        if om is not None:
            post = om["post_spl"]
            if current_spl is None:
                rep.add("SPL gate", "UNKNOWN", f"package postcondition SPL {post!r}; recovery SPL not supplied")
            elif current_spl == "":
                rep.add("SPL gate", "ok", "recovery SPL empty - spl_check.cpp PERMITS")
            elif post < current_spl:
                if om["spl_downgrade"] or om["downgrade"]:
                    rep.add("SPL gate", "ok", f"package {post!r} < recovery {current_spl!r}, but "
                                              "OtaMetadata spl_downgrade/downgrade is set - PERMITTED")
                else:
                    allow = prop("persist.vendor.recovery_allow_spl_downgrade")
                    if allow is not None and allow.lower() in ("1", "y", "yes", "on", "true"):
                        spl_downgrade_approved = True
                        rep.add("SPL gate", "PROMPT", f"package {post!r} < recovery {current_spl!r}; "
                                                      "allow_spl_downgrade is set, so the text UI asks")
                    else:
                        rep.add("SPL gate", "FATAL", f"package {post!r} < recovery {current_spl!r} - "
                                                     "'Denying OTA because it's SPL downgrade'")
            else:
                rep.add("SPL gate", "ok", f"package {post!r} >= recovery {current_spl!r}")

    if not package_is_ab:
        # device_only_supports_ab is false in install.cpp (ab_device_supports_nonab = true),
        # so a non-A/B package skips CheckPackageMetadata and runs update-binary.
        has_binary = _UPDATE_BINARY in names
        rep.add("ota-type", "info" if has_binary else "FATAL",
                f"{ota_type or 'absent'!s} - not AB; non-A/B path needs {_UPDATE_BINARY}"
                + (" (present)" if has_binary else " (MISSING)"))
        return rep
    rep.add("ota-type", "ok", "AB")

    # update_engine side: kept from the earlier tool, not part of install.cpp
    for req in (_PAYLOAD_ENTRY, _PROPS_ENTRY):
        rep.add(req, "ok" if req in names else "FATAL",
                "present" if req in names else "MISSING - update_engine_sideload needs it")
    pprops = parse_metadata(payload_props_text or "")
    for k in ("FILE_HASH", "FILE_SIZE", "METADATA_HASH", "METADATA_SIZE"):
        rep.add(k, "ok" if k in pprops else "warn",
                (pprops[k][:24] + ("..." if len(pprops[k]) > 24 else "")) if k in pprops
                else "absent from payload_properties.txt (update_engine check, not install.cpp)")

    # ---- 3. CheckPackageMetadata
    device = prop("ro.product.device")
    device_note = ""
    if device is None and prop("ro.build.product") is not None:
        # The built recovery ramdisk does not set ro.product.device in prop.default;
        # G6_RECOVERY_BOOTED.md records the running recovery as device:RED8ACL1.
        device, device_note = prop("ro.build.product"), " (proxy: ro.build.product)"
    pkg_device = meta.get("pre-device", "")
    if pkg_device == "":
        rep.add("pre-device", "FATAL", "absent or empty - install.cpp rejects (pkg_device.empty())")
    elif device is None:
        rep.add("pre-device", "UNKNOWN", f"package wants {pkg_device!r}; recovery ro.product.device not supplied")
    elif is_in_string_list(device, pkg_device, DEVICE_SEPARATORS):
        rep.add("pre-device", "ok", f"{device!r}{device_note} is in {pkg_device!r}")
    else:
        rep.add("pre-device", "FATAL", f"recovery is {device!r}{device_note}, package is for {pkg_device!r}")

    pkg_serial = meta.get("serialno", "")
    if pkg_serial:
        serial = prop("ro.serialno")
        if serial is None:
            rep.add("serialno", "UNKNOWN", f"package pins {pkg_serial!r}; recovery ro.serialno not supplied")
        elif any(serial == s.strip() for s in pkg_serial.split("|")):
            rep.add("serialno", "ok", "matches")
        else:
            rep.add("serialno", "FATAL", f"package is for serial {pkg_serial!r}")

    # ---- 4. CheckAbSpecificMetadata
    pkg_pre_inc = meta.get("pre-build-incremental", "")
    if pkg_pre_inc:
        inc = prop("ro.build.version.incremental")
        if inc is None:
            rep.add("pre-build-incremental", "UNKNOWN", f"package wants {pkg_pre_inc!r}; not supplied")
        elif pkg_pre_inc != inc:
            rep.add("pre-build-incremental", "FATAL", f"package is for {pkg_pre_inc!r}, recovery is {inc!r}")
        else:
            rep.add("pre-build-incremental", "ok", "matches")

    pkg_pre_build = meta.get("pre-build", "")
    if pkg_pre_build:
        fp = prop("ro.build.fingerprint")
        if fp is None:
            rep.add("pre-build", "UNKNOWN", "present; recovery ro.build.fingerprint not supplied")
        elif not is_in_string_list(fp, pkg_pre_build, FINGERPRINT_SEPARATOR):
            rep.add("pre-build", "FATAL", f"package is for {pkg_pre_build!r}, recovery is {fp!r}")
        else:
            rep.add("pre-build", "ok", "recovery fingerprint is listed")

    undeclared_downgrade = None
    utc = prop("ro.build.date.utc")
    if utc is None:
        rep.add("post-timestamp", "UNKNOWN", "recovery ro.build.date.utc not supplied")
    else:
        build_ts = parse_int64(utc)
        if build_ts is None:
            build_ts = (1 << 63) - 1   # GetIntProperty default: INT64_MAX
        pt_text = meta.get("post-timestamp", "")
        pt = parse_int64(pt_text)
        undeclared_downgrade = False
        if pt_text == "" or pt is None or pt < build_ts:
            if meta.get("ota-downgrade") != "yes":
                undeclared_downgrade = True
                why = "absent/unparsable" if pt is None else f"{pt} < {build_ts}"
                rep.add("post-timestamp", "PROMPT" if not spl_downgrade_approved else "ok",
                        f"{why}: undeclared downgrade - the text UI asks the operator")
            elif not pkg_pre_build:
                undeclared_downgrade = True
                rep.add("post-timestamp", "PROMPT" if not spl_downgrade_approved else "ok",
                        "ota-downgrade=yes but no pre-build - treated as undeclared; the text UI asks")
            else:
                rep.add("post-timestamp", "ok", "declared downgrade with pre-build")
        else:
            rep.add("post-timestamp", "ok", f"{pt} >= {build_ts}")

    post_build = meta.get("post-build", "")
    tokens = [t for t in post_build.split("/") if t]
    if tokens:
        btype = prop("ro.build.type")
        if btype is None:
            rep.add("post-build tag", "UNKNOWN", "recovery ro.build.type not supplied")
        elif btype != "user":
            rep.add("post-build tag", "ok", f"not checked on a {btype!r} build")
        else:
            tags = prop("ro.build.tags")
            if tags is None:
                rep.add("post-build tag", "UNKNOWN", "user build; ro.build.tags not supplied")
            elif tags != tokens[-1]:
                rep.add("post-build tag", "FATAL", f"package tag {tokens[-1]!r} != recovery tags {tags!r}")
            else:
                rep.add("post-build tag", "ok", "matches")
    return rep


def preflight(pkg: Path, props: dict) -> int:
    print(f"package : {pkg}")
    print(f"size    : {pkg.stat().st_size:,} bytes")
    print()
    try:
        zf = zipfile.ZipFile(pkg)
    except zipfile.BadZipFile as e:
        print(f"FATAL: not a readable zip: {e}")
        return 2
    with zf:
        names = set(zf.namelist())
        print("members:")
        for n in sorted(names):
            print(f"  {zf.getinfo(n).file_size:>14,}  {n}")
        print()
        meta_raw = read_zip_bytes(zf, _METADATA_ENTRY)
        meta_text = meta_raw.decode("utf-8", "replace") if meta_raw is not None else None
        pb = read_zip_bytes(zf, _METADATA_PB_ENTRY)
        props_raw = read_zip_bytes(zf, _PROPS_ENTRY)
        props_text = props_raw.decode("utf-8", "replace") if props_raw is not None else None

    if meta_text is not None:
        print("metadata keys:")
        for k, v in sorted(parse_metadata(meta_text).items()):
            print(f"  {k} = {v}")
        print()
    if pb is not None:
        try:
            print(f"metadata.pb: {parse_ota_metadata(pb)}")
        except PbError as e:
            print(f"metadata.pb: unparsable ({e})")
        print()

    rep = evaluate(names, meta_text, pb, props_text, props)
    print("gates:")
    print(rep.render())
    print()
    v = rep.verdicts()
    if "FATAL" in v:
        print("VERDICT: REFUSED - at least one FATAL gate.")
        return 1
    if "PROMPT" in v:
        print("VERDICT: needs the operator - recovery asks before installing (PROMPT).")
        return 0
    if "UNKNOWN" in v:
        print("VERDICT: no fatal gate found; UNKNOWN gates need the recovery's properties.")
        return 0
    print("VERDICT: accepted by every gate checked.")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Offline OTA preflight for the RMX3301 LineageOS recovery")
    ap.add_argument("package", type=Path)
    ap.add_argument("--recovery-prop-dir", type=Path, default=None,
                    help="extracted recovery ramdisk containing prop.default")
    ap.add_argument("--prop", action="append", default=[], metavar="KEY=VALUE",
                    help="a recovery property; repeatable. Overrides the prop dir")
    ap.add_argument("--expect-product-device", default=None, help="= --prop ro.product.device=...")
    ap.add_argument("--expect-date-utc", default=None, help="= --prop ro.build.date.utc=...")
    ap.add_argument("--expect-security-patch", default=None,
                    help="= --prop ro.build.version.security_patch=...")
    a = ap.parse_args(argv)

    props = load_props(a.recovery_prop_dir) if a.recovery_prop_dir else {}
    for key, val in (("ro.product.device", a.expect_product_device),
                     ("ro.build.date.utc", a.expect_date_utc),
                     ("ro.build.version.security_patch", a.expect_security_patch)):
        if val is not None:
            props[key] = val
    for kv in a.prop:
        if "=" not in kv:
            ap.error(f"--prop needs KEY=VALUE, got {kv!r}")
        k, v = kv.split("=", 1)
        props[k] = v
    missing = [k for k in RECOVERY_PROPS if k not in props]
    if missing:
        print("note: recovery properties not supplied (their gates report UNKNOWN): " + ", ".join(missing))
        print()
    return preflight(a.package, props)


if __name__ == "__main__":
    sys.exit(main())
