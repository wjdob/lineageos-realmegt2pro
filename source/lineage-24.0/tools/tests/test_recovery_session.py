from pathlib import Path
import sys,unittest
from unittest.mock import patch
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import recovery_session as session

class RecoverySessionTests(unittest.TestCase):
    def test_rejects_wrong_extra_unauthorized_and_offline_devices(self):
        for text in ('List of devices attached\nother recovery\n','one recovery\ntwo recovery\n',
                     'one unauthorized\n','one offline\n','one device\n',''):
            with self.subTest(text=text),self.assertRaises(ValueError):session.validate_devices(text,'one')
        session.validate_devices('List of devices attached\none\trecovery\n','one')
        session.validate_devices('one\tsideload\n','one','sideload')

    def test_bad_hash_unknown_operation_and_missing_mapper_stop_before_adb(self):
        with patch.object(session.subprocess,'run') as run,patch.object(session,'digest',return_value='a'*64):
            base=dict(adb=Path('adb'),serial='one',slot='a',recovery_sha='b'*64,helper=Path('helper'),helper_sha='a'*64,operation='status')
            for change in ({'operation':'erase'},{'slot':'c'},{'helper_sha':'0'*64},{'serial':'one;other'},
                           {'recovery_sha':'b'*63},{'operation':'mount-system-ro'},
                           {'operation':'status','package':Path('package'),'package_sha':'a'*64}):
                with self.subTest(change=change),self.assertRaises(ValueError):session.perform(**dict(base,**change))
            run.assert_not_called()

    def test_sideload_disconnect_race_requires_exact_transport_and_never_ignores_refusal(self):
        properties={'ro.bootmode':'recovery','ro.product.model':'RMX3301','ro.build.version.sdk':'37',
            'ro.lineage.recovery.engineering':'1','ro.adb.secure':'1','ro.adb.secure.recovery':'1',
            'ro.boot.slot_suffix':'_a','ro.boot.vbmeta.device_state':'unlocked'}
        def exercise(refused):
            device_queries=0
            def reply(args,**kwargs):
                nonlocal device_queries
                text='';error='';code=0
                if args[1:]==['devices']:
                    device_queries+=1;text='one\t'+('recovery' if device_queries==1 else 'sideload')+'\n'
                elif 'getprop' in args:text=properties[args[-1]]
                elif args[-2:]==['id','-u']:text='0'
                elif 'sha256sum' in args:
                    path=args[-1];text=('b'*64 if 'by-name' in path else 'a'*64)+'  '+path
                elif args[-1]=='sideload-addon':
                    code=1;error='error: closed'
                    if refused:text='recovery control refused: active update'
                return SimpleNamespace(returncode=code,stdout=text,stderr=error)
            with patch.object(session.subprocess,'run',side_effect=reply) as run,patch.object(session,'digest',return_value='a'*64):
                result=session.perform(Path('adb'),'one','a','b'*64,Path('helper'),'a'*64,'sideload-addon')
                self.assertFalse(any('sideload' in r['arguments'] for r in result['commands']))
                self.assertEqual(device_queries,2)
        exercise(False)
        with self.assertRaises(RuntimeError):exercise(True)

if __name__=='__main__':unittest.main()
