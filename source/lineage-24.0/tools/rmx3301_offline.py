#!/usr/bin/env python3
"""Offline boot image analysis for the Realme GT 2 Pro project.

Everything this tool does happens on files on disk. It has no code that talks to
a phone, and deliberately no way to flash, erase or lock anything.

Examples:

    python tools/rmx3301_offline.py info references/boot.img
    python tools/rmx3301_offline.py identity references/boot.img
    python tools/rmx3301_offline.py ramdisk references/boot.img --list
    python tools/rmx3301_offline.py compare stock.img patched.img
    python tools/rmx3301_offline.py verify-match stock.img magisk_patched.img
    python tools/rmx3301_offline.py extract-ramdisk boot.img --out ./out
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bootimg import bootimage  # noqa: E402

EXIT_OK = 0
EXIT_MISMATCH = 2
EXIT_ERROR = 3


def exact_bytes(value: int | None) -> str:
    """Byte count with separators. Use this whenever two values are compared.

    Rounded sizes hide small differences, such as the 16 byte kernel change seen
    between two firmware builds for this phone, and that difference is what
    decides whether an image belongs to the installed build.
    """

    if value is None:
        return "-"
    return f"{value:,}"


def human_size(value: int | None) -> str:
    if value is None:
        return "-"
    size = float(value)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if size < 1024 or unit == "GiB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{value} B"


def print_info(image: bootimage.BootImage, *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(image.as_dict(), indent=2, sort_keys=False))
        return

    rows = [
        ("file", image.path),
        ("size", human_size(image.file_size)),
        ("sha256", image.sha256),
        ("sha1", image.sha1),
        ("header version", str(image.header_version)),
        ("page size", str(image.page_size)),
        ("boot image os version", image.os_version_str),
        ("kernel version", image.kernel_version or "not found"),
        ("kernel size", human_size(image.kernel.size)),
        ("kernel compression", image.kernel.compression or "none"),
        ("ramdisk size", human_size(image.ramdisk.size)),
        ("ramdisk compression", image.ramdisk.compression or "none"),
        ("ramdisk unpacked", human_size(image.ramdisk.unpacked_size)),
        ("cmdline", image.cmdline or "(empty)"),
    ]
    if image.avb_footer:
        rows.append(("AVB image size", human_size(image.avb_footer.original_image_size)))
        rows.append(
            ("AVB vbmeta", f"offset {image.avb_footer.vbmeta_offset}, {image.avb_footer.vbmeta_size} bytes")
        )
    width = max(len(k) for k, _ in rows)
    for key, value in rows:
        print(f"{key.ljust(width)}  {value}")

    identity = image.identity()
    if identity:
        print()
        print("identity from ramdisk build.prop")
        width = max(len(k) for k in identity)
        for key, value in identity.items():
            print(f"  {key.ljust(width)}  {value}")

    markers = image.patch_markers()
    if any(markers.values()):
        print()
        print("patch markers")
        if markers.get("magisk"):
            info = markers["magisk"]
            print("  magisk          yes")
            if info.get("magiskinit_size"):
                print(f"  magiskinit      {human_size(info['magiskinit_size'])}")
            for key, value in (info.get("config") or {}).items():
                print(f"  {key.ljust(15)} {value}")
            if info.get("overlay"):
                print(f"  overlay         {', '.join(info['overlay'])}")
        if markers.get("kernelsu"):
            print("  kernelsu        yes")
        if markers.get("apatch"):
            print("  apatch          yes")
    else:
        print()
        print("patch markers     none, this looks like a stock image")

    if image.notes:
        print()
        for note in image.notes:
            print(f"note: {note}")


def cmd_info(args: argparse.Namespace) -> int:
    if bootimage.is_vendor_boot(args.image):
        image = bootimage.load_vendor_boot(args.image, read_ramdisk=True)
        if args.json:
            print(json.dumps(image.as_dict(), indent=2))
            return EXIT_OK
        data = image.as_dict()
        width = max(len(k) for k in ("path", "size", "sha256", "sha1", "kind", "header version",
                                     "page size", "vendor ramdisk", "vendor ramdisk unpacked",
                                     "ramdisk entries", "dtb", "cmdline"))
        rows = [
            ("path", data["path"]),
            ("kind", "vendor_boot"),
            ("size", human_size(data["file_size"])),
            ("sha256", data["sha256"]),
            ("sha1", data["sha1"]),
            ("header version", str(data["header_version"])),
            ("page size", str(data["page_size"])),
            ("vendor ramdisk", f"{exact_bytes(data['vendor_ramdisk']['size'])} bytes, "
                               f"{data['vendor_ramdisk']['compression'] or 'none'}"),
            ("vendor ramdisk unpacked", exact_bytes(data["vendor_ramdisk"]["unpacked_size"])),
            ("ramdisk table entries", str(len(data["ramdisk_table"]))),
            ("dtb", exact_bytes(data["dtb_size"]) if image.dtb is None
                    else f"{exact_bytes(image.dtb.size)} bytes (header said {exact_bytes(data['dtb_size'])})"),
            ("cmdline", data["cmdline"] or "(empty)"),
        ]
        for key, value in rows:
            print(f"{key.ljust(width)}  {value}")
        entries = image.ramdisk_entries()
        print(f"{'ramdisk entries'.ljust(width)}  {len(entries)}")
        if data["avb_footer"]:
            print(f"{'AVB image size'.ljust(width)}  {human_size(data['avb_footer']['original_image_size'])}")
        for note in image.notes:
            print(f"note: {note}")
        return EXIT_OK

    image = bootimage.load(args.image, read_ramdisk=True, read_kernel=False)
    print_info(image, as_json=args.json)
    return EXIT_OK


def cmd_identity(args: argparse.Namespace) -> int:
    image = bootimage.load(args.image, read_ramdisk=True)
    identity = image.identity()
    if not identity:
        print("no bootimage build.prop found in the ramdisk", file=sys.stderr)
        return EXIT_ERROR
    if args.json:
        print(json.dumps(identity, indent=2))
    else:
        width = max(len(k) for k in identity)
        for key, value in identity.items():
            print(f"{key.ljust(width)}  {value}")
    return EXIT_OK


def cmd_ramdisk(args: argparse.Namespace) -> int:
    if bootimage.is_vendor_boot(args.image):
        vendor = bootimage.load_vendor_boot(args.image, read_ramdisk=True)
        entries = vendor.ramdisk_entries()
        if not entries:
            print("vendor ramdisk could not be unpacked", file=sys.stderr)
            for note in vendor.notes:
                print(f"  {note}", file=sys.stderr)
            return EXIT_ERROR
        if args.json:
            print(json.dumps([{"name": e.name, "size": e.size} for e in entries], indent=2))
            return EXIT_OK
        for entry in entries:
            kind = "dir " if entry.is_dir else "link" if entry.is_symlink else "file"
            print(f"{kind}  {entry.size:>10}  {entry.name}")
        return EXIT_OK

    image = bootimage.load(args.image, read_ramdisk=True)
    entries = image.ramdisk_entries()
    if not entries:
        print("ramdisk could not be unpacked", file=sys.stderr)
        for note in image.notes:
            print(f"  {note}", file=sys.stderr)
        return EXIT_ERROR
    if args.json:
        print(json.dumps([{"name": e.name, "size": e.size, "mode": oct(e.mode)} for e in entries], indent=2))
        return EXIT_OK
    if args.dump:
        for entry in entries:
            print(f"{entry.name}\t{entry.size}")
        return EXIT_OK
    for entry in entries:
        kind = "dir " if entry.is_dir else "link" if entry.is_symlink else "file"
        print(f"{kind}  {entry.size:>10}  {entry.name}")
    return EXIT_OK


def cmd_extract_ramdisk(args: argparse.Namespace) -> int:
    image = bootimage.load(args.image, read_ramdisk=True)
    payload = image.ramdisk.unpacked
    if payload is None:
        print("ramdisk could not be unpacked", file=sys.stderr)
        return EXIT_ERROR
    out_dir = os.path.abspath(args.out)
    os.makedirs(out_dir, exist_ok=True)
    name = os.path.basename(args.image) + ".ramdisk"
    path = os.path.join(out_dir, name)
    with open(path, "wb") as fh:
        fh.write(payload)
    print(f"wrote {path} ({human_size(len(payload))})")
    if args.expand:
        for entry in image.ramdisk_entries():
            if entry.is_dir or not entry.name or entry.name.startswith("."):
                continue
            target = os.path.join(out_dir, os.path.basename(args.image) + ".tree", entry.name)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            if not entry.is_symlink:
                with open(target, "wb") as fh:
                    fh.write(entry.data)
        print(f"expanded into {os.path.join(out_dir, os.path.basename(args.image) + '.tree')}")
    return EXIT_OK


def compare_images(a: bootimage.BootImage, b: bootimage.BootImage) -> list[tuple[str, str, str, bool]]:
    """Return (field, value a, value b, same) rows."""

    def os_full(image: bootimage.BootImage) -> str:
        # The fourth field is the patch level. It separates otherwise identical
        # builds, so it must be visible rather than rounded into "12.0.0".
        if not image.os_version:
            return "unknown"
        major, minor, patch, level = image.os_version
        return f"{major}.{minor}.{patch} patch-level {level}"

    rows = [
        ("sha256", a.sha256 or "-", b.sha256 or "-", a.sha256 == b.sha256),
        ("sha1", a.sha1, b.sha1, a.sha1 == b.sha1),
        ("header version", str(a.header_version), str(b.header_version), a.header_version == b.header_version),
        ("boot image os version", os_full(a), os_full(b), a.os_version == b.os_version),
        ("kernel version", a.kernel_version or "-", b.kernel_version or "-", a.kernel_version == b.kernel_version),
        (
            "kernel size",
            exact_bytes(a.kernel.size),
            exact_bytes(b.kernel.size),
            a.kernel.size == b.kernel.size,
        ),
        ("kernel sha256", a.kernel.sha256 or "-", b.kernel.sha256 or "-", a.kernel.sha256 == b.kernel.sha256),
        (
            "ramdisk size",
            exact_bytes(a.ramdisk.size),
            exact_bytes(b.ramdisk.size),
            a.ramdisk.size == b.ramdisk.size,
        ),
        (
            "ramdisk unpacked sha256",
            a.ramdisk.sha256 or "-",
            b.ramdisk.sha256 or "-",
            a.ramdisk.sha256 == b.ramdisk.sha256,
        ),
        ("cmdline", a.cmdline or "(empty)", b.cmdline or "(empty)", a.cmdline == b.cmdline),
    ]
    ident_a = a.identity()
    ident_b = b.identity()
    for key in (
        "device",
        "build.fingerprint",
        "build.version.release",
        "build.version.sdk",
        "build.date",
    ):
        rows.append(
            (
                f"identity.{key}",
                ident_a.get(key, "-"),
                ident_b.get(key, "-"),
                ident_a.get(key) == ident_b.get(key),
            )
        )
    return rows


def cmd_compare(args: argparse.Namespace) -> int:
    a = bootimage.load(args.a, read_ramdisk=True)
    b = bootimage.load(args.b, read_ramdisk=True)
    rows = compare_images(a, b)
    if args.json:
        print(json.dumps([{"field": f, "a": x, "b": y, "same": s} for f, x, y, s in rows], indent=2))
        return EXIT_OK
    width = max(len(f) for f, _, _, _ in rows)
    same_count = 0
    for field, left, right, same in rows:
        mark = "same" if same else "DIFF"
        if same:
            same_count += 1
        print(f"{mark}  {field.ljust(width)}  {left}  |  {right}")
    print()
    print(f"{same_count} of {len(rows)} fields match")
    return EXIT_OK


def cmd_verify_match(args: argparse.Namespace) -> int:
    """Confirm a patched image was built from a given stock image.

    Magisk records the SHA1 of the whole stock boot image in .backup/.magisk.
    Matching that against the candidate stock file is proof of provenance, which
    is stronger than comparing headers.
    """

    stock = bootimage.load(args.stock, read_ramdisk=False)
    patched = bootimage.load(args.patched, read_ramdisk=True)
    markers = patched.patch_markers()
    recorded = ((markers.get("magisk") or {}).get("config") or {}).get("SHA1")

    print(f"stock   {stock.path}")
    print(f"        sha1 {stock.sha1}")
    print(f"patched {patched.path}")
    print(f"        sha1 {patched.sha1}")
    print()

    problems: list[str] = []

    if not markers.get("magisk"):
        print("patched image has no Magisk markers; is it really patched?")
        problems.append("no magisk markers")
    elif not recorded:
        print("patched image has Magisk markers but no recorded stock SHA1")
        problems.append("no recorded sha1")
    else:
        print(f"recorded stock sha1 {recorded}")
        if recorded == stock.sha1:
            print("MATCH: the patched ramdisk came from this exact stock image")
        else:
            print("MISMATCH: the patched ramdisk came from a different stock image")
            problems.append("sha1 mismatch")

    if stock.kernel.sha256 and patched.kernel.sha256:
        if stock.kernel.sha256 == patched.kernel.sha256:
            print("kernel matches, which is expected for a Magisk patch")
        else:
            print("note: kernels differ, so this is not a plain Magisk patch of that stock image")
            problems.append("kernel differs")

    if stock.os_version != patched.os_version:
        print(
            "note: boot image os version differs "
            f"({stock.os_version} vs {patched.os_version}); the fourth field is the patch level"
        )
        problems.append("os version differs")
    if stock.kernel.size != patched.kernel.size:
        print(
            "note: kernel size differs "
            f"({exact_bytes(stock.kernel.size)} vs {exact_bytes(patched.kernel.size)} bytes), "
            "which alone is enough to say these are not the same build"
        )

    ident = patched.identity()
    print()
    print("patched image identity")
    if ident:
        for key, value in ident.items():
            print(f"  {key}: {value}")
    else:
        print("  no identity found in the ramdisk")

    print()
    if problems:
        print("RESULT: not a verified match (" + ", ".join(problems) + ")")
        return EXIT_MISMATCH
    print("RESULT: verified match")
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rmx3301_offline.py",
        description=(
            "Read-only analysis of Android boot images. This tool cannot flash, "
            "erase or lock anything; it only reads files on disk."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_info = sub.add_parser("info", help="show everything known about a boot image")
    p_info.add_argument("image")
    p_info.add_argument("--json", action="store_true", help="emit JSON")
    p_info.set_defaults(func=cmd_info)

    p_ident = sub.add_parser("identity", help="show the device and build identity")
    p_ident.add_argument("image")
    p_ident.add_argument("--json", action="store_true")
    p_ident.set_defaults(func=cmd_identity)

    p_ram = sub.add_parser("ramdisk", help="list the ramdisk contents")
    p_ram.add_argument("image")
    p_ram.add_argument("--json", action="store_true")
    p_ram.add_argument("--dump", action="store_true", help="name and size only, tab separated")
    p_ram.set_defaults(func=cmd_ramdisk)

    p_ext = sub.add_parser("extract-ramdisk", help="write the unpacked ramdisk to disk")
    p_ext.add_argument("image")
    p_ext.add_argument("--out", default="out")
    p_ext.add_argument("--expand", action="store_true", help="also write out every file in the archive")
    p_ext.set_defaults(func=cmd_extract_ramdisk)

    p_cmp = sub.add_parser("compare", help="compare two boot images")
    p_cmp.add_argument("a")
    p_cmp.add_argument("b")
    p_cmp.add_argument("--json", action="store_true")
    p_cmp.set_defaults(func=cmd_compare)

    p_ver = sub.add_parser("verify-match", help="prove a patched image came from a given stock image")
    p_ver.add_argument("stock")
    p_ver.add_argument("patched")
    p_ver.set_defaults(func=cmd_verify_match)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except bootimage.BootImageError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
