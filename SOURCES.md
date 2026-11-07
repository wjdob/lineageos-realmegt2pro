# Sources

Native25 uses the [pinned manifest](source/lineage-24.0/manifests/lineage-24.0-candidate.xml)
and [recipe](source/lineage-24.0/tools/build/recipe-24.0.json). The frozen ROM build
checkpoint is `cc7a266aab79592c9f2470a04f9bfc5f9557c385`. API37 Camera/Photos inputs
come from `7121ac8384917586f884055ddf3825983aef523e`; Clock alpha5 comes from
`5a3951b6e1c9e909372e18ae46340997a6c7e3ae`. The public source kit has its own Git
history; [provenance](source/lineage-24.0/PROVENANCE.json) binds each exported file.
Build-input status text is preserved; `release.json` records later device validation.

## Kernel

Linux **5.10.246-gki-g914935583f0c** comes from pjgowtham's SM8450 work:

| Tree | Revision |
| --- | --- |
| [Kernel](https://github.com/pjgowtham/android_kernel_oneplus_sm8450/tree/914935583f0ce199114a4a1f31178ab25a3a052d) | `914935583f0ce199114a4a1f31178ab25a3a052d` |
| [Device trees](https://github.com/pjgowtham/android_kernel_oneplus_sm8450-devicetrees/tree/d8f3eb3fe8f98facd9669aa97d1247f6580e1e58) | `d8f3eb3fe8f98facd9669aa97d1247f6580e1e58` |
| [Modules](https://github.com/pjgowtham/android_kernel_oneplus_sm8450-modules/tree/ca1104519fcb7e769129e75458a9da4833bcc751) | `ca1104519fcb7e769129e75458a9da4833bcc751` |

Download the full [kernel source archive](https://github.com/wjdob/lineageos-realmegt2pro/releases/download/lineage-24.0-rmx3301-native25-20261107/kernel-source-RMX3301-native25.tar.gz).
It contains all three trees, upstream licenses, the applied trusted-app memory
overlay and `release/kernel_configs.txt` / `kernel_version.txt`. The source pins,
DTS patch and actual kernel configuration match Package-23b, so this archive is
reused unchanged. The Native25 recipe names the same patch as
[0011](source/lineage-24.0/patches/lineage-24.0/0011-ferrari-trusted-app-memory.patch).
The kernel/module trees have no local source changes.

To inspect upstream kernel history:

```sh
git clone https://github.com/pjgowtham/android_kernel_oneplus_sm8450.git
cd android_kernel_oneplus_sm8450
git checkout --detach 914935583f0ce199114a4a1f31178ab25a3a052d
git show --stat HEAD
```

Use the pinned build tools, device trees/modules and recorded kernel configuration
when reproducing the build.

## ROM and app ports

The [source kit](source/lineage-24.0/README.md) includes configs, patches, overlays,
compatibility tools and tests. Proprietary .1410 inputs and signing keys are
separate prerequisites. Extract matching inputs from your own firmware and use
your own signing identity when rebuilding. Original component licenses remain.
OEM applications/libraries retain their owners' rights and notices.
