"""Constrain the engineering derivative to authenticated keys and two CPIO entries."""
from pathlib import Path
import base64,struct,sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import engineering_recovery as recovery

def public_key():
    modulus=(1<<2048)-159
    raw=struct.pack('<II',64,(-pow(modulus&0xffffffff,-1,1<<32))&0xffffffff)
    raw+=modulus.to_bytes(256,'little')+pow(2,4096,modulus).to_bytes(256,'little')+struct.pack('<I',65537)
    return base64.b64encode(raw)+b' fixture@host\n'

def entry(name,data,mode=0o100644,inode=1):
    return recovery.encode_entry(name,data,[inode,mode,0,0,1,0,0,0,0,0,0,0,0])

def archive(*entries):
    return b''.join(entries)+entry('TRAILER!!!',b'')

class EngineeringRecoveryTests(unittest.TestCase):
    def test_valid_key_has_nonpersonal_canonical_comment(self):
        result=recovery.canonical_keys(public_key())
        self.assertIn(b'engineering-host-1',result)
        self.assertNotIn(b'fixture@host',result)

    def test_bad_key_size_and_encoding_are_refused(self):
        for data in [b'',b'not-base64!',base64.b64encode(bytes(100))]:
            with self.subTest(data=data),self.assertRaises(ValueError):recovery.canonical_keys(data)

    def test_corrupt_montgomery_key_is_refused(self):
        data=bytearray(base64.b64decode(public_key().split()[0]));data[264]^=1
        with self.assertRaises(ValueError):recovery.canonical_keys(base64.b64encode(data))

    def test_duplicate_keys_are_refused(self):
        with self.assertRaises(ValueError):recovery.canonical_keys(public_key()*2)

    def test_replaces_unavailable_product_key_symlink_and_preserves_executables(self):
        original=archive(entry('prop.default',b'ro.debuggable=0\nro.adb.secure=1\nother=retained\n'),
            entry('adb_keys',b'/product/etc/security/adb_keys',mode=0o120644),
            entry('system/bin/recovery',b'unchanged-recovery',mode=0o100755),
            entry('system/bin/adbd',b'unchanged-adbd',mode=0o100755),
            entry('system/etc/security/otacerts.zip',b'unchanged-trust'))
        changed,report=recovery.patch_ramdisk(original,public_key())
        before,_=recovery.parse_cpio(original);after,_=recovery.parse_cpio(changed)
        self.assertEqual(set(report['changed_entries']),{'prop.default','adb_keys'})
        self.assertEqual(after['adb_keys']['values'][1],0o100600)
        self.assertEqual(after['adb_keys']['values'][2:4],[0,0])
        for name in ['system/bin/recovery','system/bin/adbd','system/etc/security/otacerts.zip']:
            self.assertEqual(before[name]['raw'],after[name]['raw'])
        properties=after['prop.default']['data']
        self.assertIn(b'ro.adb.secure=1\n',properties)
        self.assertIn(b'ro.adb.secure.recovery=1\n',properties)
        self.assertNotIn(b'ro.adb.secure=0',properties)
        self.assertIn(b'other=retained\n',properties)

    def test_missing_key_file_is_added(self):
        changed,_=recovery.patch_ramdisk(archive(entry('prop.default',b'x=1\n')),public_key())
        after,_=recovery.parse_cpio(changed)
        self.assertIn('adb_keys',after)

    def test_ambiguous_property_files_are_refused(self):
        original=archive(entry('prop.default',b'x=1\n'),entry('system/etc/prop.default',b'x=1\n'))
        with self.assertRaises(ValueError):recovery.patch_ramdisk(original,public_key())

    def test_key_directory_cannot_be_replaced(self):
        original=archive(entry('prop.default',b'x=1\n'),entry('adb_keys',b'',mode=0o40755))
        with self.assertRaises(ValueError):recovery.patch_ramdisk(original,public_key())

    def test_alias_paths_and_truncation_are_refused(self):
        for raw in [archive(entry('a',b'x'),entry('./a',b'y')),archive(entry('../a',b'x')),archive(entry('/a',b'x')),b'070701']:
            with self.assertRaises(ValueError):recovery.parse_cpio(raw)

    def test_key_inode_overflow_is_refused(self):
        original=archive(entry('prop.default',b'x=1\n',inode=0xffffffff))
        with self.assertRaises(ValueError):recovery.patch_ramdisk(original,public_key())

if __name__=='__main__':unittest.main()
