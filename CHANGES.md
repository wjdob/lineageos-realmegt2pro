# Changes and credits

LineageOS/AOSP Android 16 and pjgowtham's Realme GT2 Pro platform work form the baseline. Original authors retain credit for their drivers, framework, apps and algorithms. [Sources](SOURCES.md) records exact pins and local patches.

| Area | Foundation | Project additions |
| --- | --- | --- |
| Device/kernel/Oplus | [pjgowtham's ferrari tree](https://github.com/pjgowtham/android_device_realme_ferrari), [SM8450 common](https://github.com/pjgowtham/android_device_oneplus_sm8450-common), [Oplus hardware](https://github.com/pjgowtham/android_hardware_oplus) and kernel trees | Pinned integration, .1410 extraction/fixups, TinyXML/ZIP/WFD bindings and audio-calibration paths |
| Fingerprint | OEM HAL/trusted apps and upstream HIDL-to-AIDL lifecycle | Trusted-app memory/calibration fixes, queued death cleanup, cached-user reset and Ferrari companion restart |
| Codec2 | Qualcomm provider and launchers | Corrected both allocations to the measured 288-byte provider ABI and the audio crash-report syscall rule |
| Battery | Qualcomm health HAL and Oplus dual-cell gauge | Consistent measured current units/polarity in direct getters and callbacks |
| Display/Contacts | Oplus panel modes, Lineage SystemUI and Contacts | Direct backlight updates, cutout/font alignment, QQS guideline reload and scrolling fix |
| Camera | OEM APS/HEIF providers and AOSP camera/native-window | Scoped lifecycle/vendor compatibility, recording profiles, P010 handling, filter provider and app-local dependencies |
| Optional Photos | OEM Photos/editor and native libraries | Android 16 editor/Markup/Remover compatibility, media access, thumbnail/viewer handoff and Share labels/MIME |
| Updates | Lineage addon.d/backuptool and Android update_engine | Selected-app retention/ownership checks and restore-failure propagation |
| GNSS | [Rapper_skull L5 module](https://github.com/rapperskull/realme_gps_l5_enabler) and [libnvbk](https://github.com/rapperskull/libnvbk) | Whole-container preservation, exact-layout validation and guarded inactive-slot migration |

Camera keeps its OEM APK signature. Patched Photos uses a dedicated project app key. Google apps use the separate MindTheGapps project. The base system keeps Google/OEM app selection optional.
