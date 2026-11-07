# Sources and credits

## Source repositories

| Repository | Contents |
| --- | --- |
| [Realme GT2 Pro device tree](https://github.com/wjdob/android_device_realme_ferrari/tree/lineage-23.2) | Device configuration, overlays and extraction scripts |
| [SM8450 common](https://github.com/wjdob/android_device_oneplus_sm8450-common/tree/lineage-23.2) | Shared platform configuration and extraction support |
| [Build manifests](https://github.com/wjdob/lineageos-realmegt2pro-manifests/tree/lineage-23.2) | Pinned source versions, remaining patches and build preparation |
| [Optional Realme apps](https://github.com/wjdob/realmegt2pro-oem-apps/tree/lineage-23.2) | Camera, Photos/editor and Clock compatibility tools |

Use matching version branches. For Package-23b, the source tag is **`source-package23b-20261107`**:

| Repository | Commit |
| --- | --- |
| [android_device_realme_ferrari](https://github.com/wjdob/android_device_realme_ferrari/tree/source-package23b-20261107) | `c3a5d7fab59f3303606e10c77730d95439c836eb` |
| [android_device_oneplus_sm8450-common](https://github.com/wjdob/android_device_oneplus_sm8450-common/tree/source-package23b-20261107) | `b7e92722c113ebcc8fafbc6bfef0286a4ede3c17` |
| [lineageos-realmegt2pro-manifests](https://github.com/wjdob/lineageos-realmegt2pro-manifests/tree/source-package23b-20261107) | `1fe2bb35f020aabb51ad83473ec929494c20c4e4` |
| [realmegt2pro-oem-apps](https://github.com/wjdob/realmegt2pro-oem-apps/tree/source-package23b-20261107) | `bd7cbf928b3d3493edd941c22f9ff300c8c26163` |

Build prerequisites and source commands are in the manifest repository's README.
Rebuilding requires matching stock files and your own signing keys. A complete
rebuild using the new component manifests has not yet been tested.

The original [release source kit](source/README.md)
contains the original manifests, patches and file hashes. The source-tag versions
remain available for inspecting the release.

## Kernel

Package-23b uses **Linux 5.10.246-gki-g914935583f0c**, based on pjgowtham's SM8450 work.

| Tree | Revision |
| --- | --- |
| [Kernel](https://github.com/pjgowtham/android_kernel_oneplus_sm8450/tree/914935583f0ce199114a4a1f31178ab25a3a052d) | `914935583f0ce199114a4a1f31178ab25a3a052d` |
| [Device trees](https://github.com/pjgowtham/android_kernel_oneplus_sm8450-devicetrees/tree/d8f3eb3fe8f98facd9669aa97d1247f6580e1e58) | `d8f3eb3fe8f98facd9669aa97d1247f6580e1e58` |
| [Modules](https://github.com/pjgowtham/android_kernel_oneplus_sm8450-modules/tree/ca1104519fcb7e769129e75458a9da4833bcc751) | `ca1104519fcb7e769129e75458a9da4833bcc751` |

Download the [complete kernel source archive](https://github.com/wjdob/lineageos-realmegt2pro/releases/download/lineage-23.2-rmx3301-23b-20261103/kernel-source-RMX3301-package23b.tar.gz).
It includes all three trees, license texts, the applied trusted-app memory change,
and the build configuration in `release/kernel_configs.txt` and `kernel_version.txt`.
The kernel and module trees are unchanged upstream sources. The device-tree patch restores the stock trusted-app memory reservation.

To inspect kernel history:

```sh
git clone https://github.com/pjgowtham/android_kernel_oneplus_sm8450.git
cd android_kernel_oneplus_sm8450
git checkout --detach 914935583f0ce199114a4a1f31178ab25a3a052d
git show --stat HEAD
```

## Credits and licensing

This port builds on **pjgowtham's** device, SM8450 common, Oplus and kernel work,
with **LineageOS, AOSP, Qualcomm/Oplus** and other upstream contributors.

[Changes and credits](CHANGES.md) identifies upstream fixes and project additions.

Original licenses and copyright notices remain in place. OEM apps, libraries,
models and assets retain their owners' rights. Extract proprietary inputs from
your own matching firmware. Signing keys are supplied separately.

## Contributions

Report phone problems through this repository's [issue forms](https://github.com/wjdob/lineageos-realmegt2pro/issues/new/choose).
Submit code changes to the relevant source repository and include the LineageOS version.

## Lens package source

The Lens app-package revision uses [this source commit](https://github.com/wjdob/realmegt2pro-oem-apps/tree/71c055dc4aa5fea454b7fbd7aacedfdc65ab78e9)
and tag `camera-lens16-api36-20261107`.
Its recipe is `configs/oem-addons-lens16-23.2.json` in that repository.
The ROM and kernel source versions above still describe the shipped OTA.
