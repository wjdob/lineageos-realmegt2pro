# Native25 beta

LineageOS 24.0 / Android 17 for RMX3301. Camera and Photos are separate
downloads. Clock alpha5 is also available as a normal APK.

The development handset is an RMX3300 Chinese-market model converted to RMX3301
TW .1410 firmware. These test results cover that converted phone. RMX3301 in the
release names describes the firmware target.

## Lens update, 7 November

Camera alpha2-api37 and Photos alpha2-api37 prefer the current Google Lens link, with a
legacy fallback. Camera and Photos keep their APKs, signing identities and settings.
The shared library, its receipt and each appâ€™s OTA hook are updated together.
Google remains optional. The Camera installer updates a recognized existing Photos
bundle automatically; Camera-only users keep Photos absent.

Host tests, reproducible SDK compilation and package signature checks pass. New
package installation, the Camera button and later OTA retention need live testing.
The corrected Lens link itself worked on the Android17 development phone.
The feature checks below cover the previous app packages.

## Tested features

Photos and videos, existing apps, PIN/fingerprint and Google sign-in were preserved
in the tested Native24-to-Native25 update. Camera/Photos settings and the features
listed below worked after the update.

- Calls/mobile data, Wi-Fi/hotspot, Bluetooth audio and ordinary video playback.
- PIN/fingerprint unlock, Play Store installs/updates and screen-off notifications.
- High/Max display alignment, dimming, wake, touch and adaptive brightness.
- Camera photos/video with sound, HEIC with 10-bit OFF/ON, filters, Portrait, flash and latest-media viewing.
- Photos JPEG/HEIC/video, Markup, Remover, Undo, Save copy, Replace original, album moves, Share and wallpaper selection.
- Clock alarm sound, notification Snooze/Dismiss, timer, stopwatch and World Clock. Full-screen alarms worked after enabling Display over other apps.

## Known issues and untested cases

- Private-photo locking is unavailable because the OEM privacy service is missing.
- Some share targets have duplicate or missing names.
- NFC, measured outdoor L5 reception and a separate test of all six display modes remain untested. Ordinary GPS worked in the reported use.
- A fresh clean installation and a direct Package-23b-to-Native25 upgrade have not been tested. The major-version trial used intermediate development builds.
- Camera/Photos removal, same-version package upgrades and retention through a later Android 17 OTA need live testing.
- Separate base-only, Google-only, Camera-only and Photos-only update combinations need live testing.
- Clock has not been tested on Android 16, during Doze, after reboot/timezone changes or with the phone powered off. Keep a trusted alarm app until those checks are complete.
- Remover downloads models from OEM servers. VPN or DNS filtering can block `fourier-videoclip-sg.allawnos.com` or `videoclipfsg.coloros.com`.

## GNSS

Native25 preserves existing GNSS NV configuration. It does not enable L5 on an unpatched phone. The development phone was already corrected before its Android17 upgrade. A [separate recovery package](https://github.com/wjdob/lineageos-realmegt2pro/issues/17) is planned; its changed-target and rollback paths need validation. Outdoor dual-band reception needs further testing on this release.

## Security

Public downloads use the standard boot and recovery images. The custom auto-ADB
engineering recovery is excluded. The ROM is a **userdebug beta**.
SELinux is enforcing globally, with **nine permissive vendor domains**.
Keep the bootloader unlocked.

Android security patch: **2026-10-01**. Vendor security patch: **2025-05-01**.
Play Integrity, banking-app compatibility and DRM support have not been certified.

See [open issues](https://github.com/wjdob/lineageos-realmegt2pro/issues) for current reports and workarounds.
