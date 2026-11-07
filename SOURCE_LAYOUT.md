# Source repositories

This repository provides ROM downloads, installation guidance and user support.
Maintained source components are organized separately:

| Repository | Contents |
| --- | --- |
| [Device tree](https://github.com/wjdob/android_device_realme_ferrari/tree/lineage-23.2) | RMX3301 build definitions, device overlays and integration fixes |
| [SM8450 common](https://github.com/wjdob/android_device_oneplus_sm8450-common/tree/lineage-23.2) | Shared platform configuration and extraction support |
| [Pinned manifests](https://github.com/wjdob/lineageos-realmegt2pro-manifests/tree/lineage-23.2) | Exact source revisions, remaining framework patches and build prerequisites |
| [Optional apps](https://github.com/wjdob/realmegt2pro-oem-apps/tree/lineage-23.2) | Camera, Photos/editor and optional Clock compatibility/package source |

The device/common forks preserve pjgowtham's Git history. Their project commits
import the changes already recorded in the released source recipe. Unchanged kernel
projects remain pinned upstream; [Sources](SOURCES.md) links their full source archive.
Use matching `lineage-23.2` or `lineage-24.0` branches across repositories.
Clock's basic runtime tests cover Android17; Android16 reliability remains open.

For this branch, all four repositories have the immutable source tag `source-package23b-20261107`:

| Component | Commit |
| --- | --- |
| [android_device_realme_ferrari](https://github.com/wjdob/android_device_realme_ferrari/tree/source-package23b-20261107) | `c3a5d7fab59f3303606e10c77730d95439c836eb` |
| [android_device_oneplus_sm8450-common](https://github.com/wjdob/android_device_oneplus_sm8450-common/tree/source-package23b-20261107) | `b7e92722c113ebcc8fafbc6bfef0286a4ede3c17` |
| [lineageos-realmegt2pro-manifests](https://github.com/wjdob/lineageos-realmegt2pro-manifests/tree/source-package23b-20261107) | `1fe2bb35f020aabb51ad83473ec929494c20c4e4` |
| [realmegt2pro-oem-apps](https://github.com/wjdob/realmegt2pro-oem-apps/tree/source-package23b-20261107) | `bd7cbf928b3d3493edd941c22f9ff300c8c26163` |

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
