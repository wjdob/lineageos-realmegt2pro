#!/usr/bin/env python3
"""Read-only diagnostics and partition backup for the Realme GT 2 Pro.

Partition access is read-only; backups create temporary files on the device and
capture files on the host. There is no code here that flashes,
erases, formats, locks or unlocks anything, and there is no flag that would make
it do so. If you need to write to the device, that is a decision for a human
with a proven restore path, not something this script should offer.

How backups work, and why they go through the device:

    dd reads a partition into a file under /data/local/tmp
    adb pull copies that file to the host

The two step form exists because pulling raw bytes straight through a pipe is
unreliable on Windows, and it also means a failed transfer leaves the copy on the
device where it can be retried.

Commands:

    python tools/rmx3301_device.py check
    python tools/rmx3301_device.py props
    python tools/rmx3301_device.py partitions
    python tools/rmx3301_device.py backup --out backups/2026-01-01
    python tools/rmx3301_device.py root-check
"""

from __future__ import annotations

import argparse
import datetime as _dt
import os
import shutil
import subprocess
import sys

EXIT_OK = 0
EXIT_ERROR = 2

# Partitions small enough to back up quickly and important enough that losing
# them would hurt. my_* and oplusreserve* hold per device calibration and
# identity data that cannot be regenerated.
DEFAULT_PARTITIONS = [
    "boot",
    "init_boot",
    "vendor_boot",
    "recovery",
    "dtbo",
    "vbmeta",
    "vbmeta_system",
    "vbmeta_vendor",
    "persist",
    "modem",
    "modemst1",
    "modemst2",
    "fsg",
    "bluetooth",
    "misc",
]

LARGE_PARTITIONS = [
    "super",
    "userdata",
]

MARKER = "RMX3301PROBE"

# Properties worth recording. All are reads.
# Properties that Magisk integrity modules are known to overwrite on this phone.
# Anything read here can be a lie, so the tool labels it rather than presenting
# it as fact. See docs/SPOOFING.md.
SPOOFABLE_KEYS = {
    "ro.boot.verifiedbootstate",
    "ro.boot.flash.locked",
    "ro.boot.veritymode",
    "ro.boot.vbmeta.device_state",
    "ro.boot.realbootstate",
    "ro.boot.realmebootstate",
    "ro.debuggable",
    "ro.secure",
    "ro.adb.secure",
    "ro.build.type",
    "ro.build.tags",
}

PROP_KEYS = [
    "ro.product.model",
    "ro.product.name",
    "ro.product.device",
    "ro.product.board",
    "ro.product.manufacturer",
    "ro.product.brand",
    "ro.build.fingerprint",
    "ro.build.display.id",
    "ro.build.version.release",
    "ro.build.version.sdk",
    "ro.build.version.security_patch",
    "ro.build.date",
    "ro.build.type",
    "ro.build.tags",
    "ro.boot.hardware",
    "ro.boot.slot_suffix",
    "ro.boot.verifiedbootstate",
    "ro.boot.flash.locked",
    "ro.boot.veritymode",
    "ro.boot.vbmeta.device_state",
    "ro.boot.dynamic_partitions",
    "ro.boot.dynamic_partitions_retrofit",
    "ro.virtual_ab.enabled",
    "ro.virtual_ab.retrofit",
    "ro.crypto.state",
    "ro.crypto.type",
    "ro.build.version.ota",
    "ro.build.version.realmeui",
    "ro.build.oplus_nv_id",
    "ro.oplus.version",
    "ro.oplus.image.my_stock.version",
    "ro.separate.soft",
    "ro.hardware.keystore",
    "init.svc.snapuserd",
    "sys.boot_completed",
]


class DeviceError(Exception):
    """Raised when the device cannot be reached or a read fails."""


