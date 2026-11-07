# Install and update Native25

Tested on an RMX3300 Chinese-market handset converted to RMX3301 TW .1410
firmware, project 21631. The RMX3301 checks below refer to the installed firmware
identity. Use matching firmware and partition layouts when selecting packages. Read the [release limits](RELEASE_NOTES.md).
A fresh clean installation and a direct Android 16 upgrade have not yet been tested. The successful major upgrade used intermediate development builds.

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

1. Download `lineage-24.0-RMX3301-native25.zip` and
   `recovery-support-RMX3301-native25.zip` from [Native25](https://github.com/wjdob/lineageos-realmegt2pro/releases/tag/lineage-24.0-rmx3301-native25-20261107).
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
   adb sideload lineage-24.0-RMX3301-native25.zip
   ```

   Leave system unmounted before a ROM sideload. If recovery reports mapped logical
   partitions, reboot recovery and retry without mounting. Wait for recovery's
   success message; the PC progress stopping near 47% can be normal.
5. If adding Google apps, choose **Yes** when asked to reboot recovery for additional
   packages. In the new recovery, sideload the matching
   [MindTheGapps Android 17 ARM64 package](https://github.com/MindTheGapps/17.0.0-arm64/releases/tag/MindTheGapps-17.0.0-arm64-20261022_132445)
   before the first Android boot. Verify its publisher's checksum before accepting
   the different-signature prompt. See the [LineageOS Google-apps guide](https://wiki.lineageos.org/gapps/).
6. Boot Android and finish setup. Wait for the background OTA merge to complete
   before returning to recovery for Camera/Photos. Do not cancel or clear snapshots.
   If an app installer reports a pending merge, return to Android, let it finish,
   then retry the app installation.

The ROM installs 13 OS partitions and includes no bootloader or radio firmware.
It includes no GNSS NV migration writer.

## Optional Camera and Photos

Use the packages matching this release. After Android setup and the completed
OTA merge, run `adb reboot recovery`. Leave system unmounted and choose
**Apply update > Apply from ADB** for each selected package:

```sh
adb sideload realme-camera-24.0-alpha2-api37-install.zip
adb sideload realme-photos-24.0-alpha2-api37-install.zip
```

Choose Apply from ADB again between packages. Choose **No** if asked to reboot
recovery for more app packages. Reboot Android after successful installation.
The installers check compatibility, existing files and free space automatically.

The matching `check.zip` checks compatibility and installed files. The matching
`remove.zip` removes one bundle while preserving shared files needed by the other.
Back up app settings and media before removal. Android 17 removal has not yet had a separate live test.

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

## Optional Clock

Install the APK through Android's package installer, or:

```sh
adb install --user 0 realme-clock-15.10.13-alpha5-api36-api37.apk
```

Allow notifications. Enable **Display over other apps** in Android Settings if you
want full-screen alarm controls to wake the display. Notification controls work
separately. This APK has been tested on Android 17; Android 16 remains untested.

For an update signed with the same key, use `adb install -r --user 0` followed by
the new APK filename. If an existing Clock uses a different signing key, export
its settings before deciding whether to replace it.

## Updates and app data

Use **Settings > System > Updater > Local update** to install a matching full OTA.
Reboot when installation finishes. Follow the new release's compatibility notes.
Keep the same signing identity and leave selected Google/Camera/Photos packages
installed so their update hooks can preserve them. The Clock APK stays in user data.

Retention of the Android 17 Camera/Photos bundles through a later OTA still needs live testing.
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
A Native25-to-stock return has not been tested.
