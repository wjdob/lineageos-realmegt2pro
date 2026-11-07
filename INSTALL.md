# Install and update Package-23b

For RMX3301 / project 21631 with compatible Android 15 firmware. Testing uses TW
.1410 firmware. Read the [release limits](RELEASE_NOTES.md).
Package-23b was tested as an update from Package-22; the direct update from 20a remains untested.

## Backups and bootloader

- Use current [Android platform-tools](https://developer.android.com/tools/releases/platform-tools).
- The bootloader must already be unlocked. **Keep it unlocked while using this ROM and when returning to stock. Relocking custom or mismatched images can brick the phone.**
- Export personal files, contacts, app data and authenticator recovery codes. The first installation erases apps and internal storage.
- Save off-device images of `super` and both slots' `boot`, `vendor_boot`, `dtbo`, `recovery`, `vbmeta`, `vbmeta_system` and `vbmeta_vendor`.
- Also back up `persist`, `modemst1`, `modemst2`, `fsg`, `fsc`, both `oplusstanvbk` partitions, `frp` and `devinfo`. Record partition names/sizes and verify each file's SHA-256. Read them through trusted recovery or rooted Android before flashing.
- Keep backups private. Restoring old FRP/EFS images during a routine installation can damage account pairing or radio state.

Complete these backups before proceeding. Partition backups and personal-data
exports protect different parts of the installation; keep both.

## FRP and accounts

Confirm that you know the current screen lock and can sign into the Google account.
Save working two-factor recovery codes. Before a clean installation, remove Google
accounts and the screen lock through Android Settings.

A recovery wipe can trigger Factory Reset Protection and request the previous
credentials. Resolve account access before wiping. Recovery provides no FRP bypass.

## First installation

1. Download `lineage-23.2-RMX3301-package23b.zip` and
   `recovery-support-RMX3301-package23b.zip` from [Package-23b](https://github.com/wjdob/lineageos-realmegt2pro/releases/tag/lineage-23.2-rmx3301-23b-20261103).
   Verify `SHA256SUMS`, extract the support ZIP and verify its image checksums.
2. Authorize USB debugging in Android, then check the phone and slot:

   ```sh
   adb shell getprop ro.product.model
   adb shell getprop ro.boot.prjname
   adb reboot bootloader
   fastboot devices
   fastboot getvar current-slot
   fastboot getvar is-userspace
   ```

   Expect RMX3301 / 21631. Use normal bootloader fastboot with `is-userspace: no`.
   Connect only the intended phone.
3. Flash all seven matching support images to the **current slot**. This example
   uses A. If the current slot is B, replace **every `_a` with `_b`**:

   ```sh
   fastboot flash boot_a boot.img
   fastboot flash vendor_boot_a vendor_boot.img
   fastboot flash dtbo_a dtbo.img
   fastboot flash vbmeta_a vbmeta.img
   fastboot flash vbmeta_system_a vbmeta_system.img
   fastboot flash vbmeta_vendor_a vbmeta_vendor.img
   fastboot flash recovery_a recovery.img
   fastboot reboot recovery
   ```

   Stop if a write fails. Keep the images from one release together.
4. In Lineage Recovery, choose **Factory reset > Format data** once. This erases
   apps and internal storage. Then choose **Apply update > Apply from ADB**:

   ```sh
   adb sideload lineage-23.2-RMX3301-package23b.zip
   ```

   Leave system unmounted before a ROM sideload. If recovery reports mapped logical
   partitions, reboot recovery and retry without mounting. Wait for recovery's
   success message; the PC progress stopping near 47% can be normal.
5. If adding Google apps, choose **Yes** when asked to reboot recovery for additional
   packages. In the new recovery, sideload the matching
   [MindTheGapps Android 16 ARM64 package](https://github.com/MindTheGapps/16.0.0-arm64/releases/tag/MindTheGapps-16.0.0-arm64-20261023_034858)
   before the first Android boot. Verify its publisher's checksum before accepting
   the different-signature prompt. See the [LineageOS Google-apps guide](https://wiki.lineageos.org/gapps/).
6. Boot Android and finish setup. Wait for the background OTA merge to complete
   before returning to recovery for Camera/Photos. Do not cancel or clear snapshots.
   If an app installer reports a pending merge, return to Android, let it finish,
   then retry the app installation.

The ROM installs 13 OS partitions and includes no bootloader or radio firmware.
Package-23b also includes a guarded inactive-slot GNSS NV migration. Read its test limits in the release notes.

## Optional Camera and Photos

Use the packages matching this release. After Android setup and the completed
OTA merge, run `adb reboot recovery`. Leave system unmounted and choose
**Apply update > Apply from ADB** for each selected package:

```sh
adb sideload realme-camera-23.2-beta16-install.zip
adb sideload realme-photos-23.2-alpha16-install.zip
```

Choose Apply from ADB again between packages. Choose **No** if asked to reboot
recovery for more app packages. Reboot Android after successful installation.
The installers check compatibility, existing files and free space automatically.

The matching `check.zip` checks compatibility and installed files. The matching
`remove.zip` removes one bundle while preserving shared files needed by the other.
Back up app settings and media before removal.

### Updating the Lens fix

The new Camera install ZIP also updates an exactly recognized existing Photos
installation to the matching shared library. It keeps Photos absent on Camera-only
installations. App data and saved media are retained. Install the Photos ZIP
separately if you want to add Photos for the first time.

Unknown or modified app files stop the update. If recovery reports an incomplete
Photos installation, keep recovery open, save its log and sideload the matching
Photos install ZIP before rebooting. Each app operation has rollback, but a power
loss can interrupt the sequence between apps. Keep your verified backup.

The Lens revision passed host tests and signature checks. Its installation and
Lens-button tests on the phone are pending. Earlier app packages remain available
for their matching removers and return procedures.

## Ordinary updates

Use **Settings > System > Updater > Local update** to install a matching full OTA.
Reboot when installation finishes. Follow the new release's compatibility notes.
Keep the same signing identity and leave selected Google/Camera/Photos packages
installed so their update hooks can preserve them.

The tested Package-22-to-23b update preserved the combined Google/Camera/Photos installation and the settings checked during testing. The direct 20a-to-23b path remains untested; read the release notes before choosing it.
After an OTA, let the merge complete before updating optional app packages.
If an installer refuses an update, save the error and report it through the issue form.

Keep a verified working backup. Adding Google apps after using a Google-free
installation requires a fresh setup. Major Android upgrades or downgrades may
require a wipe. Restoring older OS images does not reverse Android data migrations;
keep a matching OS/data backup for a return to an earlier version.

## Returning to stock

Use complete stock firmware matching the phone and region, or your own verified
stock backup. Restore matching `super` and the seven slot support images using
the appropriate bootloader-fastboot/fastbootd instructions for that backup format.
A data wipe through stock recovery may be required.

Keep the bootloader unlocked. Preserve bootloader/TEE firmware, calibration, EFS,
FRP and unlock state. Avoid restoring protected-state images during a routine
return. Switching slots after a completed OTA does not restore stock firmware.
Older .1410 stock restores worked on the development phone; a return from Package-23b has not been tested.
