# LineageOS for Realme GT2 Pro

An unofficial **LineageOS 24.0 / Android 17** port for **RMX3301**, with optional
Realme Camera, Photos/editor and Clock apps. The base stays close to LineageOS.
Google and the stock-app ports are separate choices. **Native25 is a beta prerelease.**

| Download | Use |
| --- | --- |
| [Android 17 Native25](https://github.com/wjdob/lineageos-realmegt2pro/releases/tag/lineage-24.0-rmx3301-native25-20261107) | Current Android 17 beta, with the tested optional app packages |
| [Android 16 Package-23b](https://github.com/wjdob/lineageos-realmegt2pro/releases/tag/lineage-23.2-rmx3301-23b-20261103) | Retained Android 16 release; use its own guide and bundles |

## Baseline and results

| Item | Native25 |
| --- | --- |
| System | LineageOS 24.0, Android 17, API 37, cp2a |
| Kernel | Linux 5.10.246 |
| Android / vendor security patch | 2026-10-01 / 2025-05-01 |
| Primary development phone | RMX3301, project 21631, TW `RMX3301_15.0.0.1410(EX01)` |

Other compatible RMX3301 regions/Android 15 firmware may work; wider testing is
needed. RMX3300 is unverified. The release contains a full OTA and standard recovery.

Two standard boots and combined testing passed: retained apps/media and Google
sign-in, PIN/fingerprint, calls/data, Wi-Fi/hotspot, Bluetooth, ordinary GPS,
video/audio, High/Max alignment, dimming and wake. Camera photos/video, HEIC/10-bit,
filters, Portrait and flash work. Photos viewing/editing, Markup, Remover, media
moves and sharing work. Clock alarms, timer, stopwatch, World Clock and its bottom
labels passed the recorded checks.

NFC, measured outdoor L5 and the next OTA's API37 app retention remain untested.
Read [release limits](RELEASE_NOTES.md) before installing.

## Quick start

1. Read [Install](INSTALL.md), including verified backups, FRP and the first-install wipe.
2. Download Native25 and its matching recovery-support ZIP. Verify `SHA256SUMS`.
3. With the bootloader already unlocked, flash the support images for the current
   slot, enter recovery, format data once and sideload the full ROM.
4. If wanted, install Android 17 ARM64 MindTheGapps before the first Android boot.
5. After setup and completed OTA merge, optionally sideload the API37 Camera and
   Photos installers. Clock installs as an ordinary APK.

**Keep the bootloader unlocked. Relocking custom or mismatched images can brick the phone.**

## Sources, credits and reports

[pjgowtham](https://github.com/pjgowtham)'s device, common platform, Oplus and kernel
work provides the foundation, with LineageOS/AOSP and upstream contributors.
[Changes and credits](CHANGES.md) separates upstream fixes from project additions.
[Sources](SOURCES.md) gives exact revisions, patches and full kernel source/configuration.

Use the [issue forms](https://github.com/wjdob/lineageos-realmegt2pro/issues/new/choose).
Include `[24.0]` or `[23.2]` in the title, choose a component and provide versions,
numbered reproduction steps, expected/actual behavior and frequency. Keep personal
information out of logs. [Reporting tips](CONTRIBUTING.md) are brief.

## Returning to stock

Use your own matching stock set and [return notes](INSTALL.md#returning-to-stock).
A wipe may be needed. Preserve calibration, EFS, FRP and unlock state. Current
Native25-to-stock restoration is untested; historical .1410 returns are separate
evidence. The Android 16 release and its source remain available on `lineage-23.2`.
