# Install and update

This beta targets RMX3301 / project 21631 with compatible Android 15 firmware. Read [release limits](RELEASE_NOTES.md) before starting. Use current [Android platform-tools](https://developer.android.com/tools/releases/platform-tools) and a reliable USB cable.

## Before flashing

- The bootloader must already be unlocked. **Keep it unlocked. Relocking a custom or mismatched installation can brick the phone.**
- Export apps, photos, contacts and authenticator recovery codes. A partition backup does not replace a personal-data backup.
- Save off-device images of `super` and both slots' `boot`, `vendor_boot`, `dtbo`, `recovery`, `vbmeta`, `vbmeta_system` and `vbmeta_vendor`.
- Also preserve `persist`, `modemst1`, `modemst2`, `fsg`, `fsc`, both `oplusstanvbk` partitions, `frp` and `devinfo`. Verify every backup's SHA-256 and keep its partition name and size. Use an existing trusted recovery or rooted Android to read them before changing the installation. If you cannot obtain and verify these backups, stop here.
- Keep your own calibration, EFS and protected-state backups private. Treat them as recovery references. Restoring old FRP/EFS data during an ordinary ROM install can damage pairing or radio state.
- Download this release's full OTA, recovery-support ZIP and any selected add-ons. Check the published hashes. A first stock-to-Lineage installation **erases internal storage**.

The OS payload contains 13 OS partitions. Package-20a also contains a separately guarded inactive-slot GNSS NV migration; its live installer execution remains unvalidated. Details are in [release notes](RELEASE_NOTES.md#gnss).

## FRP and screen locks

While the existing Android installation still works, confirm that you know its PIN/password and can sign into its Google account. Save working two-factor backup codes. Remove Google accounts and the screen lock through Android Settings before a planned clean install.

Factory Reset Protection can request the previous credential or Google account after a wipe. Recovery formatting discards data-side encryption and pairing information. Resolve ownership verification before wiping if the account or previous credential is unavailable. This recovery provides no FRP bypass or OEM private-vault unlock.

## First installation

1. Extract `recovery-support-RMX3301-package20a.zip`. Verify the extracted images against its own `SHA256SUMS`.
2. With USB debugging authorized in Android, check:

   ```sh
   adb shell getprop ro.product.model
   adb shell getprop ro.boot.prjname
   adb reboot bootloader
   fastboot devices
   fastboot getvar current-slot
   fastboot getvar is-userspace
   ```

   Android must report RMX3301 / 21631. Use normal bootloader fastboot; `is-userspace` should be `no`. Confirm one intended phone is connected.
3. Flash the matching OS support images to the **current slot**. The example below is for **slot A**. If `current-slot` is `b`, replace **every `_a` with `_b`** before running it. All images come from the same release:

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

   The recovery image uses the matching boot/kernel support. Keep the seven-image set together. A failed write needs investigation before proceeding.
4. In Lineage Recovery, choose **Factory reset → Format data** once. This erases apps and internal storage.
5. Choose **Apply update → Apply from ADB**, then send the full ROM:

   ```sh
   adb sideload lineage-23.2-RMX3301-package20a.zip
   ```

   Wait for recovery to report successful installation. The PC stopping near 47% can be normal; use recovery's result.
6. If adding Google apps, choose **Yes** when recovery offers to reboot recovery for additional packages. In the new recovery, sideload the reviewed [MindTheGapps Android 16 ARM64 package](https://github.com/MindTheGapps/16.0.0-arm64/releases/tag/MindTheGapps-16.0.0-arm64-20261023_034858) before booting Android. Its different-signature confirmation is expected for that verified package. See the [LineageOS Google-apps guide](https://wiki.lineageos.org/gapps/).
7. Reboot to Android and finish setup. Let the background update merge finish before installing Camera or Gallery. The successful installation and completed merge must be verified before returning to recovery; do not clear or cancel snapshots to force progress.

## Optional Camera and Gallery

Each package works as a separate choice on the declared compatible baseline. Use the Camera15/Gallery14 pair listed in this release. Existing supported versions use the same install ZIP for an update.

After the ROM's first boot and completed merge, enter recovery with `adb reboot recovery`. Leave system unmounted. Choose **Apply update → Apply from ADB** for each selected package:

```sh
adb sideload realme-camera-23.2-beta15-install.zip
adb sideload realme-photos-23.2-alpha14-install.zip
```

Select **Apply from ADB again between commands**. After the first package, choose **No** if asked to reboot recovery for more packages; both app packages can use one session. Reboot Android after successful results. Each installer checks the device/runtime, recognized old files, available space and shared ownership before applying its files.

The matching `check.zip` performs a package check. The matching `remove.zip` removes that bundle while preserving a verified peer's shared files. Export app settings/media first and expect removal to affect app data. Personal media is outside the installer's ownership.

## Ordinary updates

Use the same signing lineage and follow the next release's compatibility notes. Install a local full OTA through **Settings → System → Updater → Local update**, then reboot when installation finishes. Routine same-profile updates preserve data and use add-on retention hooks for installed Google/Camera/Gallery packages.

Keep the selected apps installed during a routine OTA. The tested combined profile retained their identities, settings and Google session through 19d and 20a. Adding Google apps to an already-used Google-free installation requires a fresh setup. Removing an add-on is a separate, deliberate operation.

## Returning to stock

Use a complete stock OS set for your exact phone and partition layout, or your own verified pre-install images. Restore matching `super` and the slot's seven OS support images using their correct normal-fastboot/fastbootd routes. A stock recovery data format may be needed before stock Android can boot.

Keep the bootloader unlocked. Preserve bootloader/TEE firmware, calibration, EFS, FRP and unlock state. A saved protected-state image is not a routine restore target. Slot switching after a completed OTA is not a complete stock return. Stop if the package changes firmware, rolls back incompatible security state or asks to relock. Historical .1410 returns passed on the development phone; the Package-20a inverse path remains untested.
