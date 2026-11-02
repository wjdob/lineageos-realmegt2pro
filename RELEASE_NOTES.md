# Package-20a beta

Baseline: **Package-20a + optional Camera15 + optional Gallery14**, dated 2026-11-02. The full OTA contains the earlier battery, fingerprint, display, camera-platform and update fixes. Install the full OTA directly.

## Confirmed on the development phone

- Same-key 19d → 20a update, completed merge, encrypted data, existing PIN and fingerprint.
- Retained Google session, app download/update/open, Camera/Photos identities and all 38 captured preferences.
- Camera capture/newest-media handoff, Photos Markup/Save copy and the dimming-interruption correction after the OTA.
- Camera15/Gallery14's earlier mode and editor checks listed in the README. The full mode matrix was not repeated after every OTA.

Daily-use acceptance used the owner's diagnostic boot with rooted ADB. The OTA/support archive contains the standard boot. Its separate live acceptance remains open. This is an engineering beta with one primary test device.

## GNSS

Rapper_skull's Realme L5 research identifies the stock GNSS configuration. This project adds exact-layout validation, whole-image preservation, durable backup/readback and an inactive-slot installer migration. No personal NV image is distributed.

The development phone's two slots were enabled through separately checked field trials. GPS L5/Galileo E5a and fixes were observed on the earlier A trial. The latest 20a/B sample was **indoors**: GPS L5 reception was observed, with no fresh fix in that short window. Outdoor positioning on 20a/B remains untested.

The packaged migration is compiled into normal/recovery update engines and has host checks. Its first live installer execution, failure handling and inverse return remain unvalidated. Other reviewed-layout mismatches stop installation. Keep both NV backups and report the exact error if this happens; leave firmware unchanged.

## Known limits

- Occasional Codec2 startup abort with service recovery; ordinary video/sound playback passed.
- Gallery private-photo locking is unavailable because its OEM authentication/storage backend is absent.
- Some Share targets have missing names or duplicate Google Wallet entries.
- A small lock-screen status-row offset and fingerprint enrollment hints remain under observation.
- NFC tags, every camera mode, independent add-on OTA profiles and full battery/power behavior need broader testing.
- Remover depends on the OEM model service. Network filtering can block `fourier-videoclip-sg.allawnos.com` and `videoclipfsg.coloros.com`.

The release preserves Android's permission controls and SELinux Enforcing. Magisk/KernelSU remain user-managed and have no acceptance claim in this baseline. Report problems through the matching issue form.
