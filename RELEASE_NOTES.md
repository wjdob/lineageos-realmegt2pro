# Native25 release notes

Native25 is the first public Android 17 beta from this workstream. The full OTA
contains the base fixes together. Camera/Photos API37 and Clock alpha5 are separate
optional downloads. Google uses the separate MindTheGapps project.

## Recorded checks

- Two standard-image boots, retained encrypted data/media, PIN/fingerprint and Google sign-in.
- Play installs/updates, screen-off notifications, ordinary video/audio.
- Calls/mobile data, Wi-Fi/hotspot, Bluetooth headset and owner-reported ordinary GPS.
- High/Max top-row alignment, dimming interruption, rapid wake, touch/adaptive brightness.
- Camera preview/photos/video/audio, HEIC with 10-bit OFF/ON, filters, front/rear Portrait, flash and newest-item handoff.
- Photos JPEG/HEIC/video, Markup/Remover, Undo, Save copy, Replace original, album moves, sharing and wallpaper picker.
- Clock sound, notification Snooze/Dismiss, timer, stopwatch and World Clock. Full-screen alarm wake/dismissal passed after owner-granted overlay access; bottom labels are clear.

## Limits

NFC/card transactions, measured outdoor L5, all six refresh modes independently,
fresh clean installation, a generic direct Android 16-to-Native25 jump and the
next API37 add-on-retaining OTA remain untested. Independent base/single-app OTA
profiles remain open. Earlier major-version/data-retention results used a controlled
intermediate-candidate route; they do not qualify every public upgrade path.

Photos private-photo locking needs its OEM backend and remains unavailable.
Some OEM share targets can have duplicate or incomplete labels. Clock's Android 16
runtime, Doze, reboot/timezone rescheduling and powered-off alarms remain unqualified.
Retain a trusted alarm while extended reliability is assessed.

The build is userdebug. Global SELinux is Enforcing, with nine inherited permissive
vendor domains. Public recovery is standard; the owner-keyed engineering image is
excluded. Android patch level is 2026-10-01; vendor patch level remains 2025-05-01.
Play Integrity, banking, DRM and every third-party app are not certified by these tests.

Android 16 Package-23b remains available in its own release channel. Keep its
matching app bundles and guide together.
