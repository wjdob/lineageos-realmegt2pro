from pathlib import Path
import sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from agm_calibration import verify_configuration,bind_sources


class AgmConfigurationTests(unittest.TestCase):
    contract={'namespace':'qti_agm','variable':'acdb_path','path':'/odm/etc/acdbdata'}

    def test_product_setting_is_read_from_evaluated_soong_namespace(self):
        result=verify_configuration({'VendorVars':{'qti_agm':{'acdb_path':'/odm/etc/acdbdata'}}},self.contract)
        self.assertEqual(result['value'],'/odm/etc/acdbdata')

    def test_missing_or_wrong_setting_cannot_silently_use_generic_path(self):
        for variables in ({},{'VendorVars':{}},{'VendorVars':{'qti_agm':{'acdb_path':'/vendor/etc/acdbdata'}}}):
            with self.subTest(variables=variables),self.assertRaises(ValueError):verify_configuration(variables,self.contract)

    def test_older_source_snapshot_cannot_claim_the_corrected_calibration_route(self):
        contract=dict(self.contract,source_sha256={'agm/service/src/graph.c':'corrected'})
        inputs={'target':'otapackage','manifest_sha256':'manifest','recipe_snapshot':{
            'manifest_sha256':'manifest','files':[{'path':'agm/service/src/graph.c','canonical_sha256':'old'}]}}
        with self.assertRaisesRegex(ValueError,'same-run recipe'):bind_sources(inputs,contract)


if __name__=='__main__':unittest.main()
