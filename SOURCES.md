# Sources

[Source repositories and pinned build manifests](SOURCE_LAYOUT.md) describe the component layout.
The original release source kit below remains the frozen reference.

Package-23b uses the pinned [manifest](source/manifests/lineage-23.2-candidate.xml), [recipe](source/tools/build/recipe-23.2.json) and published patches. Its engineering source checkpoint is `6dbf8f1e4c7ffb3b60acfdb218008242d9bce458`. The public source kit has its own history; [provenance](source/PROVENANCE.json) binds exported files to that snapshot.

## Kernel

Linux **5.10.246-gki-g914935583f0c** comes from pjgowtham's SM8450 work:

| Tree | Exact revision |
| --- | --- |
| [Kernel](https://github.com/pjgowtham/android_kernel_oneplus_sm8450/tree/914935583f0ce199114a4a1f31178ab25a3a052d) | `914935583f0ce199114a4a1f31178ab25a3a052d` |
| [Device trees](https://github.com/pjgowtham/android_kernel_oneplus_sm8450-devicetrees/tree/d8f3eb3fe8f98facd9669aa97d1247f6580e1e58) | `d8f3eb3fe8f98facd9669aa97d1247f6580e1e58` |
| [Modules](https://github.com/pjgowtham/android_kernel_oneplus_sm8450-modules/tree/ca1104519fcb7e769129e75458a9da4833bcc751) | `ca1104519fcb7e769129e75458a9da4833bcc751` |

Download [kernel-source-RMX3301-package23b.tar.gz](https://github.com/wjdob/lineageos-realmegt2pro/releases/download/lineage-23.2-rmx3301-23b-20261103/kernel-source-RMX3301-package23b.tar.gz). It contains all three source trees, upstream licenses, the applied ferrari trusted-app memory overlay and the built `release/kernel_configs.txt` / `kernel_version.txt`. The kernel and module trees have no local modifications; the device-tree change is patch 0035 in the recipe. Kernel pins/configuration match 20a.

To inspect kernel history:

```sh
git clone https://github.com/pjgowtham/android_kernel_oneplus_sm8450.git
cd android_kernel_oneplus_sm8450
git checkout --detach 914935583f0ce199114a4a1f31178ab25a3a052d
git show --stat HEAD
```

Use the manifest's pinned build tools/Clang and device kernel configuration when reproducing it.

## ROM and app ports

`source/` contains the release's patches, templates, contracts and compatibility tools for Camera15/Gallery15. Proprietary APKs, libraries and models are separate inputs with expected hashes in the configs. Extract them from your own matching stock set; rebuilding signed packages also requires Android build dependencies and your signing identity.

Upstream licenses remain in place. The kernel archive includes GPL-2.0 license texts. OEM apps/libraries retain their owners' rights and notices. [Changes and credits](CHANGES.md) separates foundations from local additions.
