from pathlib import Path
import sys,tempfile,unittest,zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from package_coverage import check,archive_path,merge_requirements,bind_requirement_source,bind_additional_requirements,check_ramdisk_files


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.package=Path(self.temp.name)/'target.zip'
        self.metadata={'service':{'installed':['out/target/product/ferrari/vendor/bin/hw/service']}}

    def write(self,entries):
        with zipfile.ZipFile(self.package,'w') as archive:
            for path,data in entries.items():archive.writestr(path,data)

    def test_exact_partition_and_path(self):
        self.write({'VENDOR/bin/hw/service':b'executable'})
        self.assertTrue(check(self.package,self.metadata,['service'])['package_presence_pass'])

    def test_same_basename_other_partition_rejected(self):
        self.write({'SYSTEM/bin/hw/service':b'executable'})
        self.assertFalse(check(self.package,self.metadata,['service'])['package_presence_pass'])

    def test_manifest_cannot_substitute_for_executable(self):
        self.write({'VENDOR/etc/vintf/manifest/service.xml':b'<manifest/>'})
        self.assertFalse(check(self.package,self.metadata,['service'])['package_presence_pass'])

    def test_empty_member_rejected(self):
        self.write({'VENDOR/bin/hw/service':b''})
        self.assertFalse(check(self.package,self.metadata,['service'])['package_presence_pass'])

    def test_missing_metadata_rejected(self):
        self.write({'VENDOR/bin/hw/service':b'executable'})
        self.assertFalse(check(self.package,{},['service'])['package_presence_pass'])

    def test_absent_installed_paths_rejected(self):
        self.write({})
        self.assertFalse(check(self.package,{'service':{'path':['source']}},['service'])['package_presence_pass'])

    def test_path_escape_rejected(self):
        with self.assertRaises(ValueError):archive_path('out/target/product/ferrari/vendor/../../escape','out/target/product/ferrari')

    def test_odm_and_system_ext_mappings(self):
        for partition in ('odm','system_ext'):
            self.assertEqual(archive_path('out/target/product/ferrari/'+partition+'/etc/example','out/target/product/ferrari'),partition.upper()+'/etc/example')

    def test_repeated_source_requirement_is_checked_once_and_reported(self):
        required,duplicates,count=merge_requirements((['service','WfdService'],['WfdService','sensor']))
        self.assertEqual(required,['service','WfdService','sensor'])
        self.assertEqual(duplicates,['WfdService'])
        self.assertEqual(count,4)

    def test_empty_requirement_groups_rejected(self):
        with self.assertRaises(ValueError):merge_requirements(([],[]))

    def test_ramdisk_variant_is_checked_at_its_exact_path_without_metadata_alias(self):
        required=[{'module_alias':'init.oplus.hw.rc.recovery','member':'RECOVERY/RAMDISK/system/etc/init/init.oplus.hw.rc'}]
        self.write({'RECOVERY/RAMDISK/system/etc/init/init.oplus.hw.rc':b'configuration'})
        self.assertTrue(check_ramdisk_files(self.package,required)['ramdisk_presence_pass'])
        self.write({'VENDOR/etc/init/init.oplus.hw.rc':b'configuration'})
        self.assertFalse(check_ramdisk_files(self.package,required)['ramdisk_presence_pass'])

    def test_ramdisk_missing_or_empty_file_is_rejected(self):
        required=[{'module_alias':'fastbootd','member':'RECOVERY/RAMDISK/system/bin/fastbootd'}]
        for entries in ({},{required[0]['member']:b''}):
            self.write(entries)
            self.assertFalse(check_ramdisk_files(self.package,required)['ramdisk_presence_pass'])

    def test_ramdisk_escape_duplicate_and_empty_contract_are_rejected(self):
        self.write({})
        entry={'module_alias':'service','member':'RECOVERY/RAMDISK/system/bin/service'}
        for required in ([],[entry,entry],[dict(entry,member='RECOVERY/RAMDISK/../escape')],
                         [dict(entry,member='SYSTEM/bin/service')]):
            with self.assertRaises(ValueError):check_ramdisk_files(self.package,required)

    def test_requirement_source_bound_to_candidate_recipe(self):
        inputs={'target':'otapackage','manifest_sha256':'manifest-hash',
                'recipe_snapshot':{'manifest_sha256':'manifest-hash','files':[
                    {'path':'vendor/common/vendor.mk','revision':'abc',
                     'canonical_sha256':'source-hash'}]}}
        req={'source_makefile':'vendor/common/vendor.mk',
             'source_revision_before_recipe':'abc','source_sha256':'source-hash'}
        self.assertEqual(bind_requirement_source(req,inputs),
                         {'path':'vendor/common/vendor.mk','revision':'abc',
                          'sha256':'source-hash','manifest_sha256':'manifest-hash'})
        req['source_sha256']='wrong'
        with self.assertRaises(ValueError):bind_requirement_source(req,inputs)

    def test_candidate_requirement_requires_input_record(self):
        req={'source_revision_before_recipe':'abc'}
        with self.assertRaisesRegex(ValueError,'candidate input record required'):
            bind_requirement_source(req)

    def test_legacy_requirement_can_omit_candidate_input_record(self):
        self.assertIsNone(bind_requirement_source({'source_sha256':'legacy-hash'}))

    def test_additional_device_list_is_bound_and_actually_checked(self):
        inputs={'target':'otapackage','manifest_sha256':'manifest-hash',
                'recipe_snapshot':{'manifest_sha256':'manifest-hash','files':[
                    {'path':'vendor/device/vendor.mk','revision':'device-rev','canonical_sha256':'device-hash'}]}}
        req={'additional_requirement_groups':[{'name':'device','source_makefile':'vendor/device/vendor.mk',
             'source_revision_before_recipe':'device-rev','source_sha256':'device-hash','modules':['missing-device-service']}]}
        groups,bindings=bind_additional_requirements(req,inputs)
        required,_,_=merge_requirements((['service'],*groups))
        self.write({'VENDOR/bin/hw/service':b'executable'})
        result=check(self.package,self.metadata,required)
        self.assertFalse(result['package_presence_pass'])
        self.assertEqual(result['modules'][1]['module'],'missing-device-service')
        self.assertEqual(bindings[0]['path'],'vendor/device/vendor.mk')
        req['additional_requirement_groups'][0]['source_sha256']='wrong-device-hash'
        with self.assertRaisesRegex(ValueError,'source hash differs'):
            bind_additional_requirements(req,inputs)

    def test_additional_lists_cannot_omit_provenance_or_reuse_group_names(self):
        entry={'name':'device','source_makefile':'vendor/device/vendor.mk',
               'source_revision_before_recipe':'rev','source_sha256':'hash','modules':['service']}
        with self.assertRaisesRegex(ValueError,'candidate input record required'):
            bind_additional_requirements({'additional_requirement_groups':[entry]})
        inputs={'target':'otapackage','manifest_sha256':'manifest',
                'recipe_snapshot':{'manifest_sha256':'manifest','files':[
                    {'path':'vendor/device/vendor.mk','revision':'rev','canonical_sha256':'hash'}]}}
        with self.assertRaisesRegex(ValueError,'unique nonempty'):
            bind_additional_requirements({'additional_requirement_groups':[entry,entry]},inputs)
        with self.assertRaisesRegex(ValueError,'nonempty additional module'):
            bind_additional_requirements({'additional_requirement_groups':[dict(entry,modules=[])]},inputs)
