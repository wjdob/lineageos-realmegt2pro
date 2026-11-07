"""Tests for ota_preflight.py, derived from the recovery source, not from the tool.

Each case names the branch of LineageOS 23.0 bootable/recovery it reproduces:
install/install.cpp (TryUpdateBinary, CheckPackageMetadata, CheckAbSpecificMetadata,
isInStringList) and install/spl_check.cpp (ViolatesSPLDowngrade). The expected
verdict is what that code does, so a test fails if the tool drifts from recovery.

Written for review finding R-12 (docs/CLAIMS_REVIEW_2026-10-17.md). No phone needed.
"""

from __future__ import annotations

import io
import os
import sys
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ota_preflight as pf  # noqa: E402

AB_NAMES = {"payload.bin", "payload_properties.txt", "META-INF/com/android/metadata"}
PAYLOAD_PROPS = "FILE_HASH=x\nFILE_SIZE=1\nMETADATA_HASH=y\nMETADATA_SIZE=2\n"

RECOVERY = {
    "ro.product.device": "ferrari",
    "ro.serialno": "TESTSERIAL0001",
    "ro.build.version.incremental": "eng.build.20261011",
    "ro.build.fingerprint": "realme/lineage_ferrari/ferrari:16/BP2A/1:userdebug/test-keys",
    "ro.build.date.utc": "1760000000",
    "ro.build.type": "userdebug",
    "ro.build.tags": "test-keys",
    "ro.build.version.security_patch": "2026-02-01",
}


# ---- an encoder for OtaMetadata written from ota_metadata.proto, independent of the tool's decoder
def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def _ld(field: int, payload: bytes) -> bytes:
    return _varint(field << 3 | 2) + _varint(len(payload)) + payload


def ota_metadata_pb(post_spl: str, downgrade=False, spl_downgrade=False) -> bytes:
    device_state = _ld(6, post_spl.encode())                  # DeviceState.security_patch_level = 6
    msg = _varint(1 << 3 | 0) + _varint(1)                    # type = AB (1)
    if downgrade:
        msg += _varint(3 << 3 | 0) + _varint(1)               # downgrade = 3
    msg += _ld(6, device_state)                               # postcondition = 6
    if spl_downgrade:
        msg += _varint(9 << 3 | 0) + _varint(1)               # spl_downgrade = 9
    return msg


def meta(**kv) -> str:
    base = {"ota-type": "AB", "pre-device": "ferrari", "post-timestamp": "1770000000"}
    base.update({k.replace("_", "-"): v for k, v in kv.items() if v is not None})
    for k in [k.replace("_", "-") for k, v in kv.items() if v is None]:
        base.pop(k, None)
    return "".join(f"{k}={v}\n" for k, v in base.items())


def run(meta_text=None, pb=None, props=None, names=None):
    if names is None:
        names = set(AB_NAMES) if meta_text is not None else {"payload.bin"}
    return pf.evaluate(names, meta_text, pb, PAYLOAD_PROPS, RECOVERY if props is None else props)


def verdict(rep, gate):
    rows = rep.get(gate)
    return rows[0][1] if rows else None


class CheckPackageMetadataTests(unittest.TestCase):
    def test_absent_pre_device_is_fatal(self):
        # install.cpp CheckPackageMetadata: pkg_device.empty() -> "Package is for product" -> false
        self.assertEqual(verdict(run(meta(pre_device=None)), "pre-device"), "FATAL")

    def test_empty_pre_device_is_fatal(self):
        self.assertEqual(verdict(run(meta(pre_device="")), "pre-device"), "FATAL")

    def test_matching_device_passes(self):
        self.assertEqual(verdict(run(meta()), "pre-device"), "ok")

    def test_device_list_split_on_pipe_colon_and_comma(self):
        # isInStringList(device, pkg_device, FINGERPRING_SEPARATOR ":" ",") splits on any of "|:,"
        for listed in ("a|ferrari", "a:ferrari", "a,ferrari", "x|y:ferrari,z"):
            self.assertEqual(verdict(run(meta(pre_device=listed)), "pre-device"), "ok", listed)

    def test_wrong_device_is_fatal(self):
        self.assertEqual(verdict(run(meta(pre_device="peridot")), "pre-device"), "FATAL")

    def test_substring_is_not_a_match(self):
        # isInStringList compares whole tokens: "ferrari" is not in "ferrarix"
        self.assertEqual(verdict(run(meta(pre_device="ferrarix|other")), "pre-device"), "FATAL")

    def test_serialno_mismatch_is_fatal(self):
        self.assertEqual(verdict(run(meta(serialno="aaaa|bbbb")), "serialno"), "FATAL")

    def test_serialno_in_list_passes(self):
        self.assertEqual(verdict(run(meta(serialno="aaaa|TESTSERIAL0001")), "serialno"), "ok")


