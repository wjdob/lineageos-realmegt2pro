"""Catch the native15 module-loader omission in actual package members."""
from pathlib import Path
import hashlib,sys,tempfile,unittest,zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'build'))
from verify_vendor_24 import check_boot_startup
from kernel_layout_24 import SUBSYSTEM_BOOT_NODES

class BootStartupPackage(unittest.TestCase):
    def fixture(self,omit=None,early=b'msm_rng\n',executable=True,subsystems=True,helper_executable=True):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        path=Path(temp.name)/'target.zip'
        loader=b'on early-init\n    start vendor.modprobe\n'
        if subsystems:
            loader+=('on early-boot\n'+''.join('    exec_background u:r:vendor_qti_init_shell_bg:s0 -- /vendor/bin/init.qti.write.sh '+node+' 1\n' for node in SUBSYSTEM_BOOT_NODES)).encode()
        files={'VENDOR/etc/init/hw/init.qti.kernel.rc':loader,
               'VENDOR/etc/init/hw/init.target.rc':b'import /vendor/etc/init/hw/init.qti.kernel.rc\n',
               'VENDOR/bin/vendor_modprobe.sh':b'setprop vendor.all.modules.ready 1\n',
               'VENDOR/bin/init.qti.write.sh':b'#!/vendor/bin/sh\n',
               'META/vendor_filesystem_config.txt':('vendor/bin/vendor_modprobe.sh 0 2000 '+('755' if executable else '644')+' capabilities=0x0\n'+'vendor/bin/init.qti.write.sh 0 2000 '+('755' if helper_executable else '644')+' capabilities=0x0\n').encode(),
               'VENDOR_BOOT/RAMDISK/lib/modules/modules.load':early,
               'VENDOR_BOOT/RAMDISK/lib/modules/msm_rng.ko':b'\x7fELFmodule-fixture'}
        with zipfile.ZipFile(path,'w') as z:
            for name,data in files.items():
                if name==omit:continue
                info=zipfile.ZipInfo(name)
                # Target-files ZIP attributes need not equal installed modes.
                info.external_attr=0o100644<<16
                z.writestr(info,data)
        return path,hashlib.sha256(loader).hexdigest()

    def test_complete_package_passes(self):
        self.assertTrue(check_boot_startup(*self.fixture())['boot_startup_pass'])

    def test_native15_missing_loader_rejected(self):
        self.assertFalse(check_boot_startup(*self.fixture(omit='VENDOR/etc/init/hw/init.qti.kernel.rc'))['boot_startup_pass'])

    def test_only_recovery_rng_does_not_qualify_normal_boot(self):
        self.assertFalse(check_boot_startup(*self.fixture(early=b'other_module\n'))['boot_startup_pass'])

    def test_missing_rng_bytes_rejected(self):
        self.assertFalse(check_boot_startup(*self.fixture(omit='VENDOR_BOOT/RAMDISK/lib/modules/msm_rng.ko'))['boot_startup_pass'])

    def test_nonexecutable_loader_rejected(self):
        self.assertFalse(check_boot_startup(*self.fixture(executable=False))['boot_startup_pass'])

    def test_changed_loader_cannot_reuse_recipe_claim(self):
        path,_=self.fixture()
        self.assertFalse(check_boot_startup(path,'0'*64)['boot_startup_pass'])

    def test_native18_missing_subsystem_actions_rejected(self):
        self.assertFalse(check_boot_startup(*self.fixture(subsystems=False))['boot_startup_pass'])

    def test_missing_subsystem_helper_rejected(self):
        self.assertFalse(check_boot_startup(*self.fixture(omit='VENDOR/bin/init.qti.write.sh'))['boot_startup_pass'])

    def test_nonexecutable_subsystem_helper_rejected(self):
        self.assertFalse(check_boot_startup(*self.fixture(helper_executable=False))['boot_startup_pass'])

    def test_helper_must_match_frozen_source(self):
        package,loader=self.fixture()
        self.assertFalse(check_boot_startup(package,loader,write_helper_sha256='0'*64)['boot_startup_pass'])

    def test_missing_postboot_dispatcher_rejected_when_selected(self):
        path,loader=self.fixture()
        result=check_boot_startup(path,loader,'0'*64)
        self.assertFalse(result['boot_startup_pass'])
        self.assertTrue(any('post_boot.sh' in issue for issue in result['issues']))

if __name__=='__main__':unittest.main()