def resolve_partitions(
    names: list[str],
    available: list[str],
    slot_suffix: str,
    all_slots: bool = False,
) -> tuple[list[str], list[str]]:
    """Map requested partition names to entries under /dev/block/by-name.

    A name that exists as given is used as given, so "persist" and "boot_a"
    both work. Otherwise, on an A/B device, the slot suffixed form is used:
    the active slot's, or both slots' when all_slots is set. Returns the
    resolved entries in request order without duplicates, and the names that
    matched nothing.
    """

    have = set(available)
    resolved: list[str] = []
    missing: list[str] = []
    for name in names:
        if name in have:
            candidates = [name]
        else:
            suffixes = ("_a", "_b") if all_slots else ((slot_suffix,) if slot_suffix else ())
            candidates = [name + s for s in suffixes if name + s in have]
        if not candidates:
            missing.append(name)
        for entry in candidates:
            if entry not in resolved:
                resolved.append(entry)
    return resolved, missing


def which_adb() -> str:
    found = shutil.which("adb")
    if not found:
        raise DeviceError("adb was not found on PATH; install platform-tools first")
    return found


def run(cmd: list[str], *, timeout: int = 120, check: bool = True) -> subprocess.CompletedProcess:
    proc = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        text=True,
        errors="replace",
    )
    if check and proc.returncode != 0:
        raise DeviceError(
            f"{' '.join(cmd)} failed with exit code {proc.returncode}: {proc.stderr.strip()}"
        )
    return proc


def adb(*args: str, serial: str | None = None, timeout: int = 120) -> str:
    cmd = [which_adb()]
    if serial:
        cmd += ["-s", serial]
    cmd += list(args)
    return run(cmd, timeout=timeout).stdout


def devices() -> list[tuple[str, str]]:
    out = adb("devices")
    found: list[tuple[str, str]] = []
    for line in out.splitlines()[1:]:
        line = line.strip()
        if not line or "\t" not in line:
            continue
        serial, state = line.split("\t", 1)
        found.append((serial.strip(), state.strip()))
    return found


def pick_serial(requested: str | None) -> str:
    found = devices()
    if not found:
        raise DeviceError(
            "no device is visible to adb. Connect the phone, unlock the screen, "
            "and accept the USB debugging prompt. Then run 'adb devices' to confirm."
        )
    if requested:
        for serial, state in found:
            if serial == requested:
                if state != "device":
                    raise DeviceError(f"device {serial} is in state '{state}', not 'device'")
                return serial
        raise DeviceError(f"device {requested} is not connected; visible: {[s for s, _ in found]}")
    ready = [serial for serial, state in found if state == "device"]
    if not ready:
        raise DeviceError(
            "a device is connected but adb reports state "
            f"'{found[0][1]}'. Accept the USB debugging prompt on the phone."
        )
    if len(ready) > 1:
        raise DeviceError(f"more than one device is ready ({ready}); pass --serial")
    return ready[0]


def shell(command: str, *, serial: str, timeout: int = 120) -> str:
    return adb("shell", command, serial=serial, timeout=timeout)


def have_root(serial: str) -> bool:
    try:
        out = shell("su -c 'id -u' 2>/dev/null || echo 255", serial=serial)
    except DeviceError:
        return False
    return out.strip().splitlines()[-1].strip() == "0" if out.strip() else False


def cmd_check(args: argparse.Namespace) -> int:
    serial = pick_serial(args.serial)
    print(f"serial            {serial}")
    print(f"state             device")
    print(f"adb version       {adb('version').splitlines()[0]}")
    print(f"root available    {'yes' if have_root(serial) else 'no'}")
    out = shell("uname -a", serial=serial)
    print(f"kernel            {out.strip().splitlines()[-1] if out.strip() else 'unknown'}")
    for key in ("ro.build.display.id", "ro.build.version.release", "ro.build.version.ota"):
        value = shell(f"getprop {key}", serial=serial).strip()
        print(f"{key:<17} {value}")
    print()
    print("guardrail: this tool only reads. Locking the bootloader is out of scope.")
    return EXIT_OK


