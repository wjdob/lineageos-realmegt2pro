#!/bin/bash
# Bind the verified, migrated 24.0 store from the SSD-backed WSL filesystem.
set -euo pipefail
store=/mnt/lineage24-store
backing=/build/lineage24-store
if [ ! -d "$backing" ] || [ -L "$backing" ] || [ ! -f "$backing/storage-identity.json" ]; then
    echo "missing verified SSD 24.0 store: $backing" >&2
    exit 2
fi
mkdir -p "$store"
if ! mountpoint -q "$store"; then
    if [ -n "$(ls -A "$store")" ]; then
        echo "24.0 mountpoint contains unmounted data; preserve it" >&2
        exit 3
    fi
    mount --bind "$backing" "$store"
fi
script_dir=$(cd "$(dirname "$0")" && pwd)
python3 -c 'import sys;sys.path.insert(0,sys.argv[1]);from storage_24 import verify_store;verify_store()' "$script_dir"
echo "$store"
