from pathlib import Path
import hashlib,io,sys,tempfile,unittest,zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from vendor_wfd_wiring import check_archive


class WfdWiringTests(unittest.TestCase):
    def setUp(self):
        scratch=Path(__file__).resolve().parents[2]/'tmp'
        scratch.mkdir(exist_ok=True)
        self.tmp=tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(self.tmp.cleanup);self.package=Path(self.tmp.name)/'target.zip'
        self.dex=b'reviewed-selection-bytecode'
        self.rc=('service wfdservice /system_ext/bin/wfdservice\n    disabled\n'
                 'service wfdservice64 /system_ext/bin/wfdservice\n    disabled\n'
                 'on property:vendor.wfdservice=enable\n    start wfdservice\n'
                 'on property:vendor.wfdservice=disable\n    stop wfdservice\n'
                 'on property:vendor.wfdservice64=enable\n    start wfdservice64\n'
                 'on property:vendor.wfdservice64=disable\n    stop wfdservice64\n').encode()
        elf=bytearray(64);elf[:6]=b'\x7fELF\x02\x01';elf[18:20]=(183).to_bytes(2,'little')
        self.elf=bytes(elf)
        self.contract=dict(init_member='SYSTEM_EXT/etc/init/wfdservice.rc',init_sha256=hashlib.sha256(self.rc).hexdigest(),
            executable_member='SYSTEM_EXT/bin/wfdservice',executable_sha256=hashlib.sha256(self.elf).hexdigest(),
            APK_member='SYSTEM_EXT/priv-app/WfdService/WfdService.apk',DEX_member='classes.dex',DEX_sha256=hashlib.sha256(self.dex).hexdigest(),
            seccomp_member='SYSTEM_EXT/etc/seccomp_policy/wfdservice64.policy',board_platform='taro')

    def run_check(self,dexes=None,metadata=b'signature-container-one',rc=None):
        buffer=io.BytesIO()
        with zipfile.ZipFile(buffer,'w') as app:
            for name,data in dexes or [('classes.dex',self.dex)]:app.writestr(name,data)
            app.writestr('META-INF/container',metadata)
        with zipfile.ZipFile(self.package,'w') as z:
            for key,data in [('init',self.rc if rc is None else rc),('executable',self.elf),('APK',buffer.getvalue()),('seccomp',b'policy')]:
                z.writestr(self.contract[key+'_member'],data)
            z.writestr('VENDOR/build.prop',b'ro.board.platform=taro\n')
        return check_archive(self.package,self.contract)

    def test_renamed_executable_route_is_required_for_the_64_property(self):
        self.assertTrue(self.run_check()['vendor_wfd_wiring_pass'])
        old=self.rc.replace(b'service wfdservice64 /system_ext/bin/wfdservice\n',b'service wfdservice64 /system_ext/bin/wfdservice64\n')
        self.assertFalse(self.run_check(rc=old)['vendor_wfd_wiring_pass'])

    def test_new_or_changed_bytecode_requires_renewed_review(self):
        for dexes in ([('classes.dex',self.dex+b'changed')],[('classes.dex',self.dex),('classes10.dex',b'new selection')]):
            with self.subTest(dexes=dexes):self.assertFalse(self.run_check(dexes=dexes)['vendor_wfd_wiring_pass'])

    def test_apk_container_signature_metadata_is_separate_from_dex_identity(self):
        self.assertTrue(self.run_check(metadata=b'different-signature-container')['vendor_wfd_wiring_pass'])


if __name__=='__main__':unittest.main()
