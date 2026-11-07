#!/bin/bash
set -eo pipefail
target=${1:?target required}
jobs=${2:-5}
case "$target" in recoveryimage|otapackage|nothing) ;; *) echo 'unsupported target' >&2; exit 2;; esac
[[ "$jobs" =~ ^[1-9][0-9]*$ ]] || exit 2
test -f .realme-next-isolated.json
source build/envsetup.sh
export TARGET_PRODUCT=lineage_ferrari TARGET_BUILD_VARIANT=userdebug TARGET_RELEASE=bp2a TARGET_DEVICE=ferrari TARGET_BUILD_APPS=
# Byte count forwarded through Soong's otherwise empty primary-builder environment.
# This is a soft Go-runtime limit, not a process/cgroup memory guarantee.
export SOONG_GOMEMLIMIT=21474836480
if [[ "$target" == otapackage ]]; then
    # The OTA alone does not expose module-to-partition mappings for G5 review.
    m otapackage target-files-package module-info -j"$jobs"
else
    m "$target" -j"$jobs"
fi
