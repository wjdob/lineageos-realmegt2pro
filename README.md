# LineageOS for Realme GT2 Pro

An unofficial LineageOS 23.2 / Android 16 port for **RMX3301**, with optional Realme Camera and Photos/editor packages.

The aim is a stable daily-use system that stays close to LineageOS. Releases are currently **beta**. Google apps, Realme Camera and Realme Photos are separate choices.

**Current release:** [Package-20a, Camera15 and Gallery14](https://github.com/wjdob/lineageos-realmegt2pro/releases/tag/lineage-23.2-rmx3301-20a-20261102).

## Baseline

| Item | Version |
| --- | --- |
| System | LineageOS 23.2, Android 16, API 36 |
| Kernel | Linux 5.10.246 |
| Android security patch | 2026-10-01 |
| Vendor security patch | 2025-05-01 |
| Primary development phone | RMX3301, project 21631, TW stock `RMX3301_15.0.0.1410(EX01)` |

Development and live testing use that TW .1410 phone. Other RMX3301 regions and compatible Android 15 firmware are expected to work, with testing still needed. Package-20a's GNSS migration accepts a specific reviewed configuration and can refuse other firmware layouts. See [release limits](RELEASE_NOTES.md). RMX3300 support is unverified.

## Available features

| Choice | Tested features |
| --- | --- |
| Base LineageOS | Calls, mobile data, Wi-Fi/hotspot, Bluetooth headset, PIN/fingerprint, encryption, display resolutions and charging-current reporting |
| Realme Camera | Photos, video with sound, flash, front/rear Portrait, filters, HEIC including 10-bit, and newest-media handoff |
| Realme Photos | JPEG/HEIC/video browsing, editing, Markup, Remover, Save copy/Replace original, album moves, sharing and wallpaper handoff |
| MindTheGapps | Google sign-in, Play downloads/updates and retained sessions through tested OTAs |

Same-key updates retained encrypted data and the selected Google/Camera/Photos apps on the development phone. Plain and individually selected add-on profiles still need their own live update coverage. Gallery private-photo locking remains unavailable. See [release notes](RELEASE_NOTES.md) for the remaining issues.

## Quick start

1. Read [Install](INSTALL.md), including backups, FRP and the data wipe.
2. Download the full OTA and matching recovery-support ZIP from [the beta release](https://github.com/wjdob/lineageos-realmegt2pro/releases/tag/lineage-23.2-rmx3301-20a-20261102). Verify `SHA256SUMS`.
3. With an **already unlocked bootloader**, install the matching recovery/support images, then sideload the ROM. A first installation from stock requires **Format data**.
4. If wanted, install Android 16 ARM64 MindTheGapps in the new recovery **before the first Android boot**.
5. Finish Android setup and let the OTA merge complete. Camera15 and Gallery14 can then be installed separately through recovery's **Apply update → Apply from ADB**. Their installers handle checks and updates. An app-only installation needs no data wipe.

**Keep the bootloader unlocked while using this ROM and during a return to stock. Relocking with custom or mismatched images can brick the phone.**

## Source and credits

[pjgowtham](https://github.com/pjgowtham)'s device, common platform, kernel and Oplus work provides the foundation. Credit also belongs to LineageOS, AOSP, Qualcomm/Oplus contributors and Rapper_skull's L5 research.

[Changes and credits](CHANGES.md) distinguishes upstream work from this project's additions. [Sources](SOURCES.md) provides exact revisions, patches and the downloadable kernel source/configuration for this release.

## Report a problem

Use the matching **ROM**, **Camera** or **Gallery** [issue form](https://github.com/wjdob/lineageos-realmegt2pro/issues/new/choose). Forms add labels automatically. Include versions, repeatable steps, expected/actual results and frequency. Keep one problem per report and remove private information from logs. See [reporting tips](CONTRIBUTING.md).

## Returning to stock

Keep your own stock OS backup and personal-data exports. Return with matching stock OS images and the device-specific [return notes](INSTALL.md#returning-to-stock); a data wipe may be required. Keep the bootloader unlocked and preserve calibration, EFS and FRP. The development phone has previously returned to .1410 stock; a complete return from Package-20a has not been tested.