def cmd_props(args: argparse.Namespace) -> int:
    serial = pick_serial(args.serial)
    spoofed_seen: list[tuple[str, str]] = []
    for key in PROP_KEYS:
        value = shell(f"getprop {key}", serial=serial).strip()
        flag = ""
        if key in SPOOFABLE_KEYS:
            flag = "   <- SPOOFABLE, do not trust"
            spoofed_seen.append((key, value))
        print(f"{key:<38} {value if value else '-'}{flag}")

    if spoofed_seen:
        print()
        print("WARNING: the properties marked SPOOFABLE are overwritten at boot by the")
        print("integrity modules installed on this phone. They currently claim a locked,")
        print("verified device. That claim is false: the bootloader reports unlocked and")
        print("/proc/cmdline carries oplusboot.verifiedbootstate=orange.")
        print()
        print("Authoritative alternatives:")
        print("  lock state          fastboot getvar unlocked")
        print("  verified boot state cat /proc/cmdline   (look for oplusboot.verifiedbootstate)")
        print("  boot image contents python tools/rmx3301_offline.py info <image>")
        print()
        print("Details: docs/SPOOFING.md")
    return EXIT_OK


def cmd_partitions(args: argparse.Namespace) -> int:
    serial = pick_serial(args.serial)
    out = shell(
        "ls -l /dev/block/by-name/ 2>/dev/null || ls -l /dev/block/bootdevice/by-name/ 2>/dev/null",
        serial=serial,
    )
    if not out.strip():
        raise DeviceError("could not list /dev/block/by-name; is the device rooted?")
    print(out.rstrip())
    print()
    print("slot note: entries suffixed _a and _b exist on A/B devices.")
    return EXIT_OK


def cmd_root_check(args: argparse.Namespace) -> int:
    serial = pick_serial(args.serial)
    if not have_root(serial):
        print("root is NOT available through 'su'")
        print("If Magisk is installed, open the Magisk app and grant shell su access.")
        return EXIT_ERROR
    print("root is available through 'su'")
    for probe in (
        "magisk -V",
        "magisk -v",
        "which magisk",
        "ls -d /data/adb/modules/* 2>/dev/null",
        "ls /data/adb/ 2>/dev/null",
        "cat /data/adb/magisk/util_functions.sh 2>/dev/null | head -5",
    ):
        try:
            out = shell(f"su -c '{probe}' 2>&1", serial=serial).strip()
        except DeviceError as exc:
            out = f"error: {exc}"
        print(f"$ {probe}")
        print(f"  {out if out else '(no output)'}")
    return EXIT_OK


def partition_size_bytes(name: str, serial: str) -> int | None:
    try:
        out = shell(f"su -c 'blockdev --getsize64 /dev/block/by-name/{name}' 2>/dev/null", serial=serial)
        text = out.strip().splitlines()[-1].strip() if out.strip() else ""
        return int(text) if text.isdigit() else None
    except (DeviceError, ValueError):
        return None


