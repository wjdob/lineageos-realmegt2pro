"""Catch the wrong-SoC power file and missing SIM provider found in Native22."""
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from device_responsibilities24 import check


class ResponsibilitiesTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / 'target.zip'
        self.members = {
            'VENDOR/etc/powerhint.xml': '<Powerhint><Config Target="taro" Enable="true"/></Powerhint>',
            'VENDOR/etc/vintf/manifest.xml': '<manifest><hal format="hidl"><name>android.hardware.secure_element</name><transport>hwbinder</transport><fqname>@1.2::ISecureElement/SIM1</fqname><fqname>@1.2::ISecureElement/SIM2</fqname><fqname>@1.2::ISecureElement/eSE1</fqname></hal></manifest>',
            'ODM/bin/hw/vendor.qti.secure_element@1.2-service': b'service',
            'ODM/lib64/android.hardware.secure_element@1.0-impl.so': b'implementation',
            'ODM/etc/init/vendor.qti.secure_element@1.2-service.rc': 'service secureelement-hal_1_2 /odm/bin/hw/vendor.qti.secure_element@1.2-service\n    class hal\n',
        }

    def inspect(self):
        with zipfile.ZipFile(self.path, 'w') as archive:
            for name, data in self.members.items():
                archive.writestr(name, data)
        return check(self.path)

    def test_matching_configuration(self):
        self.assertTrue(self.inspect()['passed'])

    def test_lahaina_cannot_satisfy_taro(self):
        self.members['VENDOR/etc/powerhint.xml'] = '<Powerhint><Config Target="lahaina" Enable="true"/></Powerhint>'
        self.assertIn('power hints: no enabled taro configuration for SM8450', self.inspect()['issues'])

    def test_disabled_taro_cannot_satisfy_selection(self):
        self.members['VENDOR/etc/powerhint.xml'] = '<Powerhint><Config Target="taro" Enable="false"/></Powerhint>'
        self.assertFalse(self.inspect()['passed'])

    def test_declared_hal_with_missing_implementation_fails(self):
        del self.members['ODM/lib64/android.hardware.secure_element@1.0-impl.so']
        self.assertFalse(self.inspect()['passed'])

    def test_executable_without_sim_registration_fails(self):
        self.members['VENDOR/etc/vintf/manifest.xml'] = '<manifest/>'
        self.assertIn('secure element: missing SIM1 VINTF registration', self.inspect()['issues'])

    def test_unrelated_init_service_cannot_satisfy_startup(self):
        self.members['ODM/etc/init/vendor.qti.secure_element@1.2-service.rc'] = 'service unrelated /odm/bin/unrelated\n    class hal\n'
        self.assertFalse(self.inspect()['passed'])

    def test_native24_sim_only_manifest_is_rejected(self):
        name = 'VENDOR/etc/vintf/manifest.xml'
        self.members[name] = self.members[name].replace('<fqname>@1.2::ISecureElement/SIM2</fqname>', '').replace('<fqname>@1.2::ISecureElement/eSE1</fqname>', '')
        self.assertEqual(self.inspect()['issues'], [
            'secure element: missing SIM2 VINTF registration',
            'secure element: missing eSE1 VINTF registration'])

    def test_each_cohort_instance_is_required(self):
        name = 'VENDOR/etc/vintf/manifest.xml'
        original = self.members[name]
        for instance in ('SIM1', 'SIM2', 'eSE1'):
            with self.subTest(instance=instance):
                self.members[name] = original.replace('<fqname>@1.2::ISecureElement/' + instance + '</fqname>', '')
                self.assertIn('secure element: missing ' + instance + ' VINTF registration', self.inspect()['issues'])

    def test_wrong_interface_version_or_transport_cannot_satisfy_provider(self):
        name = 'VENDOR/etc/vintf/manifest.xml'
        original = self.members[name]
        for old, new in (('@1.2::ISecureElement', '@1.0::ISecureElement'),
                         ('::ISecureElement/', '::Unrelated/'),
                         ('hwbinder', 'passthrough')):
            with self.subTest(new=new):
                self.members[name] = original.replace(old, new)
                self.assertFalse(self.inspect()['passed'])

    def test_stock_version_interface_syntax_is_accepted(self):
        self.members['VENDOR/etc/vintf/manifest.xml'] = '<manifest><hal format="hidl"><name>android.hardware.secure_element</name><transport>hwbinder</transport><version>1.2</version><interface><name>ISecureElement</name><instance>SIM1</instance><instance>SIM2</instance><instance>eSE1</instance></interface></hal></manifest>'
        self.assertTrue(self.inspect()['passed'])


if __name__ == '__main__':
    unittest.main()
