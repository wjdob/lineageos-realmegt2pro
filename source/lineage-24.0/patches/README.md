# Build patches and historical inputs

The active hash-guarded ROM recipe is `tools/build/recipe-23.2.json`, using the series under
`lineage-23.2/`. Original 23.0 inputs are historical references from
`0c4f60236c3e252d9029de3aef8007062ce72f62`. The old multi-ROM trust patch 0006, its public
certificates and installer are retired to Git history. The 23.0 recipe is read-only history.
Original files remain in the ignored migration snapshot; no existing WSL source is modified.

## LineageOS24.0 series

The authoritative active series is `tools/build/recipe-24.0.json`, using the
pinned `manifests/lineage-24.0-candidate.xml`. Retained patch files outside that
recipe are historical inputs. The current source batch reconstructs35 modified
files and12 additions; it has41 text actions plus pinned binary corrections.

| Area | Delivery |
| --- | --- |
| Device/core compatibility | Build and namespace wiring, calibration/health units, fingerprint/display handling, coherent kernel/DT/modules and conservative recording profiles |
| Boot and sensor corrections | Qualcomm module/DSP starts, RNG/performance/post-boot/thermal wiring, pjgowtham's AOD request-mode fix and the project's separate parser guard |
| Private vendor cohort | The hash-bound `.1410` extractor/output manifests preserve the reviewed backend and compatibility providers. Public vendor lower inputs stay intact. |
|0045 | Project lifecycle compatibility and callback AIDL, rebased from accepted23.2 patch0091 |
|0046 | Project checked camera-client metadata and header, rebased from0092 |
|0047 | Project format-specific Qualcomm P010 plane handling, rebased from0094 |
|0048 | Project optional filter/LUT delivery through the actual extractor and regenerated private provider |

These support optional apps; OEM APKs stay in separate packages. API37 app
profiles, compilation, actual images and device behavior have independent gates.
Native21's published build predates0045-0048. The current source batch has no new
ROM-build or runtime acceptance. See [the app plan](../docs/OPTIONAL_APPS_24.md),
[development plan](../docs/DEVELOPMENT_PLAN_24.md) and [audit](../docs/AUDIT.md).

## Retained 23.2/23.0 inputs

| Patch | Target project path | Intended change |
| --- | --- | --- |
| 0001 | device/oneplus/sm8450-common | Build configuration and module workarounds |
| 0003 | vendor/oneplus/sm8450-common | Common-V2 AIDL library label |
| 0005 | kernel/oneplus/sm8450-modules | Redundant camera-kernel struct declaration |
| 0006 (retired) | device/realme/ferrari | Historical extra-ROM trust; retrieve from Git history |
| 0007 | vendor/oneplus/sm8450-common | Remove duplicate performance VINTF entry |
| 0008 | vendor/oneplus/sm8450-common | Hash-guarded composer blob dependency change |
| 0009 | device/oneplus/sm8450-common | ROM-only selection of existing AOSP AIDL sensor multihal service |
| 0010 | build/soong | Forward a validated numeric host Go memory limit to the graph builder |

Numbers 0002 and 0004 are historical gaps, not missing migration files. Verify preimages and
record target revisions before applying active patches. Current recovery trust uses only the
pinned Lineage certificate and project release certificate; no extra-ROM installer remains.

Patch 0009 selects an implementation present in the pinned AOSP tree, rather than restoring the nonexistent named Oplus service. Source reconstruction is verified; actual ROM package contents and sensor behavior remain to be checked. Patch 0010 changes host-tool execution only and needs real graph-build validation. See the [development workflow](../docs/DEVELOPMENT.md) and [audit findings](../docs/AUDIT.md).

The Lineage 23.2 candidate recipe adds patches 0001–0035 under `lineage-23.2/` and hash-guarded blob substitutions described in `tools/build/recipe-23.2.json`. Patches 0018–0024 address Horae, WFD, qguard and qccsyshal compatibility. qccsyshal uses the pinned Lineage 21.7 full protobuf provider because all nine symbols reported missing by candidate-rom-06 are exported by that exact ARM64 prebuilt. The build runner rewrites proprietary ELF dependencies only in its private overlay and verifies input, tool, dependency tag and output hashes. The OTA build runs `check-elf-files` before packaging; package coverage requires the compatibility modules. Source reconstruction and symbol matching do not establish runtime behavior or installation readiness.

Patch 0025 exports `hardware/pixelworks/interfaces` to Make through the product's Soong
namespace list. Package-05 compiled its display consumers but omitted their runtime
Pixelworks provider libraries; live linker errors blocked the display composer and Iris
services. The corrected export and four explicit provider requirements address that
measured defect. Package-05 fails the stronger package check as expected; package-06 build
and runtime verification remain separate requirements. No low-level firmware change is
part of this correction.

