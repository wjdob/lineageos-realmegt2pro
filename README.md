# LineageOS for Realme GT2 Pro

Unofficial **LineageOS 24.0 / Android 17** for **RMX3301**.
Realme Camera and Photos/editor are optional packages. Google apps are installed
separately with MindTheGapps. Realme Clock is available as an optional APK.

**Current Android 17 beta:** [Native25](https://github.com/wjdob/lineageos-realmegt2pro/releases/tag/lineage-24.0-rmx3301-native25-20261107).
[Android 16 downloads and guide](https://github.com/wjdob/lineageos-realmegt2pro/tree/lineage-23.2).

## Device and firmware

| Item | Version |
| --- | --- |
| ROM | LineageOS 24.0, Android 17, API 37 |
| Kernel | Linux 5.10.246 |
| Android / vendor security patch | 2026-10-01 / 2025-05-01 |
| Development phone | RMX3301, project 21631, TW `RMX3301_15.0.0.1410(EX01)` |

Development and testing use the TW .1410 phone. Other RMX3301 regions with
compatible Android 15 firmware may work and need further testing. RMX3300 is untested.

## Tested features

- Calls, mobile data, Wi-Fi, hotspot, Bluetooth audio, PIN and fingerprint unlock.
- Video playback, High/Max display resolution, status-bar alignment and smooth dimming.
- Realme Camera photos and video, sound, flash, Portrait, filters, HEIC/10-bit and latest-photo viewing.
- Realme Photos viewing, editing, Markup, Remover, Replace original, album moves and sharing.
- Optional Google sign-in, Play Store downloads and app updates.
- Realme Clock alarms, full-screen alarm controls, timer, stopwatch and World Clock.

This is a beta tested on one development phone. Read the
[known issues and test limits](RELEASE_NOTES.md) before installing.

The optional Camera/Photos Lens revision is available in the current release.
See [release notes](RELEASE_NOTES.md) for its test status and update instructions.

## Quick start

1. Read [Install](INSTALL.md). Back up your data and core partitions, and check FRP/account access.
2. Download the ROM and matching recovery-support ZIP from [Native25](https://github.com/wjdob/lineageos-realmegt2pro/releases/tag/lineage-24.0-rmx3301-native25-20261107). Verify `SHA256SUMS`.
3. With the bootloader unlocked, flash the matching support images, enter recovery, format data and sideload the ROM.
4. If wanted, install Android 17 ARM64 MindTheGapps before the first Android boot.
5. Finish setup and wait for the background update merge to complete. Then install any optional Camera/Photos packages. Clock installs as a normal APK.

**The first installation erases internal storage. Keep the bootloader unlocked;
relocking custom or mismatched images can brick the phone.**

## Sources and support

[Sources and credits](SOURCES.md) lists the device repositories, exact release
versions, kernel source and build instructions. This port builds on
[pjgowtham](https://github.com/pjgowtham)'s work and LineageOS/AOSP.
[Changes](CHANGES.md) identifies upstream contributions and project fixes.

Use the [issue forms](https://github.com/wjdob/lineageos-realmegt2pro/issues/new/choose) to report a problem.
Include the ROM/app versions and steps to reproduce it. See [reporting tips](CONTRIBUTING.md).

## Returning to stock

Use matching stock firmware or your own verified stock backup. A data wipe may
be needed. Keep the bootloader unlocked and preserve calibration, EFS and FRP.
See [return instructions and limits](INSTALL.md#returning-to-stock).
