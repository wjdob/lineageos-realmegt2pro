"""Catch structural kernel load failures without loading modules or a device."""
import json
from pathlib import Path
import struct
import tempfile
import unittest
import zipfile

import kernel_modules as gate

RELEASE='5.10.246-test'
VERMAGIC=RELEASE+' SMP preempt mod_unload modversions aarch64'


def module(depends='', vermagic=VERMAGIC, machine=183, kind=1):
    strings=b'\0.shstrtab\0.modinfo\0'
    payload=('vermagic='+vermagic+'\0depends='+depends+'\0license=GPL\0').encode()
    string_offset=64; info_offset=string_offset+len(strings)
    section_offset=(info_offset+len(payload)+7)&~7
    header=struct.pack('<16sHHIQQQIHHHHHH', b'\x7fELF\x02\x01\x01'+bytes(9),kind,machine,1,
                       0,0,section_offset,0,64,0,0,64,3,1)
    sections=bytes(64)+struct.pack('<IIQQQQIIQQ',1,3,0,0,string_offset,len(strings),0,0,1,0)
    sections+=struct.pack('<IIQQQQIIQQ',strings.index(b'.modinfo'),1,2,0,info_offset,len(payload),0,0,1,0)
    return header+strings+payload+bytes(section_offset-info_offset-len(payload))+sections


class KernelModuleTests(unittest.TestCase):
    def setUp(self):
        root=Path(__file__).resolve().parents[2]/'tmp'
        self.tmp=tempfile.TemporaryDirectory(prefix='kernel-module-check-',dir=root)
        self.addCleanup(self.tmp.cleanup)
        self.archive=Path(self.tmp.name)/'target.zip'
        self.files={'META/kernel_version.txt': RELEASE.encode()}
        for pool,(prefix,loads) in gate.POOLS.items():
            self.files[pool+'/provider.ko']=module()
            self.files[pool+'/consumer-mod.ko']=module('provider')
            self.files[pool+'/modules.dep']=(prefix+'provider.ko:\n'+prefix+'consumer-mod.ko: '+prefix+'provider.ko\n').encode()
            for name in loads:self.files[pool+'/'+name]=b'consumer_mod\n'
        self.pool=next(iter(gate.POOLS))

    def check(self):
        with zipfile.ZipFile(self.archive,'w') as z:
            for name,data in self.files.items():z.writestr(name,data)
        return gate.check(self.archive)

    def test_complete_files_load_lists_and_modinfo_dependencies_pass(self):
        result=self.check()
        self.assertTrue(result['kernel_modules_pass'],result['issues'])
        self.assertEqual(result['module_count'],4)
        self.assertEqual(result['kernel_release'],RELEASE)

    def test_missing_load_root_fails(self):
        self.files[self.pool+'/modules.load']=b'absent\n'
        self.assertFalse(self.check()['kernel_modules_pass'])

    def test_missing_module_file_or_required_recovery_list_fails(self):
        del self.files[self.pool+'/provider.ko']
        self.assertFalse(self.check()['kernel_modules_pass'])
        self.files[self.pool+'/provider.ko']=module()
        del self.files[self.pool+'/modules.load.recovery']
        self.assertFalse(self.check()['kernel_modules_pass'])

    def test_modinfo_dependency_cannot_be_omitted_from_depmod(self):
        prefix=gate.POOLS[self.pool][0]
        self.files[self.pool+'/modules.dep']=(prefix+'provider.ko:\n'+prefix+'consumer-mod.ko:\n').encode()
        result=self.check()
        self.assertFalse(result['kernel_modules_pass'])
        self.assertTrue(any('modinfo dependency' in x for x in result['issues']))

    def test_unreachable_staging_depmod_rows_are_not_mandatory_modules(self):
        prefix=gate.POOLS[self.pool][0]
        self.files[self.pool+'/modules.dep']+=(prefix+'not-installed.ko: '+prefix+'other-not-installed.ko\n').encode()
        result=self.check()
        self.assertTrue(result['kernel_modules_pass'],result['issues'])
        self.assertEqual(result['groups'][0]['unused_dependency_records'],['not-installed.ko'])

    def test_duplicate_valid_load_entries_are_reported_without_failure(self):
        self.files[self.pool+'/modules.load']=b'consumer-mod\nconsumer_mod\n'
        result=self.check()
        self.assertTrue(result['kernel_modules_pass'],result['issues'])
        self.assertEqual(result['groups'][0]['load_lists'][0]['duplicates'],['consumer_mod'])

    def test_cycles_and_missing_declared_dependency_files_fail(self):
        prefix=gate.POOLS[self.pool][0]
        self.files[self.pool+'/modules.dep']=(prefix+'provider.ko: '+prefix+'consumer-mod.ko\n'+prefix+'consumer-mod.ko: '+prefix+'provider.ko\n').encode()
        self.assertFalse(self.check()['kernel_modules_pass'])
        self.files[self.pool+'/modules.dep']=(prefix+'provider.ko:\n'+prefix+'consumer-mod.ko: '+prefix+'missing.ko\n').encode()
        self.assertFalse(self.check()['kernel_modules_pass'])

    def test_dependency_traversal_and_foreign_absolute_paths_fail(self):
        prefix=gate.POOLS[self.pool][0]
        for target in ['../provider.ko','/data/provider.ko']:
            with self.subTest(target=target):
                self.files[self.pool+'/modules.dep']=(prefix+'provider.ko:\n'+prefix+'consumer-mod.ko: '+target+'\n').encode()
                self.assertFalse(self.check()['kernel_modules_pass'])

    def test_wrong_architecture_or_shared_object_is_not_a_module(self):
        for content in [module(machine=62),module(kind=3),b'not an ELF']:
            with self.subTest(content=content[:20]):
                self.files[self.pool+'/provider.ko']=content
                self.assertFalse(self.check()['kernel_modules_pass'])

    def test_kernel_release_and_full_vermagic_must_agree(self):
        self.files[self.pool+'/provider.ko']=module(vermagic='5.10.246-other SMP')
        self.assertFalse(self.check()['kernel_modules_pass'])
        self.files[self.pool+'/provider.ko']=module(vermagic=RELEASE+' SMP')
        self.assertFalse(self.check()['kernel_modules_pass'])

    def test_missing_depmod_file_and_unexpected_pool_fail(self):
        del self.files[self.pool+'/modules.dep']
        self.assertFalse(self.check()['kernel_modules_pass'])
        self.files['SYSTEM/unexpected.ko']=module()
        self.assertFalse(self.check()['kernel_modules_pass'])

    def test_ambiguous_normalized_names_fail(self):
        self.files[self.pool+'/consumer_mod.ko']=module('provider')
        self.assertFalse(self.check()['kernel_modules_pass'])

    def test_duplicate_zip_member_is_rejected(self):
        with zipfile.ZipFile(self.archive,'w') as z:
            z.writestr('META/kernel_version.txt',RELEASE)
            with self.assertWarns(UserWarning):z.writestr('META/kernel_version.txt',RELEASE)
        with self.assertRaises(ValueError):gate.check(self.archive)

    def test_bad_section_bounds_and_ambiguous_vermagic_are_rejected(self):
        value=bytearray(module());struct.pack_into('<Q',value,40,len(value)+64)
        with self.assertRaises(ValueError):gate.modinfo(value)
        # Reuse a payload allocation with a second key, without reflecting gate internals.
        value=module(depends='\0vermagic=duplicate')
        with self.assertRaises(ValueError):gate.modinfo(value)


if __name__=='__main__':unittest.main()
