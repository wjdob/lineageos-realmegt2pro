# Changes and credits

LineageOS/AOSP and pjgowtham's Realme GT2 Pro, SM8450, Oplus and kernel work provide
the foundation. Original authors retain credit. [Sources](SOURCES.md) lists exact versions.

| Area | Upstream work | Project changes |
| --- | --- | --- |
| Device and kernel | [pjgowtham's device tree](https://github.com/pjgowtham/android_device_realme_ferrari), [SM8450 common](https://github.com/pjgowtham/android_device_oneplus_sm8450-common), Oplus and kernel sources | .1410 firmware integration, trusted-app memory, module/subsystem startup and device-specific extraction fixes |
| Fingerprint | OEM HAL/trusted apps and Lineage HIDL-to-AIDL support | Trusted-app memory and boot-state fixes, cleanup after service failure and OEM provider restart handling |
| Media and audio | Qualcomm Codec2 and Oplus audio components | Codec2 allocation/ABI fixes, crash-report syscall handling and device audio-calibration paths |
| Battery | Qualcomm health HAL and Oplus dual-cell gauge | Corrected current units and sign in getters and callbacks |
| Display | OEM panel, Lineage SystemUI and Contacts | Smooth backlight updates, resolution-aware status-bar alignment and Contacts scrolling fixes |

| Camera | OEM Camera/APS/HEIF and AOSP camera/native-window code | Camera lifecycle and vendor-interface compatibility, recording profiles, HEIF/P010 and filter support |
| Photos/editor | OEM Photos, editor and native algorithms | Android compatibility for editing, Markup and Remover; media permissions, album moves, sharing and latest-photo viewing |

| Updates | Lineage addon.d/backuptool and Android update_engine | Optional-app retention, shared-file ownership checks and error handling |
| GNSS | [Rapper_skull L5 module](https://github.com/rapperskull/realme_gps_l5_enabler) and [libnvbk](https://github.com/rapperskull/libnvbk) | Preserve the full NV container, verify its layout and apply the guarded inactive-slot change |

Camera retains its OEM APK signature. Patched Photos uses a dedicated project app key.
Google apps come from MindTheGapps. These apps remain optional.

The Lens package revision adds the current Google Lens route with an older-route
fallback and coordinates Camera/Photos shared-library updates. This project change
keeps the OEM APKs and existing app signatures.
