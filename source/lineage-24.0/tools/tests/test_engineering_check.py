from pathlib import Path
import os,shutil,subprocess,sys,tempfile,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from build_engineering_check import script

class EngineeringReadOnlyCheckTests(unittest.TestCase):
    def test_invalid_bindings_refuse_before_build(self):
        for digest,session in [('a'*63,'session'),('a'*64,"session';bad"),('a'*64,'')]:
            with self.assertRaises(ValueError):script(digest,session)

    @unittest.skipUnless(os.name=='posix' and shutil.which('sh'),'POSIX shell and /proc required')
    def test_actual_script_pass_and_refusal_with_controlled_read_only_tools(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);binary=root/'bin';binary.mkdir();test=root/'update-binary';test.write_bytes(script('a'*64,'test-session'))
            commands={
                'id':'#!/bin/sh\necho 0\n',
                'getprop':'''#!/bin/sh
case "$1" in
ro.bootmode) echo recovery;; ro.product.model) echo RMX3301;; ro.build.version.sdk) echo 37;;
ro.boot.vbmeta.device_state) echo unlocked;; ro.boot.slot_suffix) echo _a;;
ro.lineage.recovery.engineering) echo 1;; ro.adb.secure) echo 1;;
ro.adb.secure.recovery) echo "${AUTH_VALUE:-1}";; esac
''',
                'sha256sum':'#!/bin/sh\nprintf "%s  %s\\n" "'+('a'*64)+'" "$1"\n'}
            for name,text in commands.items():
                p=binary/name;p.write_text(text);p.chmod(0o755)
            for auth,expected in [('1',0),('0',1)]:
                result=subprocess.run(['sh',str(test),'3','1','package.zip'],env=dict(os.environ,PATH=str(binary)+os.pathsep+os.environ['PATH'],AUTH_VALUE=auth),capture_output=True,text=True)
                self.assertEqual(result.returncode,expected,result.stderr)
                self.assertEqual('READ_ONLY_CHECK_PASS test-session' in result.stdout,auth=='1')
                self.assertEqual('READ_ONLY_CHECK_PASS test-session' in result.stderr,auth=='1')
                if auth=='0':
                    self.assertIn('ERROR: recovery authentication required',result.stderr)

if __name__=='__main__':unittest.main()
