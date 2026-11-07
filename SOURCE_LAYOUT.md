# Source repositories

This repository provides ROM downloads, installation guidance and user support.
Maintained source components are organized separately:

| Repository | Contents |
| --- | --- |
| [Device tree](https://github.com/wjdob/android_device_realme_ferrari/tree/lineage-24.0) | RMX3301 build definitions, device overlays and integration fixes |
| [SM8450 common](https://github.com/wjdob/android_device_oneplus_sm8450-common/tree/lineage-24.0) | Shared platform configuration and extraction support |
| [Pinned manifests](https://github.com/wjdob/lineageos-realmegt2pro-manifests/tree/lineage-24.0) | Exact source revisions, remaining framework patches and build prerequisites |
| [Optional apps](https://github.com/wjdob/realmegt2pro-oem-apps/tree/lineage-24.0) | Camera, Photos/editor and optional Clock compatibility/package source |

The device/common forks preserve pjgowtham's Git history. Their project commits
import the changes already recorded in the released source recipe. Unchanged kernel
projects remain pinned upstream; [Sources](SOURCES.md) links their full source archive.
Use matching `lineage-23.2` or `lineage-24.0` branches across repositories.
Clock's basic runtime tests cover Android17; Android16 reliability remains open.

For this branch, all four repositories have the immutable source tag `source-native25-20261107`:

| Component | Commit |
| --- | --- |
| [android_device_realme_ferrari](https://github.com/wjdob/android_device_realme_ferrari/tree/source-native25-20261107) | `7b6186c70a9370884f156df15b07827d90467fb1` |
| [android_device_oneplus_sm8450-common](https://github.com/wjdob/android_device_oneplus_sm8450-common/tree/source-native25-20261107) | `19a47fb1b97dd06be6d73f21cfc547ede1b79f74` |
| [lineageos-realmegt2pro-manifests](https://github.com/wjdob/lineageos-realmegt2pro-manifests/tree/source-native25-20261107) | `c11b0b4a50e61e2da3f139de5834f2f6b700f338` |
| [realmegt2pro-oem-apps](https://github.com/wjdob/realmegt2pro-oem-apps/tree/source-native25-20261107) | `120ee630a3054077e14ddc9bb3224e347f83f29f` |

The original release source kits, tags, checksums and downloads remain available.
The component split changes no released binary or installation procedure. Hash
checks establish source-content equivalence; no new native rebuild is claimed.

Builds still need matching proprietary stock inputs, the pinned Android tools and
your own signing identity. The manifest's README describes these prerequisites
and the remaining patch-staging step. A manifest sync alone is insufficient.

Report phone problems through this repository's issue forms. Submit source changes
as PRs to the relevant component repository. Include the affected LineageOS version
and reference the user issue where applicable. The manifest pins a reviewed release
cohort, so coordinate changes there before producing a new bundled build.
