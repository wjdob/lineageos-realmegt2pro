from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from install_guard import validate_fastboot, validate_recovery_ab_ota_mappings


class InstallGuardTests(unittest.TestCase):
    def test_fresh_unmapped_recovery_can_start_ab_ota(self):
        validate_recovery_ab_ota_mappings([])
        validate_recovery_ab_ota_mappings(())

    def test_unmounted_but_still_mapped_source_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'restart recovery'):
            validate_recovery_ab_ota_mappings(['system_b','product_b'])

    def test_cow_mapper_is_also_rejected(self):
        with self.assertRaises(ValueError):
            validate_recovery_ab_ota_mappings(['system_b-cow'])

    def test_unknown_mapper_observation_is_not_empty_success(self):
        for names in (None,'',{},[None],['']):
            with self.subTest(names=names),self.assertRaises(ValueError):
                validate_recovery_ab_ota_mappings(names)

    def test_kernel_boot_image_and_explicit_recovery_write_are_allowed(self):
        validate_fastboot(['flash','boot_a','boot.img'],permitted_writes=['boot_a'])
        validate_fastboot(['flash','recovery_b','recovery.img'],permitted_writes=['recovery_b'])

    def test_no_firmware_or_lock_state_write_even_if_caller_permits_it(self):
        for name in ('abl','xbl','xbl_config','xbl_ramdump','bootloader','aop','tz','keymaster',
                     'hyp','uefi','imagefv','modem','devinfo','frp','config','persist'):
            for target in (name,name+'_a',name+'_b'):
                with self.subTest(target=target),self.assertRaises(ValueError):
                    validate_fastboot(['flash',target,'image.img'],permitted_writes=[target])

    def test_lock_unlock_and_opaque_aggregate_commands_are_rejected(self):
        for args in (['flashing','lock'],['flashing','unlock'],['flashing','unlock_critical'],
                     ['oem','lock'],['oem','unlock'],['flashall'],['update','images.zip'],
                     ['-w'],['erase','userdata'],['snapshot-update','cancel']):
            with self.subTest(args=args),self.assertRaises(ValueError):
                validate_fastboot(args)

    def test_unlisted_os_and_hidden_flags_rejected(self):
        with self.assertRaises(ValueError):validate_fastboot(['flash','boot_b','boot.img'])
        with self.assertRaises(ValueError):validate_fastboot(['--disable-verification','flash','vbmeta_a','vbmeta.img'],permitted_writes=['vbmeta_a'])

    def test_reboot_to_bootloader_is_a_mode_transition(self):
        validate_fastboot(['reboot','bootloader'])
        validate_fastboot(['getvar','unlocked'])

    def test_filename_position_cannot_smuggle_global_flags(self):
        for filename in ('-w','--slot=all','--disable-verification'):
            with self.subTest(filename=filename),self.assertRaises(ValueError):
                validate_fastboot(['flash','boot_a',filename],permitted_writes=['boot_a'])

    def test_super_and_slot_change_need_explicit_return_scope(self):
        with self.assertRaises(ValueError):validate_fastboot(['flash','super','super.img'],permitted_writes=['super'])
        validate_fastboot(['flash','super','super.img'],permitted_writes=['super'],allow_super_restore=True)
        with self.assertRaises(ValueError):validate_fastboot(['set_active','b'])
        validate_fastboot(['set_active','b'],allow_slot_change=True)
