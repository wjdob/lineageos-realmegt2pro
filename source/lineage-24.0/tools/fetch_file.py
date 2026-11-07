#!/usr/bin/env python3
"""Download a whole file with HTTP range requests, resuming if partial.

Read only against the remote server. Writes one local file.

    python tools/fetch_file.py --url <url> --out C:/Users/wdob/realmeGT2Pro-dev/ota/package.zip
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import urllib.request

CHUNK = 1 << 22


def remote_size(url: str) -> int:
    req = urllib.request.Request(url, method="HEAD")
    req.add_header("User-Agent", "Mozilla/5.0 (compatible; rmx3301-offline-tooling)")
    with urllib.request.urlopen(req, timeout=60) as resp:
        return int(resp.headers["Content-Length"])


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--size", type=int, help="expected size; probed with HEAD if omitted")
    args = parser.parse_args(argv)

    total = args.size or remote_size(args.url)
    have = os.path.getsize(args.out) if os.path.exists(args.out) else 0
    if have >= total:
        print(f"already complete: {have:,} bytes")
        return 0
    if have:
        print(f"resuming from {have:,} of {total:,} ({have / total * 100:.1f}%)", flush=True)

    req = urllib.request.Request(args.url)
    req.add_header("Range", f"bytes={have}-{total - 1}")
    req.add_header("User-Agent", "Mozilla/5.0 (compatible; rmx3301-offline-tooling)")

    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    written = have
    started = time.time()
    last = 0.0
    with urllib.request.urlopen(req, timeout=300) as resp, open(args.out, "ab") as fh:
        while True:
            block = resp.read(CHUNK)
            if not block:
                break
            fh.write(block)
            written += len(block)
            pct = written / total * 100
            if pct - last >= 5:
                last = pct
                rate = (written - have) / max(time.time() - started, 1) / 1e6
                print(f"{pct:5.1f}%  {written:,} / {total:,}  {rate:.1f} MB/s", flush=True)

    print(f"done: {written:,} bytes in {time.time() - started:.0f}s")
    if written != total:
        print(f"warning: expected {total:,}, got {written:,}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())