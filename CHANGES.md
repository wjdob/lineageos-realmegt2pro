# Changes and credits

This build starts from LineageOS 23.2 / AOSP Android 16 and pjgowtham's Realme GT2 Pro platform work. Original authors retain credit for their device drivers, framework, vendor apps and algorithms. Exact revisions and this project's patches are in [Sources](SOURCES.md).

| Area | Upstream foundation | This project's change |
| --- | --- | --- |
| Device/kernel/platform | [pjgowtham's ferrari device tree](https://github.com/pjgowtham/android_device_realme_ferrari), [SM8450 common](https://github.com/pjgowtham/android_device_oneplus_sm8450-common), [Oplus hardware](https://github.com/pjgowtham/android_hardware_oplus), kernel and Qualcomm display work | Pinned and integrated the selected 23.2 sources with .1410 vendor inputs and repeatable package checks |
| Display firmware | pjgowtham/Lineage display generation and callbacks | Matched extraction and Pixelworks interface bindings to that implementation |
| Vendor loading/audio | OEM binaries, Lineage libraries and Qualcomm AGM | Corrected extraction fixups, TinyXML/ZIP ABI bindings, WFD paths and .1410 audio-calibration paths |
| Fingerprint | Existing Oplus sensor/HAL and trusted applications | Corrected trusted-application memory allocation and calibration initialization |
| Battery | Qualcomm health HAL and Oplus dual-cell gauge | Converted the measured mA/polarity contract consistently in direct getters and callbacks; capacity keeps the stock interpretation |
| Dimming | Existing Oplus panel driver's direct/deferred modes | Selected direct backlight updates for project 21631 after controlled comparisons |
| Status bar/Contacts | Lineage SystemUI overlays and Contacts | Adjusted cutout alignment at both resolutions; corrected repeated keyboard dismissal during list scrolling |
| Camera platform | AOSP camera/native-window and OEM APS/HEIF providers | Added scoped client/lifecycle compatibility, recording profiles, P010 plane handling and the omitted stock filter provider |
| Optional Camera | Original Realme Camera and OEM SDK/assets | Packaged its app-local dependencies; added filter/HEIC/session/viewer compatibility and stable thumbnails |
| Optional Photos/editor | Original Realme Photos/editor and native libraries | Added Android 16 compatibility for editor/Markup/Remover, sharing, wallpaper, media replacement and album moves |
| Updates | Lineage addon.d/backuptool and Android update_engine | Added selected-app ownership/retention checks and propagated add-on restore failures through the update path |
| GNSS | [Rapper_skull's L5 module](https://github.com/rapperskull/realme_gps_l5_enabler) and [libnvbk](https://github.com/rapperskull/libnvbk) | Preserved full containers, validated the exact GNSS record and added guarded inactive-slot migration; see its remaining validation limits |

Camera retains its OEM APK signature. The patched Photos app uses a dedicated project app key. Optional-app changes stay separate from the base app selection. Google services use the separate MindTheGapps project.
