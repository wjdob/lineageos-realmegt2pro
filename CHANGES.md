# Changes and credits

LineageOS/AOSP Android 17 and pjgowtham's ferrari/SM8450/Oplus/kernel work form the
foundation. Original authors retain credit. Exact pins and patches are in [Sources](SOURCES.md).

| Area | Foundation | Project changes |
| --- | --- | --- |
| Device/kernel | [pjgowtham's ferrari](https://github.com/pjgowtham/android_device_realme_ferrari), [SM8450 common](https://github.com/pjgowtham/android_device_oneplus_sm8450-common), Oplus hardware and kernel trees | .1410 cohort integration, trusted-app memory overlay, restored module/subsystem startup and complete SIM1/SIM2/eSE1 declarations |
| AOD sensors | [pjgowtham e7432ff](https://github.com/pjgowtham/android_device_oneplus_sm8450-common/commit/e7432ffb3533aa41bd46ab5c6e97f361c49d0f9e) request-mode correction | Separate sensor error-event parser guard and live rapid-wake validation |
| Core hardware | Lineage/Qualcomm/Oplus HALs and drivers | Fingerprint lifecycle/recovery work, Codec2 provider ABI integration, health current reporting, audio calibration and HIDL compatibility |
| Display | OEM panel and Lineage SystemUI | Direct backlight updates and resolution-aware cutout/header alignment |
| Camera | OEM Camera/APS/HEIF, AOSP camera/native-window | Scoped lifecycle/caller metadata, public-buffer/API37 compatibility, P010 and filter/LUT provider integration |
| Photos/editor | OEM app, editor and algorithms | Receiver/editor/Markup/Remover compatibility, media access/consent, sharing and latest-item viewer integration |
| Clock | OEM Clock15.10.13 | App-local OEM API fallbacks, Android alarm-sound fallback, optional window integration and navigation-inset spacing |
| Updates | Lineage addon.d/backuptool and Android update_engine | Selected-app ownership/retention checks and failure propagation; the next API37 app-retaining OTA still needs live validation |
| GNSS research | [Rapper_skull's L5 module](https://github.com/rapperskull/realme_gps_l5_enabler) and libnvbk | Earlier23.2 guarded migration research; Native25 contains no GNSS-NV migration writer |

Public common-vendor inputs also use [Arman-ATI's work](https://github.com/Arman-ATI/proprietary_vendor_oneplus_sm8450-common).
Camera keeps its OEM APK signature. Patched Photos and Clock use separate project
app identities. Google packages come from MindTheGapps. These additions remain optional.
