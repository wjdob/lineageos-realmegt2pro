#!/bin/bash
set -eo pipefail
target=${1:?target required}
jobs=${2:-5}
case "$target" in recoveryimage|dtboimage|otapackage|nothing|check-elf-files) ;; *) exit 2;; esac
[[ "$jobs" =~ ^[1-9][0-9]*$ ]] || exit 2
test -f .realme-next-isolated.json
# systemd may omit HOME/XDG_CACHE_HOME. Keep Go's bootstrap cache in this run's
# isolated output tree, including when there is no inherited native output.
export GOCACHE="$PWD/out/.cache/go-build"
mkdir -p "$GOCACHE"
export BUILD_NUMBER=${4:?recorded build number required}
export BUILD_DATETIME=${5:?recorded UTC seconds required}
candidate_inputs=${6:?same-run inputs required}
[[ "$BUILD_NUMBER" =~ ^RMX3301\.([0-9]+)\.[a-f0-9]{12}$ ]] || exit 2
[[ "$BUILD_DATETIME" == "${BASH_REMATCH[1]}" ]] || exit 2
# This file is checked against its pinned source by the candidate runner.
source vendor/lineage/vars/aosp_target_release
test "$aosp_target_release" = bp4a
source build/envsetup.sh
export TARGET_PRODUCT=lineage_ferrari TARGET_BUILD_VARIANT=userdebug
export TARGET_RELEASE="$aosp_target_release" TARGET_DEVICE=ferrari TARGET_BUILD_APPS=
export LINEAGE_BUILD=ferrari
# Go runtime target, not a resident-RAM cap; the host's swap remains available.
export SOONG_GOMEMLIMIT=12884901888
if [[ "$target" == otapackage ]]; then
    m check-elf-files plat_mac_permissions.xml -j"$jobs"
    firmware_report=${3:?firmware policy report required}
    python3 "$(dirname "$0")/../agm_calibration.py" \
        --soong-variables "out/soong/soong.${TARGET_PRODUCT}.variables" \
        --contract "$(dirname "$0")/../../configs/agm-calibration-23.2.json" \
        --report "${firmware_report%/*}/agm-configuration.json"
    m otapackage target-files-package module-info -j"$jobs"
    python3 "$(dirname "$0")/../build_identity.py" \
        --candidate-inputs "$candidate_inputs" \
        --ota out/target/product/ferrari/lineage_ferrari-ota.zip \
        --target-files out/target/product/ferrari/obj/PACKAGING/target_files_intermediates/lineage_ferrari-target_files.zip \
        --report "${firmware_report%/*}/build-identity.json"
    python3 "$(dirname "$0")/../health_current.py" \
        --source-tree . \
        --target-files out/target/product/ferrari/obj/PACKAGING/target_files_intermediates/lineage_ferrari-target_files.zip \
        --report "${firmware_report%/*}/health-current-packaged.json"
    python3 "$(dirname "$0")/../display_resources.py" \
        --target-files out/target/product/ferrari/obj/PACKAGING/target_files_intermediates/lineage_ferrari-target_files.zip \
        --aapt2 prebuilts/sdk/tools/linux/bin/aapt2 \
        --report "${firmware_report%/*}/display-resources-packaged.json"
    python3 "$(dirname "$0")/../addon_update_contract.py" \
        --target-files out/target/product/ferrari/obj/PACKAGING/target_files_intermediates/lineage_ferrari-target_files.zip \
        --certificate "$(dirname "$0")/../../certs/rmx3301-releasekey.x509.pem" \
        --report "${firmware_report%/*}/addon-update-contract.json"
    python3 "$(dirname "$0")/../fingerprint_memory.py" \
        --target-files out/target/product/ferrari/obj/PACKAGING/target_files_intermediates/lineage_ferrari-target_files.zip \
        --report "${firmware_report%/*}/fingerprint-memory-packaged.json"
    python3 "$(dirname "$0")/../firmware_policy.py" \
        --ota out/target/product/ferrari/lineage_ferrari-ota.zip \
        --target-files out/target/product/ferrari/obj/PACKAGING/target_files_intermediates/lineage_ferrari-target_files.zip \
        --expected-cert "$(dirname "$0")/../../certs/rmx3301-releasekey.x509.pem" \
        --report "${3:?firmware policy report required}"
else
    m "$target" -j"$jobs"
    if [[ "$target" == dtboimage ]]; then
        report_path=${3:?run report path required}
        python3 "$(dirname "$0")/../fingerprint_memory.py" \
            --dtb-image out/target/product/ferrari/dtb.img \
            --dtbo out/target/product/ferrari/dtbo.img \
            --report "${report_path%/*}/fingerprint-memory-dtbo.json"
    fi
fi
