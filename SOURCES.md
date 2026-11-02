# Sources

Package-20a uses the pinned [23.2 manifest](source/manifests/lineage-23.2-candidate.xml), [source recipe](source/tools/build/recipe-23.2.json) and published patches. The original ROM source checkpoint is `60ac15ad78a2abbbadb0cf1715079efc184732de`. The public source kit has its own clean history; [provenance](source/PROVENANCE.json) records each exported file.

## Kernel

Linux **5.10.246-gki-g914935583f0c** comes from pjgowtham's SM8450 work:

| Source | Exact revision |
| --- | --- |
| [Kernel](https://github.com/pjgowtham/android_kernel_oneplus_sm8450/tree/914935583f0ce199114a4a1f31178ab25a3a052d) | `914935583f0ce199114a4a1f31178ab25a3a052d` |
| [Device trees](https://github.com/pjgowtham/android_kernel_oneplus_sm8450-devicetrees/tree/d8f3eb3fe8f98facd9669aa97d1247f6580e1e58) | `d8f3eb3fe8f98facd9669aa97d1247f6580e1e58` |
| [Modules](https://github.com/pjgowtham/android_kernel_oneplus_sm8450-modules/tree/ca1104519fcb7e769129e75458a9da4833bcc751) | `ca1104519fcb7e769129e75458a9da4833bcc751` |

Download `kernel-source-RMX3301-package20a.tar.gz` from this release. It contains those three source trees, their licenses, the applied ferrari trusted-application memory overlay, and `release/kernel_configs.txt` / `kernel_version.txt` taken from the built target-files archive. Compare the overlay with patch 0035 and its hashes in the recipe. The kernel and module trees have no project modifications in this build.

To inspect the original kernel history:

```sh
git clone https://github.com/pjgowtham/android_kernel_oneplus_sm8450.git
cd android_kernel_oneplus_sm8450
git checkout --detach 914935583f0ce199114a4a1f31178ab25a3a052d
git show --stat HEAD
```

For a rebuild, use the manifest's pinned kernel build tools/Clang projects and the device tree's `BoardConfigCommon.mk`/kernel configuration together with the recipe. Preserve the shipped compiler/configuration when comparing results. No kernel binary or private signing key is needed to inspect the source.

## ROM and optional-app changes

`source/` contains the selected manifests, source patches, templates and compatibility/package tools. Recipe hashes bind the ROM modifications to the build snapshot. App-port files come from the accepted Camera15/Gallery14 source line. Proprietary APKs, libraries, model files and signing keys are separate inputs; their expected hashes are recorded in the configs.

The stock input reference is the development phone's .1410 firmware. Extract proprietary files from your own matching stock set. The source kit records the fixes; rebuilding signed releases also requires the corresponding proprietary inputs, Android build dependencies and your own signing identity.

Upstream sources retain their licenses. The kernel uses GPL-2.0; the archive includes its full license texts. OEM apps/libraries remain proprietary, with their original owners' rights and notices. Publishing this port does not grant a new license to those OEM assets. [Changes and credits](CHANGES.md) identifies upstream work and local additions.
