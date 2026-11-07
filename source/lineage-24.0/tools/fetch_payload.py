#!/usr/bin/env python3
"""Download the payload.bin range of a Realme OTA package, resuming if partial.

Realme OTA zips store payload.bin uncompressed, so the payload can be fetched as
one contiguous HTTP range instead of downloading the whole archive. That also
makes the download resumable: read the current file size, ask for the remainder.

Read only against OPPO's CDN. Writes one local file.

    python tools/fetch_payload.py --url <zip url> --base 3044 \
        --length 7764686021 --out C:/Users/wdob/realmeGT2Pro-dev/ota/payload.bin
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import urllib.request

CHUNK = 1 << 22


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", required=True, help="URL of the OTA zip, or of payload.bin directly")
    parser.add_argument("--base", type=int, default=0, help="byte offset of payload.bin inside the zip")
    parser.add_argument("--length", type=int, required=True, help="size of payload.bin in bytes")
    parser.add_argument("--out", required=True, help="local file to write")
    args = parser.parse_args(argv)

    have = os.path.getsize(args.out) if os.path.exists(args.out) else 0
    if have >= args.length:
        print(f"already complete: {have:,} bytes")
        return 0
    if have:
        print(f"resuming from {have:,} of {args.length:,} ({have / args.length * 100:.1f}%)", flush=True)

    req = urllib.request.Request(args.url)
    req.add_header("Range", f"bytes={args.base + have}-{args.base + args.length - 1}")
    req.add_header("User-Agent", "Mozilla/5.0 (compatible; rmx3301-offline-tooling)")

    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    written = have
    started = time.time()
    last_report = 0.0
    with urllib.request.urlopen(req, timeout=300) as resp, open(args.out, "ab") as fh:
        while True:
            block = resp.read(CHUNK)
            if not block:
                break
            fh.write(block)
            written += len(block)
            pct = written / args.length * 100
            if pct - last_report >= 5:
                last_report = pct
                rate = (written - have) / max(time.time() - started, 1) / 1e6
                print(f"{pct:5.1f}%  {written:,} / {args.length:,}  {rate:.1f} MB/s", flush=True)

    print(f"done: {written:,} bytes in {time.time() - started:.0f}s")
    if written != args.length:
        print(f"warning: expected {args.length:,} bytes, got {written:,}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())