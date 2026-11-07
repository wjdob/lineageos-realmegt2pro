"""Reject broken kernel selections before an expensive native build."""
from pathlib import Path
import sys,tempfile,unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'build'))
from kernel_layout_24 import check, check_subsystem_boot_actions, SUBSYSTEM_BOOT_NODES, SUBSYSTEM_WRITE_SOURCE


class KernelLayoutTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.tree=Path(temporary.name)
        self.board='device/realme/ferrari/BoardConfig.mk'
        self.config='device/oneplus/sm8450-common/BoardConfigCommon.mk'
        self.kernel='kernel/oneplus/sm8450'
        self.modules='kernel/oneplus/sm8450-modules'
        self.write(self.board,'TARGET_KERNEL_VERSION := 5.10\nTARGET_KERNEL_CLANG_VERSION := r563880c\ninclude device/oneplus/sm8450-common/BoardConfigCommon.mk\nTARGET_MERGE_DTBS_WILDCARD := waipio*\nTARGET_MERGE_DTBOS_WILDCARD := ferrari-21631-waipio-overlay\n')
        self.write(self.config,'ifeq ($(TARGET_USES_KERNEL_6_6),true)\ninclude unused.mk\nelse\nTARGET_KERNEL_SOURCE := '+self.kernel+'\nTARGET_KERNEL_EXT_MODULE_ROOT := '+self.modules+'\nTARGET_KERNEL_CONFIG := gki_defconfig vendor/waipio_GKI.config\nTARGET_KERNEL_EXT_MODULES := qcom/opensource/provider qcom/opensource/display-drivers/msm\nendif\n')
        self.write(self.kernel+'/Makefile','VERSION = 5\nPATCHLEVEL = 10\nSUBLEVEL = 246\n')
        self.write('device/oneplus/sm8450-common/vintf/manifest.xml','<manifest target-level="7"/>')
        self.write('hardware/interfaces/compatibility_matrices/Android.bp','vintf_compatibility_matrix { name: "framework_compatibility_matrix.7.xml", kernel_configs: ["kernel_config_t_5.10"], }')
        self.write(self.kernel+'/arch/arm64/configs/gki_defconfig','')
        self.write(self.kernel+'/arch/arm64/configs/vendor/waipio_GKI.config','')
        self.write('prebuilts/clang/host/linux-x86/clang-r563880c/bin/clang','')
        self.write(self.modules+'/qcom/opensource/provider/Makefile','')
        self.write(self.modules+'/qcom/opensource/display-drivers/msm/Makefile','KBUILD_EXTRA_SYMBOLS += $(OUT_DIR)/../sm8450-modules/qcom/opensource/provider/Module.symvers\n')
        self.overlay='kernel/oneplus/sm8450-devicetrees/oplus/ferrari-21631-waipio-overlay.dts'
        self.write(self.overlay,'#include "../qcom/waipio-mtp.dtsi"\n#include "ferrari_21631_overlay_common.dtsi"\noplus,project-id = <21631 0x216AC>;\n&qseecom_ta_mem { size = <0x0 0x02000000>; };\n')
        self.write('kernel/oneplus/sm8450-devicetrees/oplus/ferrari_21631_overlay_common.dtsi','')
        link=self.tree/self.kernel/'arch/arm64/boot/dts/vendor';link.parent.mkdir(parents=True)
        link.symlink_to(self.tree/'kernel/oneplus/sm8450-devicetrees',target_is_directory=True)
        for name in ('modules.load','modules.load.vendor_boot','modules.load.recovery'):
            self.write('device/oneplus/sm8450-common/'+name,'module.ko\nmsm_rng.ko\n')
        self.subsystems='on early-boot\n'+''.join('    exec_background u:r:vendor_qti_init_shell_bg:s0 -- /vendor/bin/init.qti.write.sh '+node+' 1\n' for node in SUBSYSTEM_BOOT_NODES)
        self.write('device/realme/ferrari/init/init.ferrari.modules.rc',
                   'on early-init\n    start vendor.modprobe\non init\n    wait_for_prop vendor.all.modules.ready 1\nservice vendor.modprobe /vendor/bin/vendor_modprobe.sh\n    seclabel u:r:vendor_modprobe:s0\n'+self.subsystems)
        self.write(SUBSYSTEM_WRITE_SOURCE,'#!/vendor/bin/sh\n')
        self.write('device/realme/ferrari/device.mk','PRODUCT_COPY_FILES += $(LOCAL_PATH)/init/init.ferrari.modules.rc:$(TARGET_COPY_OUT_VENDOR)/etc/init/hw/init.qti.kernel.rc\n')

    def write(self,name,data):
        path=self.tree/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(data)

    def test_complete_source_layout(self):
        result=check(self.tree)
        self.assertTrue(result['ok']);self.assertEqual(result['external_modules'],2)

    def test_missing_early_rng_rejected(self):
        self.write('device/oneplus/sm8450-common/modules.load.vendor_boot','module.ko\n')
        with self.assertRaisesRegex(ValueError,'hardware RNG must load'):check(self.tree)

    def test_missing_vendor_module_start_rejected(self):
        self.write('device/realme/ferrari/init/init.ferrari.modules.rc','on init\n    wait_for_prop vendor.all.modules.ready 1\n')
        with self.assertRaisesRegex(ValueError,'module-loader startup contract'):check(self.tree)

    def test_missing_init_import_destination_rejected(self):
        self.write('device/realme/ferrari/device.mk','PRODUCT_COPY_FILES :=\n')
        with self.assertRaisesRegex(ValueError,'init import target is not packaged'):check(self.tree)

    def test_native18_omitted_subsystem_boot_rejected(self):
        path=self.tree/'device/realme/ferrari/init/init.ferrari.modules.rc'
        path.write_text(path.read_text().replace(self.subsystems,''))
        with self.assertRaisesRegex(ValueError,'early-boot subsystem'):check(self.tree)

    def test_subsystem_boot_cannot_wait_for_boot_completed(self):
        with self.assertRaisesRegex(ValueError,'early-boot subsystem'):
            check_subsystem_boot_actions(self.subsystems.replace('on early-boot','on property:sys.boot_completed=1'))

    def test_wrong_subsystem_domain_rejected(self):
        with self.assertRaisesRegex(ValueError,'early-boot subsystem'):
            check_subsystem_boot_actions(self.subsystems.replace('vendor_qti_init_shell_bg','su'))

    def test_missing_write_helper_rejected(self):
        (self.tree/SUBSYSTEM_WRITE_SOURCE).unlink()
        with self.assertRaisesRegex(ValueError,'missing kernel input'):check(self.tree)

    def test_duplicate_subsystem_start_rejected(self):
        with self.assertRaisesRegex(ValueError,'early-boot subsystem'):
            check_subsystem_boot_actions(self.subsystems+self.subsystems)

    def test_contradictory_later_stop_rejected(self):
        with self.assertRaisesRegex(ValueError,'early-boot subsystem'):
            check_subsystem_boot_actions(self.subsystems+'on boot\n    write /sys/kernel/boot_adsp/boot 0\n')

    def test_unreviewed_kernel_selection_refused(self):
        path=self.tree/self.board;path.write_text(path.read_text().replace('TARGET_KERNEL_VERSION := 5.10','TARGET_KERNEL_VERSION := 6.6'))
        with self.assertRaisesRegex(ValueError,'select kernel5.10'):check(self.tree)

    def test_wrong_kernel_generation_refused(self):
        self.write(self.kernel+'/Makefile','VERSION = 6\nPATCHLEVEL = 6\nSUBLEVEL = 144\n')
        with self.assertRaisesRegex(ValueError,'not5.10.246'):check(self.tree)

    def test_missing_fragment_refused(self):
        (self.tree/self.kernel/'arch/arm64/configs/vendor/waipio_GKI.config').unlink()
        with self.assertRaisesRegex(ValueError,'missing kernel input'):check(self.tree)

    def test_missing_external_module_refused(self):
        (self.tree/self.modules/'qcom/opensource/provider/Makefile').unlink()
        with self.assertRaisesRegex(ValueError,'missing kernel input'):check(self.tree)

    def test_display_dependency_order_refused(self):
        path=self.tree/self.config;path.write_text(path.read_text().replace('qcom/opensource/provider qcom/opensource/display-drivers/msm','qcom/opensource/display-drivers/msm qcom/opensource/provider'))
        with self.assertRaisesRegex(ValueError,'selected earlier'):check(self.tree)

    def test_wrong_dts_project_refused(self):
        link=self.tree/self.kernel/'arch/arm64/boot/dts/vendor';link.unlink();link.symlink_to(self.tree,target_is_directory=True)
        with self.assertRaisesRegex(ValueError,'DTS link'):check(self.tree)

    def test_combined_overlay_required(self):
        self.write(self.overlay,'#include "../qcom/waipio-mtp.dtsi"\n')
        with self.assertRaisesRegex(ValueError,'combined Ferrari overlay'):check(self.tree)

    def test_wrong_device_fcm_refused(self):
        self.write('device/oneplus/sm8450-common/vintf/manifest.xml','<manifest target-level="8"/>')
        with self.assertRaisesRegex(ValueError,'FCM7'):check(self.tree)

    def test_removed_framework_kernel_support_refused(self):
        self.write('hardware/interfaces/compatibility_matrices/Android.bp','vintf_compatibility_matrix { name: "framework_compatibility_matrix.7.xml", kernel_configs: ["kernel_config_t_5.15"], }')
        with self.assertRaisesRegex(ValueError,'lacks the selected5.10'):check(self.tree)

    def test_wrong_kernel_toolchain_refused(self):
        path=self.tree/self.board;path.write_text(path.read_text().replace('r563880c','r547379'))
        self.write('prebuilts/clang/host/linux-x86/clang-r547379/bin/clang','')
        with self.assertRaisesRegex(ValueError,'accepted23b compiler'):check(self.tree)


if __name__=='__main__':unittest.main()
