import hashlib
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from firmware_policy import OS_PARTITIONS
from payload_image_binding import verify


def varint(n):
    result=bytearray()
    while n>=128:
        result.append((n&127)|128);n>>=7
    result.append(n)
    return bytes(result)


def field(n,data):
    return varint(n*8+2)+varint(len(data))+data


class PayloadBindingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.images={name:('fixture-'+name).encode() for name in OS_PARTITIONS}
        manifest=b''
        for name,data in sorted(self.images.items()):
            info=varint(8)+varint(len(data))+field(2,hashlib.sha256(data).digest())
            manifest+=field(13,field(1,name.encode())+field(7,info))
        self.ota=self.root/'lineage_ferrari-ota.zip'
        with zipfile.ZipFile(self.ota,'w') as archive:
            archive.writestr('payload.bin',b'CrAU'+struct.pack('>QQI',2,len(manifest),0)+manifest)
        self.target=self.root/'lineage_ferrari-target_files.zip'
        self.write_target()
        self.recovery=self.root/'recovery.img'
        self.recovery.write_bytes(self.images['recovery'])
        self.record=self.root/'result.json'
        self.write_record()

    def write_target(self):
        with zipfile.ZipFile(self.target,'w') as archive:
            for name,data in self.images.items():
                archive.writestr('IMAGES/'+name+'.img',data)

    def write_record(self,state='success'):
        artifacts=[{'path':'out/'+p.name,'collected':str(p),'bytes':p.stat().st_size,
                    'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
                   for p in (self.ota,self.target,self.recovery)]
        self.record.write_text(json.dumps({'state':state,'artifacts':artifacts}))

    def test_all_os_images_and_matching_recovery(self):
        result=verify(self.record)
        self.assertTrue(result['pass']);self.assertEqual(len(result['partitions']),13)

    def test_changed_collected_artifact_rejected(self):
        self.recovery.write_bytes(b'x'*len(self.images['recovery']))
        with self.assertRaisesRegex(ValueError,'artifact changed'):
            verify(self.record)

    def test_manifest_image_mismatch_even_with_valid_collection_hash(self):
        self.images['system']=b'x'*len(self.images['system'])
        self.write_target();self.write_record()
        result=verify(self.record)
        self.assertFalse(result['pass'])
        self.assertEqual([r['partition'] for r in result['partitions'] if not r['pass']],['system'])

    def test_recovery_collection_must_match_payload_not_just_its_own_hash(self):
        self.recovery.write_bytes(b'x'*len(self.images['recovery']));self.write_record()
        result=verify(self.record)
        self.assertFalse(result['pass'])
        recovery=next(r for r in result['partitions'] if r['partition']=='recovery')
        self.assertFalse(recovery['collected_recovery_matches'])

    def test_failed_run_cannot_promote_existing_outputs(self):
        self.write_record(state='failed')
        with self.assertRaisesRegex(ValueError,'successful collector'):
            verify(self.record)

    def test_explicit_export_binds_packaged_recovery_and_preserves_build_image(self):
        build_image=b'different-standalone-recovery'
        self.recovery.write_bytes(build_image);self.write_record()
        destination=self.root/'release/recovery.img'
        result=verify(self.record,destination)
        self.assertTrue(result['pass'])
        self.assertEqual(destination.read_bytes(),self.images['recovery'])
        self.assertEqual(self.recovery.read_bytes(),build_image)
        self.assertEqual(result['exported_recovery']['sha256'],hashlib.sha256(destination.read_bytes()).hexdigest())
        with self.assertRaises(FileExistsError):
            verify(self.record,destination)

    def test_export_cannot_bypass_recovery_manifest_mismatch(self):
        self.images['recovery']=b'x'*len(self.images['recovery'])
        self.write_target();self.write_record()
        destination=self.root/'release/recovery.img'
        with self.assertRaisesRegex(ValueError,'unbound'):
            verify(self.record,destination)
        self.assertFalse(destination.exists())
