# Package-23b beta

LineageOS 23.2 / Android 16 for RMX3301. Camera and Photos are separate
downloads. Package-23b replaces the older Android 16 release, 20a.

The development handset is an RMX3300 Chinese-market model converted to RMX3301
TW .1410 firmware. These test results cover that converted phone. RMX3301 in the
release names describes the firmware target.

## Lens update, 7 November

Camera beta16 and Photos alpha16 prefer the current Google Lens link, with a
legacy fallback. Camera and Photos keep their APKs, signing identities and settings.
The shared library, its receipt and each appâ€™s OTA hook are updated together.
Google remains optional. The Camera installer updates a recognized existing Photos
bundle automatically; Camera-only users keep Photos absent.

Host tests, reproducible SDK compilation and package signature checks pass. New
package installation, the Camera button and later OTA retention need live testing.
The corrected Lens link itself worked on the Android17 development phone.
The feature checks below cover the previous app packages.

## Tested features

The tested update from Package-22 to Package-23b preserved existing apps and media,
encrypted data, PIN/fingerprint, Google sign-in and the Camera/Photos settings checked
during testing.

- Calls/mobile data, Wi-Fi/hotspot, Bluetooth audio and ordinary video playback.
- PIN/fingerprint unlock, Play Store installs/updates and screen-off notifications.
- High/Max display alignment, dimming, wake, touch and adaptive brightness.
- Camera photos/video with sound, HEIC with 10-bit OFF/ON, filters, Portrait, flash and latest-media viewing.
- Photos JPEG/HEIC/video, Markup, Remover, Undo, Save copy, Replace original, album moves, Share and wallpaper selection.

## Known issues and untested cases

- Private-photo locking is unavailable because the OEM privacy service is missing.

- NFC, navigation accuracy, every camera mode and full battery/power behavior need further testing.
- The direct 20a-to-23b update has not been tested separately.
- A brief fingerprint retry burst can occur while recovering from a fingerprint service failure. Unlocking recovered in testing.
- Separate base-only, Google-only, Camera-only and Photos-only update combinations need live testing.
- The bundled older Digital Wellbeing app needs more startup testing. The Play-updated version works.
- Remover downloads models from OEM servers. VPN or DNS filtering can block `fourier-videoclip-sg.allawnos.com` or `videoclipfsg.coloros.com`.

## GNSS

Earlier outdoor testing on 20a received GPS L5 and Galileo E5a signals. Package-23b preserves already-enabled NV images during normal updates. Its first-time NV change, reverse change and refusal/failure handling still need live testing. Other partition layouts may be refused. Keep your own NV backups.

## Security

Public downloads use the standard boot and recovery images. The custom auto-ADB
engineering recovery is excluded. The ROM is a **userdebug beta**.

Keep the bootloader unlocked.

Android security patch: **2026-10-01**. Vendor security patch: **2025-05-01**.
Play Integrity, banking-app compatibility and DRM support have not been certified.

See [open issues](https://github.com/wjdob/lineageos-realmegt2pro/issues) for current reports and workarounds.
