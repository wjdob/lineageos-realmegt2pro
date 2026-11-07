import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'build'))
from run_build import execute,write_json
from apply_recipe import known_state


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);(self.root/'out').mkdir()

    def run_fixture(self,script,**kw):
        return execute([sys.executable,'-c',script],self.root,['out/recovery.img'],self.root/'record',min_free=0,space_path=self.root,poll=.01,**kw)

    def test_success_collects_hash(self):
        r=self.run_fixture("from pathlib import Path;Path('out/recovery.img').write_bytes(b'new image')")
        self.assertEqual(r['state'],'success')
        self.assertEqual(r['artifacts'][0]['sha256'],hashlib.sha256(b'new image').hexdigest())

    def test_secondary_volume_floor_blocks_before_start(self):
        from types import SimpleNamespace
        guarded=self.root/'guarded'
        def usage(path):
            return SimpleNamespace(free=0 if path==guarded else 1000,used=0)
        with patch('run_build.shutil.disk_usage',side_effect=usage):
            result=self.run_fixture("from pathlib import Path;Path('started').touch()",
                                    extra_space_floors=((guarded,1),))
        self.assertEqual(result['state'],'failed')
        self.assertIn('storage reserve reached',result['error'])
        self.assertFalse((self.root/'started').exists())

    def test_failed_build_rejects_stale_image(self):
        (self.root/'out/recovery.img').write_bytes(b'stale')
        r=self.run_fixture('raise SystemExit(7)')
        self.assertEqual(r['state'],'failed');self.assertEqual(r['exit_code'],7)
        self.assertFalse(r['artifacts'])

    def test_success_without_output_fails(self):
        (self.root/'out/recovery.img').write_bytes(b'stale')
        self.assertEqual(self.run_fixture('pass')['state'],'failed')

    def test_old_timestamp_fails(self):
        script="from pathlib import Path;import os;Path('out/recovery.img').write_bytes(b'x');os.utime('out/recovery.img',(1,1))"
        self.assertIn('stale',self.run_fixture(script)['error'])

    def test_timeout_recorded(self):
        self.assertEqual(self.run_fixture('import time;time.sleep(30)',timeout=.05)['error'],'timeout')

    def test_cancel_records_failure(self):
        result=self.run_fixture("from pathlib import Path;import time;Path('record/cancel').touch();time.sleep(30)")
        self.assertEqual(result['error'],'cancel requested')
        self.assertEqual(result['state'],'failed')
        self.assertFalse(result['artifacts'])
        self.assertIn('heartbeat_ns',result)

    def test_signal_records_interruption(self):
        result=self.run_fixture('import os,signal,time;os.kill(os.getppid(),signal.SIGTERM);time.sleep(30)')
        self.assertEqual(result['state'],'failed')
        self.assertEqual(result['error'],'interrupted')
        self.assertFalse(result['artifacts'])

    def test_unknown_preimage_rejected(self):
        row=dict(path='test',base_sha256='a'*64,legacy_sha256='b'*64,canonical_sha256='c'*64)
        with self.assertRaises(ValueError):known_state(row,b'unknown')

    def test_transient_record_sharing_denial_retried(self):
        import os
        actual_replace=os.replace
        target=self.root/'state.json'
        calls=[]
        def replace(source,destination):
            calls.append(destination)
            if len(calls)==1:raise PermissionError('reader holds destination')
            actual_replace(source,destination)
        with patch('run_build.os.replace',side_effect=replace),patch('run_build.time.sleep'):
            write_json(target,{'state':'running'})
        self.assertEqual(json.loads(target.read_text()),{'state':'running'})
        self.assertEqual(len(calls),2)

    def test_persistent_record_denial_fails_and_preserves_previous(self):
        target=self.root/'state.json';target.write_text('{"state":"previous"}')
        with patch('run_build.os.replace',side_effect=PermissionError('denied')) as replace,patch('run_build.time.sleep'):
            with self.assertRaises(PermissionError):write_json(target,{'state':'success'})
        self.assertEqual(replace.call_count,51)
        self.assertEqual(json.loads(target.read_text())['state'],'previous')

    def test_module_info_collected(self):
        result=execute([sys.executable,'-c',"from pathlib import Path;Path('out/module-info.json').write_text('{}')"],self.root,['out/module-info.json'],self.root/'record',min_free=0,space_path=self.root,poll=.01)
        self.assertEqual(result['state'],'success')
        self.assertEqual(result['artifacts'][0]['bytes'],2)

    def test_escaping_output_rejected_before_command(self):
        result=execute([sys.executable,'-c','raise SystemExit(99)'],self.root,['../escape.img'],self.root/'record',min_free=0,space_path=self.root,poll=.01)
        self.assertEqual(result['state'],'failed')
        self.assertIn('escapes tree',result['error'])
        self.assertNotIn('exit_code',result)

    def test_exact_codec_probe_collected_with_hash(self):
        relative='out/target/product/ferrari/vendor/lib64/libcodec2_hidl@1.0.so'
        script="from pathlib import Path;p=Path(%r);p.parent.mkdir(parents=True);p.write_bytes(b'compiled probe')" % relative
        result=execute([sys.executable,'-c',script],self.root,[relative],self.root/'record',min_free=0,space_path=self.root,poll=.01)
        self.assertEqual(result['state'],'success')
        self.assertEqual(result['artifacts'][0]['sha256'],hashlib.sha256(b'compiled probe').hexdigest())

    def test_arbitrary_shared_library_rejected_before_command(self):
        result=execute([sys.executable,'-c','raise SystemExit(99)'],self.root,['out/target/product/ferrari/vendor/lib64/arbitrary.so'],self.root/'record',min_free=0,space_path=self.root,poll=.01)
        self.assertEqual(result['state'],'failed')
        self.assertIn('exact Codec2 probe',result['error'])
        self.assertNotIn('exit_code',result)