Patches 0026–0028 prepare versioned TinyXML2 dependencies for 11 proprietary consumers that
still resolve to platform libtinyxml2.so. Package-06's live composer crash and offline AArch64
disassembly expose XMLDocument stack corruption: its legacy caller reserves 776 bytes, while
the packaged TinyXML2 11 constructor writes up to 880 bytes. The v34 provider stays within
776 bytes and exports the required symbols. The extraction rules, generated module declarations,
explicit provider selection and hash-pinned ELF transformations are kept together. Existing
libtinyxml2_1 consumers retain their dependencies. The new vendor_xml_abi.py gate pins reviewed
provider/caller bytes and checks dependencies, SONAME and XML imports; it is not a general ABI
detector. Source reconstruction and real-ELF regression checks pass. Broader offline review and
a corrected build/live result remain pending; no service or color functionality is disabled.


Patch 0029 reconciles the generated camera ZIP dependency and installed ELF with the existing
libziparchive_odm extraction rule. Both providers export the imported ZIP functions; no live
ZIP crash is claimed. Patches 0030/0031 correct WFD init wiring after APK disassembly showed
that taro selects vendor.wfdservice64. The selected ARM64 binary is deliberately renamed to
wfdservice during extraction; both init service names now invoke that installed executable.
No WFD service or property action is removed. Real-file regression checks accept the corrected
route and reject the original route, missing/wrong-architecture binaries, altered DEX and an
incorrect property action.

Patches 0032-0034 add product-specific AGM calibration selection. Stock opens the exact
RMX3301 file already packaged under /odm/etc/acdbdata; package-06 instead repeatedly exits
after looking for absent generic /vendor/etc/acdbdata/waipio_mtp files. Ferrari explicitly
selects the ODM directory through Soong; products without an override retain per-card and
ARRAX behavior. Host tests compile/run the actual reconstructed C selector for four cases;
the build must also verify its evaluated setting and collected calibration/module binding.
No calibration bytes or DSP firmware are replaced. Package-07 subsequently built and booted
Android; full hardware acceptance remains open. The current recipe has twenty-one files,
thirty-six text patch actions, one byte substitution and sixteen ELF fixups.

Patch 0035 restores the RMX3301 stock 32 MiB trusted-app DMA reservation in the Ferrari
overlay. Package-07 uses the generic 16 MiB reservation; Goodix G7's roughly 12 MiB allocation
fails during trusted-app loading before the native fingerprint callback crashes. All four
saved stock base trees retain 32 MiB after the stock overlay. This is an OS device-tree
correction; no trusted-app bytes, TEE or bootloader firmware are changed. The source and
packaged-image gate composes the Ferrari overlay with all four compatible base trees and
checks the pool size, allocation constraints and driver/heap references. Stock-positive,
package-07-negative and corrected-source checks pass; runtime fingerprint remains unproven.

Patch 0036 restores missing Ferrari Android boot-state reporting before HAL startup.
Goodix treated the missing vbmeta.device_state property as locked and rejected the retained
calibration on this physically unlocked phone. The patch exports unlocked only for project
21631, an empty property and an explicit orange verified-boot report. Existing supplied
values and other states/devices are preserved; no physical bootloader state or calibration
is changed. Nineteen actual-C++ mocked-property cases and original/guard-removal negative
controls pass. Current-session calibration, physical enrollment and two authentication
callbacks pass with the equivalent RAM correction; source-built reboot proof remains open.

## MVP external firmware

`lineage-23.2/0023-ferrari-external-firmware.patch` removes low-level radio image registration and the 24 vendor A/B firmware entries. Both vendor makefiles are pinned and hash-checked by the 23.2 recipe. It retains the OS images and existing vendor libraries. The package gate validates the actual write set and pinned OTA signer; runtime firmware compatibility is still a separate requirement. Private signing keys are staged by the runner through the existing Lineage private-keys include, not stored in this patch or repository.


## Android 17 first-native consolidation

The 24.0 recipe has 16 exact patch actions, 16 modified files and two added init
files. Patches 0017/0018 connect Ferrari to pjgowtham's pinned WAIPIO 6.6 integration:
explicit board opt-in, existing checkout paths, WAIPIO DTB filtering, legacy
Synx/EVA module paths and display symbol-provider order. These are local wiring
corrections to upstream kernel/common foundations; no source revision changed.

Patch 0019 and the two init templates carry the project's 23.2 display scheduling
and fingerprint-provider restart corrections into Ferrari only. Patch 0020 retains
Android 17's upstream HIDL user reset/death lifecycle and adds handler serialization,
with its regression test. Android compilation and device execution are distinct
from recipe reconstruction. The Codec2 allocator fix still awaits the newly
compiled Android 17 provider's layout; its Android16 size is not assumed.
