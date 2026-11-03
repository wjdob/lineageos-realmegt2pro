# Package-23b beta

**Package-23b + optional Camera15 + optional Gallery15**, release date 2026-11-03. This full OTA includes the earlier battery, calibration, display, GNSS and camera-platform fixes.

## Changes since 20a

- Match both Qualcomm Codec2 launchers to the provider's 288-byte allocation ABI; retain the narrow audio crash-report syscall fix.
- Restore fingerprint framework state after HAL death and restart its OEM companion through a device-specific init dependency.
- Reload the notification-header guideline correctly when switching resolution and align lock-screen carrier font padding.
- Gallery15 supplies Share labels and image-specific MIME handling, including privacy/format conversion.

## Tested

The development phone completed a same-key, no-wipe 22/A to 23b/B update using the standard shipped boot. Recovery/firmware checks, encrypted data, PIN/fingerprint, Google session/app installation, video/audio, Camera JPEG/HEIC10-bit OFF/ON/video/thumbnail, Photos Markup/Remover and High/Max alignment passed. All 38 captured app preferences were retained. Captured codec startup/crash checks and dimming-interruption checks passed.

Idle fingerprint-service recovery passed in 6.3 seconds. During active recovery, the original empty-queue test timed out while cleanup waited behind fresh authentication. Cleanup then completed and PIN/fingerprint worked without repair. A brief reconnect retry burst remains tracked.

## GNSS

Earlier 20a/B outdoor testing received fresh fixes and GPS L5/Galileo E5a signals. The packaged migration's already-enabled path now runs successfully through normal OTA updates, preserving both NV images. A changed-target write, inverse return and live refusal/failure paths still need validation. The installer can refuse other layouts. Preserve your own NV backups and report an error before changing firmware.

## Remaining limits

- A brief HIDL user-start retry burst during deliberate fingerprint HAL recovery; enrollment hints need broader observation.
- Gallery private-photo locking requires its missing OEM privacy backend.
- Independent plain/Google-only/Camera-only/Gallery-only update profiles need live coverage. Their package prerequisites pass offline checks.
- The older bundled Wellbeing version's direct-boot behavior remains separate from the working Play-updated app.
- NFC tags, every camera mode, navigation accuracy and full power behavior need broader testing.
- Remover downloads models from OEM services; filtering can block `fourier-videoclip-sg.allawnos.com` or `videoclipfsg.coloros.com`.

Magisk and KernelSU remain user-managed, with separate compatibility work required. See [open issues](https://github.com/wjdob/lineageos-realmegt2pro/issues) before reporting a problem.