class CheckAbSpecificMetadataTests(unittest.TestCase):
    def test_pre_build_present_and_matching_passes(self):
        # Only a MISMATCH is fatal; the earlier tool rejected any pre-build
        fp = RECOVERY["ro.build.fingerprint"]
        self.assertEqual(verdict(run(meta(pre_build="other/fp|" + fp)), "pre-build"), "ok")

    def test_pre_build_mismatch_is_fatal(self):
        self.assertEqual(verdict(run(meta(pre_build="other/fp")), "pre-build"), "FATAL")

    def test_pre_build_incremental_mismatch_is_fatal(self):
        self.assertEqual(verdict(run(meta(pre_build_incremental="123")), "pre-build-incremental"), "FATAL")

    def test_pre_build_incremental_match_passes(self):
        inc = RECOVERY["ro.build.version.incremental"]
        self.assertEqual(verdict(run(meta(pre_build_incremental=inc)), "pre-build-incremental"), "ok")

    def test_older_timestamp_prompts(self):
        # undeclared_downgrade -> ask_to_continue_downgrade in the text UI
        self.assertEqual(verdict(run(meta(post_timestamp="1500000000")), "post-timestamp"), "PROMPT")

    def test_missing_timestamp_prompts(self):
        # pkg_post_timestamp_string.empty() counts as a downgrade
        self.assertEqual(verdict(run(meta(post_timestamp=None)), "post-timestamp"), "PROMPT")

    def test_unparsable_timestamp_prompts(self):
        self.assertEqual(verdict(run(meta(post_timestamp="soon")), "post-timestamp"), "PROMPT")

    def test_declared_downgrade_without_pre_build_still_prompts(self):
        rep = run(meta(post_timestamp="1500000000", ota_downgrade="yes"))
        self.assertEqual(verdict(rep, "post-timestamp"), "PROMPT")

    def test_declared_downgrade_with_pre_build_passes(self):
        fp = RECOVERY["ro.build.fingerprint"]
        rep = run(meta(post_timestamp="1500000000", ota_downgrade="yes", pre_build=fp))
        self.assertEqual(verdict(rep, "post-timestamp"), "ok")

    def test_newer_timestamp_passes(self):
        self.assertEqual(verdict(run(meta()), "post-timestamp"), "ok")

    def test_post_build_tag_checked_only_on_user_builds(self):
        m = meta(post_build="realme/x/ferrari:16/BP2A/1:user/release-keys")
        self.assertEqual(verdict(run(m), "post-build tag"), "ok")          # userdebug: skipped
        user = dict(RECOVERY, **{"ro.build.type": "user"})
        self.assertEqual(verdict(run(m, props=user), "post-build tag"), "FATAL")
        user_rel = dict(user, **{"ro.build.tags": "release-keys"})
        self.assertEqual(verdict(run(m, props=user_rel), "post-build tag"), "ok")


