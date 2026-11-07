# Android 16 release source

This directory contains the original Package-23b manifests, patches and templates,
plus Camera15/Gallery15 compatibility tools. `PROVENANCE.json` records their versions
and hashes. [Sources and credits](https://github.com/wjdob/lineageos-realmegt2pro/blob/lineage-23.2/SOURCES.md) links the maintained repositories
and complete kernel source.

Rebuilding needs the Android checkout, matching stock files, build tools and your
own signing keys. The filter library at `.local/build-inputs/ferrari-filter/libmsnativefilter.so`
is supplied from matching stock firmware and checked against the recipe's hash.
Build-time status text in the original configurations is historical;
[release notes](https://github.com/wjdob/lineageos-realmegt2pro/blob/lineage-23.2-rmx3301-23b-20261103/RELEASE_NOTES.md) describe the published release's test results.
For Android 17, use the [Native25 source kit](lineage-24.0/README.md).
