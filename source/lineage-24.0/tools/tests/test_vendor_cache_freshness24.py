"""Exercise stale prebuilt reuse with real Ninja and content-bound success records."""
from pathlib import Path
import hashlib,json,os,shutil,subprocess,sys,tempfile,time,unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'build'))
import output_cache_24 as cache

class VendorFreshnessTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.tree=self.root/'tree';self.tree.mkdir()
        self.output=self.root/'cache/out';self.output.mkdir(parents=True)
        self.path=self.tree/'vendor/realme/ferrari/proprietary/test.so'
        self.path.parent.mkdir(parents=True);self.path.write_bytes(b'correct')
        self.enterContext(patch.object(cache,'isolated'))
    def contract(self):
        return {'files':[{'path':'proprietary/test.so','sha256':hashlib.sha256(self.path.read_bytes()).hexdigest()}]}
    def prepare(self):return cache.vendor_freshness(self.tree,self.output,self.contract())
    def success(self,freshness,state='success'):
        inputs=self.root/'inputs.json';inputs.write_text(json.dumps({'output_cache':{'vendor_freshness':freshness}}))
        record=self.root/'result.json';record.write_text(json.dumps({'state':state,'exit_code':0 if state=='success' else 1,'finished_ns':time.time_ns(),'command':['bash','build_candidate_24.0.sh','otapackage',str(inputs)]}))
        return record
    def test_real_ninja_rebuilds_older_corrected_input_after_freshness(self):
        ninja=os.environ.get('CANDIDATE_NINJA') or shutil.which('ninja')
        if not ninja:self.skipTest('real Ninja required')
        self.path.write_bytes(b'old');dest=self.output/'copied.so'
        graph=self.root/'build.ninja';graph.write_text('rule copy\n  command = cp $in $out\nbuild '+str(dest)+': copy '+str(self.path)+'\n')
        def build():subprocess.run([ninja,'-f',str(graph)],check=True,capture_output=True)
        build();self.path.write_bytes(b'correct');os.utime(self.path,(1,1))
        build();self.assertEqual(dest.read_bytes(),b'old')
        self.prepare();build();self.assertEqual(dest.read_bytes(),b'correct')
    def test_successful_unchanged_input_keeps_mtime(self):
        first=self.prepare();cache.record_vendor_success(first,self.success(first))
        before=self.path.stat().st_mtime_ns
        self.assertEqual(self.prepare()['refreshed'],[])
        self.assertEqual(self.path.stat().st_mtime_ns,before)
    def test_changed_content_is_refreshed_after_success(self):
        first=self.prepare();cache.record_vendor_success(first,self.success(first))
        self.path.write_bytes(b'changed');os.utime(self.path,(1,1))
        self.assertEqual(len(self.prepare()['refreshed']),1)
        self.assertGreater(self.path.stat().st_mtime_ns,10**9)
    def test_failed_build_cannot_advance_receipt(self):
        first=self.prepare()
        with self.assertRaisesRegex(ValueError,'successful OTA'):
            cache.record_vendor_success(first,self.success(first,'failed'))
        self.assertFalse((self.output.parent/'vendor-inputs-success.json').exists())
        self.assertEqual(len(self.prepare()['refreshed']),1)
    def test_modified_completion_record_is_refused(self):
        first=self.prepare();record=self.success(first);cache.record_vendor_success(first,record)
        record.write_text('{}')
        with self.assertRaisesRegex(ValueError,'completion record differs'):self.prepare()
    def test_modified_input_record_is_refused(self):
        first=self.prepare();cache.record_vendor_success(first,self.success(first))
        (self.root/'inputs.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'input record differs'):self.prepare()
    def test_wrong_hash_refuses_before_any_timestamp_change(self):
        before=self.path.stat().st_mtime_ns;contract=self.contract();contract['files'][0]['sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'input differs'):cache.vendor_freshness(self.tree,self.output,contract)
        self.assertEqual(self.path.stat().st_mtime_ns,before)
    def test_escaped_source_is_refused(self):
        with self.assertRaises(ValueError):cache.vendor_freshness(self.tree,self.output,{'files':[{'path':'../../../../escape','sha256':'0'*64}]})

if __name__=='__main__':unittest.main()
