# LineageOS for Realme GT2 Pro

Android 17 is available separately: [Native25 beta and optional Camera, Photos and Clock](https://github.com/wjdob/lineageos-realmegt2pro/releases/tag/lineage-24.0-rmx3301-native25-20261107).
[Android 17 source and guide](https://github.com/wjdob/lineageos-realmegt2pro/tree/lineage-24.0).
This branch retains the Android 16 Package-23b release and its matching instructions.

An unofficial **LineageOS 23.2 / Android 16** port for **RMX3301**, with separate Realme Camera and Photos/editor packages. The project aims for a dependable daily-use system close to upstream LineageOS. This release is **beta**.

**Current release:** [Package-23b, Camera15 and Gallery15](https://github.com/wjdob/lineageos-realmegt2pro/releases/tag/lineage-23.2-rmx3301-23b-20261103).

| Baseline | Version |
| --- | --- |
| System | LineageOS 23.2, Android 16, API 36 |
| Kernel | Linux 5.10.246 |
| Android / vendor security patch | 2026-10-01 / 2025-05-01 |
| Primary development phone | RMX3301, project 21631, TW `RMX3301_15.0.0.1410(EX01)` |

The TW .1410 phone remains the primary test device. Other RMX3301 regions and compatible Android 15 firmware are expected to work; broader testing is needed. The GNSS installer accepts specific reviewed layouts. RMX3300 is unverified.

## Choices and tested features

- **Base LineageOS:** calls/data, Wi-Fi/hotspot, Bluetooth headset, encryption, PIN/fingerprint, display resolutions and corrected battery-current reporting.
- **Realme Camera:** photos, video/sound, flash, Portrait, filters, HEIC/10-bit and newest-media handoff.
- **Realme Photos:** browsing, editing, Markup, Remover, Save copy/Replace original, album moves, sharing and wallpaper.
- **MindTheGapps:** optional Google sign-in, Play downloads/updates and retained sessions.

Google and OEM apps are separate choices. The tested combined installation retained encrypted data, app identities and all 38 captured Camera/Photos preferences through the 23b update. [Release notes](RELEASE_NOTES.md) describe the remaining limits.

## Quick start

1. Read [Install](INSTALL.md), including backups, FRP and the required first-install data wipe.
2. Download the full OTA and matching recovery-support ZIP from [the latest release](https://github.com/wjdob/lineageos-realmegt2pro/releases/latest). Verify `SHA256SUMS`.
3. With an **already unlocked bootloader**, flash the matching support images, enter recovery, format data once and sideload the ROM.
4. Add Android 16 ARM64 MindTheGapps before the first Android boot if wanted.
5. After setup and a completed OTA merge, optionally sideload Camera15 and Gallery15. Their app-only installers handle checks and updates without formatting data.

**Keep the bootloader unlocked while using this ROM and when returning to stock. Relocking custom or mismatched images can brick the phone.**

## Source, credits and support

[pjgowtham](https://github.com/pjgowtham)'s device, common platform, kernel and Oplus work provides the foundation. Credit also belongs to LineageOS, AOSP, Qualcomm/Oplus contributors and Rapper_skull's L5 research. [Changes and credits](CHANGES.md) identifies this project's additions. [Sources](SOURCES.md) gives exact revisions, patches and kernel source/configuration.

Report problems through the [ROM, Camera or Gallery issue form](https://github.com/wjdob/lineageos-realmegt2pro/issues/new/choose). Forms add component labels. Include versions, repeatable steps, expected/actual results and frequency; remove personal information from logs. See [reporting tips](CONTRIBUTING.md).

## Returning to stock

Use your own verified stock OS set and [return notes](INSTALL.md#returning-to-stock). A wipe may be required. Preserve calibration, EFS, FRP and unlock state. Historical .1410 stock returns passed on the development phone; a full return from 23b remains untested. [20a is retained as a superseded release](releases/20a.md).
