# Install and update Native25

This guide covers the RMX3301 / project 21631 Android 17 beta. Its tested device
used TW .1410 Android 15 firmware. Clean installation on a fresh phone and a direct
Package-23b-to-Native25 upgrade remain untested. The live major-version trial used
intermediate candidates; the later Native24-to-Native25 update preserved data.
Use a clean setup for a first public trial. Read [release limits](RELEASE_NOTES.md).

## Backups and bootloader

- Use current [Android platform-tools](https://developer.android.com/tools/releases/platform-tools).
  The bootloader must already be unlocked. **Keep it unlocked throughout this ROM
  and any return to stock. Relocking custom or mismatched images can brick the phone.**
- Export personal files, contacts, app data and authenticator recovery codes.
- Before changing partitions, keep off-device images of `super` and both slots'
  `boot`, `vendor_boot`, `dtbo`, `recovery`, `vbmeta`, `vbmeta_system`, `vbmeta_vendor`.
- Also preserve `persist`, `modemst1`, `modemst2`, `fsg`, `fsc`, both `oplusstanvbk`
  partitions, `frp` and `devinfo`. Record names/sizes and verify SHA-256. A trusted
  recovery or rooted Android can read them. Complete and verify backups before flashing.
- Keep these backups private. Calibration, EFS and protected-state images are
  recovery references; restoring old FRP/EFS during an ordinary install can damage state.

Native25 carries 13 OS partitions. It includes no bootloader/radio firmware or
GNSS-NV migration writer. The first stock-to-Lineage installation **erases internal storage**.

## FRP and accounts

Confirm that you know the existing screen lock and can sign into the Google account.
Save working two-factor recovery codes. Before a planned clean setup, remove the
Google account and screen lock through the working Android Settings.

A recovery wipe can trigger Factory Reset Protection and request previous
credentials. Resolve account ownership before wiping. This recovery has no FRP
bypass or OEM private-vault unlock.

## First installation

1. Download `lineage-24.0-RMX3301-native25.zip` and
   `recovery-support-RMX3301-native25.zip` from [the Native25 release](https://github.com/wjdob/lineageos-realmegt2pro/releases/tag/lineage-24.0-rmx3301-native25-20261107).
   Check `SHA256SUMS`, extract the support ZIP and verify its image checksums.
2. Confirm the intended phone and current slot:

   ```sh
   adb shell getprop ro.product.model
   adb shell getprop ro.boot.prjname
   adb reboot bootloader
   fastboot devices
   fastboot getvar current-slot
   fastboot getvar is-userspace
   ```

   Expect RMX3301 / 21631. Use normal bootloader fastboot with `is-userspace: no`.
3. Flash the seven support images to the **current slot**. This example uses A.
   If the current slot is B, replace **every `_a` with `_b`**:

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

   Keep the matching seven-image set together. Investigate any failed write.
4. In Lineage Recovery choose **Factory reset > Format data** once. This erases
   apps and internal storage. Then choose **Apply update > Apply from ADB**:

   ```sh
   adb sideload lineage-24.0-RMX3301-native25.zip
   ```

   Do not mount system before a ROM sideload. If recovery says logical partitions
   are mapped, reboot recovery and retry without mounting. Use recovery's final
   result; a PC progress stop near 47% can be normal.
5. If adding Google, reboot recovery when prompted for additional packages. Install
   the reviewed [MindTheGapps Android 17 ARM64 package](https://github.com/MindTheGapps/17.0.0-arm64/releases/tag/MindTheGapps-17.0.0-arm64-20261022_132445)
   before the first Android boot. Verify its publisher's checksum. Accept its
   different-signature prompt only after that verification. See the
   [LineageOS Google-apps guide](https://wiki.lineageos.org/gapps/).
6. Boot Android, finish setup and let the OTA merge complete before returning to
   recovery for OEM apps. Leave pending snapshots intact until normal merge finishes.

## Optional Camera, Photos and Clock

For either recovery add-on, run `adb reboot recovery`, leave system unmounted and
choose **Apply update > Apply from ADB**:

```sh
adb sideload realme-camera-24.0-alpha1-api37-install.zip
adb sideload realme-photos-24.0-alpha1-api37-install.zip
```

Choose Apply from ADB again between packages. Choose No if asked to reboot for
more app packages. Each installer handles mapping, recognition, preflight,
replacement and rollback staging. Check success before booting Android.
The corresponding `check.zip` checks a package; `remove.zip` removes the matching
bundle with shared-file ownership checks. API37 removal has host checks but no
separate live removal test yet. Export app settings/media before removal.

Clock installs through the normal Android package installer, or:

```sh
adb install --user 0 realme-clock-15.10.13-alpha5-api36-api37.apk
```

Allow notifications. Clock's existing full-screen alarm path uses Android's
**Display over other apps** access; notification controls work separately. Choose
that access in Settings if wanted. Same-signer updates use `adb install -r --user 0`.
An existing differently signed OEM Clock needs a separate data-migration decision;
export its alarms/settings before replacing it. This APK was tested on Android 17.

## Updates and app data

For same-major releases, use **Settings > System > Updater > Local update** with
the complete matching OTA. Keep the same signing lineage. Google and installed
Camera/Photos use retention hooks; the ordinary Clock APK lives in user data.
The next OTA retaining the installed API37 Camera/Photos packages is still an
open live test. Keep a verified return set and review each release's update notes.

Adding Google to an already-used Google-free installation needs a fresh setup.
An Android major upgrade or downgrade can require a wipe. An OS-only rollback
does not restore data migrated by Android 17. Preserve a matching OS/data return set.

## Returning to stock

Use a complete matching stock set or your own verified pre-install OS images.
Restore matching `super` and the seven slot support images through their correct
normal-fastboot/fastbootd routes. A stock recovery data format may be required.
Keep the bootloader unlocked and preserve bootloader/TEE firmware, calibration,
EFS, FRP and unlock state. A slot switch after a completed OTA is not a stock return.
Native25-to-stock restoration remains untested.
