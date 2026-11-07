# Native25 release source

This directory contains the original Native25 manifest, patches, configurations
and compatibility tools. `PROVENANCE.json` records source versions and file hashes.
See [Sources and credits](../../SOURCES.md) for the maintained repositories and kernel source.

Rebuilding needs matching proprietary stock files, Android build tools and your
own signing keys. The required file hashes are listed in the configurations.
`tools/port_stock_clock.py` prepares the Clock APK; Camera/Photos tools prepare
their compatibility files and recovery packages.

Build-time status text in original configurations is historical.
[Release notes](../../RELEASE_NOTES.md) describe the published release's test results.
