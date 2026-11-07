#!/bin/bash
# Keep mounting and the private build namespace in one WSL/service invocation.
set -euo pipefail
script_dir=$(cd "$(dirname "$0")" && pwd)
bash "$script_dir/mount_24.sh" >/dev/null
python3 -c 'import sys; sys.path.insert(0, sys.argv[1]); from storage_24 import verify_store, prepare_mountpoint; verify_store(); prepare_mountpoint()' "$script_dir"
exec /usr/bin/unshare --mount --propagation private "$@"
