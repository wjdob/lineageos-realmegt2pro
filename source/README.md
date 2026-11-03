# Source kit

The manifest, recipe, patches and templates describe Package-23b. Compatibility sources/configs describe Camera15/Gallery15. PROVENANCE.json records the original snapshot and file hashes. Historical status strings in frozen source contracts describe their build-time state; current acceptance is in the release notes.

Proprietary inputs and private keys are supplied separately. The recipe's omitted `.local/build-inputs/ferrari-filter/libmsnativefilter.so` comes from matching stock firmware and is checked against the recorded hash.

See [Sources](../SOURCES.md) for kernel/toolchain pins and attribution, and [Install](../INSTALL.md) for installation. Rebuilding requires the Android checkout, proprietary inputs and host configuration.
