#!/bin/bash
# Sync the pinned lineage-24.0 graph into the dedicated SSD ext4 store.
# The store is 24.0-only; /build/lineage (23.2) is never used for 24.0 data.
set -e
script_dir=$(cd "$(dirname "$0")" && pwd)
repo_root=$(cd "$script_dir/../.." && pwd)
store=/mnt/lineage24-store

bash "$script_dir/mount_24.sh" >/dev/null
python3 "$script_dir/preflight_24.py" --phase sync
mkdir -p "$store/tmp" "$store/manifests"
export TMPDIR="$store/tmp"

manifest_src="$repo_root/manifests/lineage-24.0-candidate.xml"
manifest_repo="$store/manifests"
if [ ! -d "$manifest_repo/.git" ]; then
    git init -q -b lineage-24.0 "$manifest_repo"
fi
cp "$manifest_src" "$manifest_repo/lineage-24.0-candidate.xml"
if ! git -C "$manifest_repo" diff --quiet -- lineage-24.0-candidate.xml ||
   ! git -C "$manifest_repo" ls-files --error-unmatch lineage-24.0-candidate.xml >/dev/null 2>&1; then
    git -C "$manifest_repo" add lineage-24.0-candidate.xml
    git -C "$manifest_repo" -c user.name=lineage24 -c user.email=lineage24@localhost \
        commit -qm "Pinned lineage-24.0 source manifest"
fi

mkdir -p "$store/tree"
cd "$store/tree"
# Always re-init so manifest edits are applied without discarding fetched objects.
/opt/bin/repo init -q -u "file://$manifest_repo" -b lineage-24.0 \
    -m lineage-24.0-candidate.xml
exec > "$store/sync.log" 2>&1
echo "sync started $(date -u +%Y-%m-%dT%H:%M:%SZ)"
set +e
/opt/bin/repo sync -c -j16 --no-clone-bundle --no-tags
rc=$?
set -e
echo "sync finished $(date -u +%Y-%m-%dT%H:%M:%SZ) rc=$rc"
exit $rc
