#!/bin/bash
# First-build driver for the pinned lineage-24.0 source graph.
# Scope: compile and package in an isolated tree. It does not apply device,
# recovery, migration or hardware acceptance checks.
set -eo pipefail
target=${1:?target required}
jobs=${2:-5}
case "$target" in nothing|otapackage|check-elf-files|codec2-provider|init-diagnostic) ;; *) exit 2;; esac
[[ "$jobs" =~ ^[1-9][0-9]*$ ]] || exit 2
test -f .realme-next-isolated.json
# This namespace's out/ is in the dedicated SSD store. Do not inherit another checkout's
# output/dist directory from the caller or service manager.
# Siso1.5.8 cannot load @config from an absolute config_repo_dir. Its config
# directory derives from OUT_DIR, so use Android's standard relative out path.
# The runner binds that exact path to the leased SSD cache before this script.
export OUT_DIR=out
unset OUT_DIR_COMMON_BASE
export DIST_DIR="$PWD/out/dist"
export XDG_CACHE_HOME="$PWD/out/.cache"
# systemd may omit HOME/XDG_CACHE_HOME. Keep Go's bootstrap cache in this run's
# isolated output tree, including when there is no inherited native output.
export GOCACHE="$PWD/out/.cache/go-build"
mkdir -p "$GOCACHE"
# Keep host-tool temporary data in this run's SSD-backed overlay.
export TMPDIR="$PWD/out/.tmp"
mkdir -p "$TMPDIR"
export BUILD_NUMBER=${4:?recorded build number required}
export BUILD_DATETIME=${5:?recorded UTC seconds required}
candidate_inputs=${6:?same-run inputs required}
if [[ "$target" == init-diagnostic ]]; then
    python3 "$(dirname "$0")/init_boot_trace_24.py" --source-tree "$PWD" \
        --candidate-inputs "$candidate_inputs" --report "${3%/*}/init-diagnostic-source.json"
fi
[[ "$BUILD_NUMBER" =~ ^RMX3301\.([0-9]+)\.[a-f0-9]{12}$ ]] || exit 2
[[ "$BUILD_DATETIME" == "${BASH_REMATCH[1]}" ]] || exit 2
if [[ "$target" == otapackage ]]; then
    # Refuse stale extraction or undersized launchers before the expensive build.
    python3 "$(dirname "$0")/../codec_store_abi_24.py" \
        --source-tree "$PWD" --candidate-inputs "$candidate_inputs" \
        --report "${3%/*}/codec2-source.json"
    python3 "$(dirname "$0")/../device_core_24.py" \
        --source-tree "$PWD" --candidate-inputs "$candidate_inputs" \
        --report "${3%/*}/device-core-source.json"
fi
source vendor/lineage/vars/aosp_target_release
test "$aosp_target_release" = cp2a
source build/envsetup.sh
export TARGET_PRODUCT=lineage_ferrari TARGET_BUILD_VARIANT=userdebug
export TARGET_RELEASE="$aosp_target_release" TARGET_DEVICE=ferrari TARGET_BUILD_APPS=
export LINEAGE_BUILD=ferrari
# Go runtime target, not a resident-RAM cap; the host's swap remains available.
export SOONG_GOMEMLIMIT=12884901888
if [[ "$target" == init-diagnostic ]] && \
    python3 "$(dirname "$0")/init_cached_graph_24.py" --source-tree "$PWD" \
        --candidate-inputs "$candidate_inputs" --report "${3%/*}/init-cached-graph.json"; then
    # Direct Ninja bypasses ConfigJavaEnvironment in Soong. Match its pinned
    # JDK21 default so generators such as xsdc do not pick the host's Java17.
    export JAVA_HOME="$PWD/prebuilts/jdk/jdk21/linux-x86"
    export ANDROID_JAVA_HOME="prebuilts/jdk/jdk21/linux-x86"
    export ANDROID_JAVA8_HOME="prebuilts/jdk/jdk8/linux-x86"
    export PATH="$JAVA_HOME/bin:$PATH"
    "$JAVA_HOME/bin/java" -version
    prebuilts/build-tools/linux-x86/bin/ninja -f out/combined-lineage_ferrari.ninja \
        -j"$jobs" out/target/product/ferrari/ramdisk/init out/target/product/ferrari/system/bin/init
    exit 0
fi
# Keep compiled objects across retries, while removing stale installed files
# and package staging from the preceding run of this same source baseline.
m installclean -j"$jobs"
if [[ "$target" == init-diagnostic ]]; then
    m init_first_stage init_second_stage -j"$jobs"
elif [[ "$target" == codec2-provider ]]; then
    # Measure the actual linked Android17 class ABI before correcting the
    # proprietary launchers. This target produces no OTA or hardware claim.
    m out/target/product/ferrari/vendor/lib64/libcodec2_hidl@1.0.so -j"$jobs"
elif [[ "$target" == otapackage ]]; then
    m check-elf-files plat_mac_permissions.xml -j"$jobs"
    firmware_report=${3:?firmware policy report required}
    python3 "$(dirname "$0")/../agm_calibration.py" \
        --soong-variables "out/soong/soong.${TARGET_PRODUCT}.variables" \
        --contract "$(dirname "$0")/../../configs/agm-calibration-24.0.json" \
        --report "${firmware_report%/*}/agm-configuration.json"
    m otapackage target-files-package module-info -j"$jobs"
    python3 "$(dirname "$0")/../firmware_policy.py" \
        --ota out/target/product/ferrari/lineage_ferrari-ota.zip \
        --target-files out/target/product/ferrari/obj/PACKAGING/target_files_intermediates/lineage_ferrari-target_files.zip \
        --expected-cert "$(dirname "$0")/../../certs/rmx3301-releasekey.x509.pem" \
        --report "$firmware_report"
    python3 "$(dirname "$0")/verify_vendor_24.py" \
        --target-files out/target/product/ferrari/obj/PACKAGING/target_files_intermediates/lineage_ferrari-target_files.zip \
        --candidate-inputs "$candidate_inputs" \
        --report "${firmware_report%/*}/vendor-package.json"
    python3 "$(dirname "$0")/../codec_store_abi_24.py" \
        --target-files out/target/product/ferrari/obj/PACKAGING/target_files_intermediates/lineage_ferrari-target_files.zip \
        --candidate-inputs "$candidate_inputs" \
        --report "${firmware_report%/*}/codec2-package.json"
    python3 "$(dirname "$0")/../build_identity.py" \
        --candidate-inputs "$candidate_inputs" \
        --ota out/target/product/ferrari/lineage_ferrari-ota.zip \
        --target-files out/target/product/ferrari/obj/PACKAGING/target_files_intermediates/lineage_ferrari-target_files.zip \
        --report "${firmware_report%/*}/build-identity.json"
    python3 "$(dirname "$0")/../device_core_24.py" \
        --target-files out/target/product/ferrari/obj/PACKAGING/target_files_intermediates/lineage_ferrari-target_files.zip \
        --candidate-inputs "$candidate_inputs" \
        --report "${firmware_report%/*}/device-core-package.json"
else
    m "$target" -j"$jobs"
fi
