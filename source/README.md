# Android 16 release source

This directory contains the original Package-23b manifests, patches and templates,
plus Camera15/Gallery15 compatibility tools. `PROVENANCE.json` records their versions
and hashes. [Sources and credits](../SOURCES.md) links the maintained repositories
and complete kernel source.

Rebuilding needs the Android checkout, matching stock files, build tools and your
own signing keys. The filter library at `.local/build-inputs/ferrari-filter/libmsnativefilter.so`
is supplied from matching stock firmware and checked against the recipe's hash.
Build-time status text in the original configurations is historical;
[release notes](../RELEASE_NOTES.md) describe the published release's test results.