class SplCheckTests(unittest.TestCase):
    def test_absent_metadata_pb_permits_even_with_older_text_spl(self):
        # spl_check.cpp: no metadata.pb -> "treating this as non-spl-downgrade, permit OTA install".
        # The text post-security-patch-level is never read; the earlier tool called this FATAL.
        rep = run(meta(post_security_patch_level="2020-01-01"), pb=None)
        self.assertEqual(verdict(rep, "SPL gate"), "ok")
        self.assertNotIn("FATAL", rep.verdicts())

    def test_older_pb_spl_is_denied(self):
        rep = run(meta(), pb=ota_metadata_pb("2025-07-05"))
        self.assertEqual(verdict(rep, "SPL gate"), "FATAL")

    def test_spl_downgrade_bit_permits(self):
        rep = run(meta(), pb=ota_metadata_pb("2025-07-05", spl_downgrade=True))
        self.assertEqual(verdict(rep, "SPL gate"), "ok")

    def test_downgrade_bit_permits(self):
        rep = run(meta(), pb=ota_metadata_pb("2025-07-05", downgrade=True))
        self.assertEqual(verdict(rep, "SPL gate"), "ok")

    def test_equal_or_newer_spl_passes(self):
        for spl in ("2026-02-01", "2026-03-01"):
            self.assertEqual(verdict(run(meta(), pb=ota_metadata_pb(spl)), "SPL gate"), "ok", spl)

    def test_empty_device_spl_permits(self):
        props = dict(RECOVERY, **{"ro.build.version.security_patch": ""})
        rep = run(meta(), pb=ota_metadata_pb("2020-01-01"), props=props)
        self.assertEqual(verdict(rep, "SPL gate"), "ok")

    def test_allow_property_turns_denial_into_prompt_and_skips_timestamp_prompt(self):
        # TryUpdateBinary: allow_spl_downgrade && IsTextVisible -> ask; approval sets
        # spl_downgrade_approved, which CheckAbSpecificMetadata uses to skip its own prompt
        props = dict(RECOVERY, **{"persist.vendor.recovery_allow_spl_downgrade": "true"})
        rep = run(meta(post_timestamp="1500000000"), pb=ota_metadata_pb("2025-07-05"), props=props)
        self.assertEqual(verdict(rep, "SPL gate"), "PROMPT")
        self.assertEqual(verdict(rep, "post-timestamp"), "ok")

    def test_unparsable_pb_permits(self):
        rep = run(meta(), pb=b"\x0a\xff\xff")
        self.assertEqual(verdict(rep, "SPL gate"), "ok")

    def test_spl_gate_applies_to_non_ab_packages_too(self):
        # ViolatesSPLDowngrade runs before the A/B branch in TryUpdateBinary
        names = {"META-INF/com/google/android/update-binary"}
        rep = pf.evaluate(names, None, ota_metadata_pb("2020-01-01"), None, RECOVERY)
        self.assertEqual(verdict(rep, "SPL gate"), "FATAL")


class PackageTypeTests(unittest.TestCase):
    def test_no_metadata_takes_non_ab_path(self):
        rep = pf.evaluate({"payload.bin"}, None, None, None, RECOVERY)
        self.assertEqual(verdict(rep, "ota-type"), "FATAL")   # no update-binary either
        self.assertIsNone(verdict(rep, "pre-device"))         # CheckPackageMetadata not reached

    def test_ota_type_must_be_exactly_AB(self):
        rep = run(meta(ota_type="ab"))
        self.assertIsNone(verdict(rep, "pre-device"))

    def test_brick_package_is_reported(self):
        self.assertEqual(verdict(run(meta(ota_type="BRICK")), "ota-type"), "info")

    def test_metadata_first_key_wins(self):
        # std::map::emplace does not overwrite an existing key
        text = "ota-type=AB\npre-device=ferrari\npre-device=peridot\npost-timestamp=1770000000\n"
        self.assertEqual(verdict(run(text), "pre-device"), "ok")


class EndToEndTests(unittest.TestCase):
    def test_zip_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "pkg.zip"
            with zipfile.ZipFile(p, "w") as z:
                z.writestr("META-INF/com/android/metadata", meta())
                z.writestr("META-INF/com/android/metadata.pb", ota_metadata_pb("2025-07-05"))
                z.writestr("payload.bin", b"CrAU")
                z.writestr("payload_properties.txt", PAYLOAD_PROPS)
            buf = io.StringIO()
            args = [str(p)] + [f"--prop={k}={v}" for k, v in RECOVERY.items()]
            with redirect_stdout(buf):
                rc = pf.main(args)
            self.assertEqual(rc, 1)
            self.assertIn("Denying OTA because it's SPL downgrade", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