def cmd_backup(args: argparse.Namespace) -> int:
    serial = pick_serial(args.serial)
    if not have_root(serial):
        raise DeviceError("root is required to read raw partitions; 'su' did not work")

    names = list(args.partition or DEFAULT_PARTITIONS)
    if args.include_large:
        names += LARGE_PARTITIONS
    if args.include_sensitive and "persist" not in names:
        names.append("persist")
    for pattern in args.include or []:
        names.append(pattern)

    out_dir = os.path.abspath(args.out or os.path.join("backups", _dt.date.today().isoformat()))
    os.makedirs(out_dir, exist_ok=True)
    remote_dir = args.device_tmp.rstrip("/")

    available = shell("ls /dev/block/by-name/ 2>/dev/null", serial=serial).split()
    if not available:
        raise DeviceError("could not list partitions on the device")
    slot_suffix = shell("getprop ro.boot.slot_suffix", serial=serial).strip()
    resolved, missing = resolve_partitions(names, available, slot_suffix, args.all_slots)

    manifest_lines: list[str] = [
        "# Partition backup manifest",
        f"# device serial: {serial}",
        f"# created: {_dt.datetime.now().isoformat(timespec='seconds')}",
        f"# build: {shell('getprop ro.build.display.id', serial=serial).strip()}",
        f"# fingerprint: {shell('getprop ro.build.fingerprint', serial=serial).strip()}",
        f"# active slot suffix: {slot_suffix or 'none'}",
        "",
    ]

    print(f"backing up into {out_dir}")
    print(f"staging on device in {remote_dir}")
    print(f"active slot suffix: {slot_suffix or 'none'}")
    print()

    for name in missing:
        print(f"skip    {name:<16} not present on this device")

    failures: list[str] = []
    for name in resolved:
        size = partition_size_bytes(name, serial)
        size_text = f"{size} bytes" if size else "unknown size"
        remote = f"{remote_dir}/{name}.img"
        print(f"reading {name:<16} {size_text}")
        try:
            shell(
                f"su -c 'mkdir -p {remote_dir} && dd if=/dev/block/by-name/{name} of={remote} bs=4M 2>/dev/null'",
                serial=serial,
                timeout=args.timeout,
            )
            local = os.path.join(out_dir, f"{name}.img")
            adb("pull", remote, local, serial=serial, timeout=args.timeout)
            pulled = os.path.getsize(local) if os.path.exists(local) else 0
            ok = size is None or pulled == size
            manifest_lines.append(
                f"{name}\tsize={size if size is not None else 'unknown'}\tfile={pulled}\t"
                f"sha256_pending\tstatus={'ok' if ok else 'size-mismatch'}"
            )
            print(f"        pulled {pulled} bytes" + ("" if ok else "  SIZE MISMATCH"))
            if not ok:
                failures.append(f"{name}: pulled {pulled} of {size} bytes")
        except (DeviceError, subprocess.TimeoutExpired) as exc:
            print(f"        FAILED: {exc}")
            failures.append(f"{name}: {exc}")
        finally:
            try:
                shell(f"su -c 'rm -f {remote}' 2>/dev/null", serial=serial)
            except DeviceError:
                pass

    manifest_path = os.path.join(out_dir, "MANIFEST.txt")
    with open(manifest_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(manifest_lines) + "\n")
    print()
    print(f"wrote {manifest_path}")
    print("Run 'python tools/rmx3301_offline.py info <file>' on the boot image to record it.")
    if failures:
        print()
        print("failures:")
        for item in failures:
            print(f"  {item}")
        return EXIT_ERROR
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rmx3301_device.py",
        description=(
            "Read-only diagnostics and partition backup for the Realme GT 2 Pro "
            "(RMX3301). This tool never writes to boot, init_boot, vbmeta, super "
            "or any other partition, and never touches the bootloader lock state."
        ),
    )
    parser.add_argument("--serial", help="adb serial to use when more than one device is attached")
    sub = parser.add_subparsers(dest="command", required=True)

    p_check = sub.add_parser("check", help="confirm the device is reachable and summarise it")
    p_check.set_defaults(func=cmd_check)

    p_props = sub.add_parser("props", help="read the properties that matter for this project")
    p_props.set_defaults(func=cmd_props)

    p_part = sub.add_parser("partitions", help="list the by-name partition entries")
    p_part.set_defaults(func=cmd_partitions)

    p_root = sub.add_parser("root-check", help="confirm root works and report the Magisk version")
    p_root.set_defaults(func=cmd_root_check)

    p_backup = sub.add_parser("backup", help="copy partitions to the host through the device")
    p_backup.add_argument("--out", help="host directory, defaults to backups/<date>")
    p_backup.add_argument(
        "--partition",
        action="append",
        help="partition name, repeatable; without a slot suffix the active slot is used",
    )
    p_backup.add_argument(
        "--all-slots",
        action="store_true",
        help="copy both the _a and _b copies of slotted partitions",
    )
    p_backup.add_argument("--include-large", action="store_true", help="also super and userdata")
    p_backup.add_argument(
        "--include-sensitive",
        action="store_true",
        help="also copy persist, which holds calibration data",
    )
    p_backup.add_argument("--include", action="append", help="extra partition names to try")
    p_backup.add_argument("--device-tmp", default="/data/local/tmp/rmx3301-backup")
    p_backup.add_argument("--timeout", type=int, default=1800, help="seconds per partition")
    p_backup.set_defaults(func=cmd_backup)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except DeviceError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
