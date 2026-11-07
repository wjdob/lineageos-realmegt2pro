# Native25 source kit

The manifest pins LineageOS 24.0 / Android 17 and the device/kernel projects.
The recipe lists the applied source patches and required private stock-input
hashes. Extract those inputs from your own matching firmware. Use your own
signing identity when rebuilding. The released APK/OTA identities have their own
published certificates and checksums.

`tools/port_stock_clock.py` prepares the optional Clock APK. Camera/Photos
preparation and recovery packaging use the matching configs and tools here.
`requirements-dev.txt` supports the host checks. Android build tools and OEM
inputs are separate prerequisites. This kit retains the source files unchanged;
the release notes describe the tested builds and remaining limits.

See [sources and credits](../../SOURCES.md) for kernel links and the project
changes. `PROVENANCE.json` lists each exported file's source revision and hash.
