from io import BytesIO
from pathlib import Path
import hashlib
import json
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'build'))
from recovery_trust import inspect_archive, verify
from signing_keys import create_identity


class RecoveryTrustTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory()
        root=Path(cls.tmp.name)
        first=create_identity(root/'first',('releasekey',),2048)
        create_identity(root/'second',('releasekey',),2048)
        cls.first=(root/'first/releasekey.x509.pem').read_bytes()
        cls.second=(root/'second/releasekey.x509.pem').read_bytes()
        cls.first_fingerprint=first['releasekey']

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def archive(self,certs):
        output=BytesIO()
        with zipfile.ZipFile(output,'w') as archive:
            for i,data in enumerate(certs):
                archive.writestr('certificate-'+str(i)+'.pem',data)
        return output.getvalue()

    def test_expected_project_certificate_present(self):
        self.assertTrue(inspect_archive(self.archive([self.first]),self.first)['trust_pass'])

    def test_wrong_recovery_certificate_fails(self):
        self.assertFalse(inspect_archive(self.archive([self.second]),self.first)['trust_pass'])

    def test_forbidden_trust_fails_even_when_expected_present(self):
        result=inspect_archive(self.archive([self.first,self.second]),self.first,{self.first_fingerprint})
        self.assertFalse(result['trust_pass'])
        self.assertTrue(result['expected_certificate_present'])

    def test_empty_trust_is_not_accepted(self):
        self.assertFalse(inspect_archive(self.archive([]),self.first)['trust_pass'])

    def test_unrelated_certificate_is_rejected_even_with_project_key(self):
        result=inspect_archive(self.archive([self.first,self.second]),self.first)
        self.assertFalse(result['trust_pass'])
        self.assertTrue(result['expected_certificate_present'])
        self.assertEqual(len(result['unexpected_certificates_present']),1)

    def test_lineage_filename_cannot_disguise_an_unrelated_key(self):
        output=BytesIO()
        with zipfile.ZipFile(output,'w') as archive:
            archive.writestr('releasekey.x509.pem',self.first)
            archive.writestr('lineage.x509.pem',self.second)
        self.assertFalse(inspect_archive(output.getvalue(),self.first)['trust_pass'])

    def test_exported_recovery_binding_and_tamper_rejection(self):
        with tempfile.TemporaryDirectory() as scratch:
            root=Path(scratch)
            artifacts=[]
            for name in ('recovery.img','lineage_ferrari-ota.zip','lineage_ferrari-target_files.zip'):
                path=root/name;path.write_bytes(name.encode())
                artifacts.append(dict(path='out/'+name,collected=str(path),bytes=path.stat().st_size,
                                      sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
            record=root/'result.json'
            record.write_text(json.dumps(dict(state='success',artifacts=artifacts)))
            exported=root/'packaged-recovery.img';exported.write_bytes(b'packaged recovery')
            digest=hashlib.sha256(exported.read_bytes()).hexdigest()
            binding={'pass':True,'run_id':root.name,'run_record_sha256':hashlib.sha256(record.read_bytes()).hexdigest(),
                     'ota_sha256':artifacts[1]['sha256'],'target_files_sha256':artifacts[2]['sha256'],
                     'exported_recovery':dict(path=str(exported),sha256=digest,bytes=exported.stat().st_size,source_member='IMAGES/recovery.img'),
                     'partitions':[dict(partition='recovery',payload_sha256=digest,bytes=exported.stat().st_size,**{'pass':True})]}
            report=root/'binding.json';report.write_text(json.dumps(binding))
            cert=root/'expected.pem';cert.write_bytes(self.first)
            archive=self.archive([self.first])
            image=SimpleNamespace(sha256=digest,ramdisk=SimpleNamespace(note=None,unpacked=b'cpio'),
                                  kernel=SimpleNamespace(size=0),
                                  ramdisk_entries=lambda:[SimpleNamespace(name='system/etc/security/otacerts.zip',is_file=True,data=archive)])
            with patch('recovery_trust.bootimage.load',return_value=image) as load:
                result=verify(record,cert,report)
                self.assertTrue(result['trust_pass'])
                load.assert_called_once_with(str(exported),read_ramdisk=True)
                exported.write_bytes(b'x'*exported.stat().st_size)
                with self.assertRaisesRegex(ValueError,'differs from bound payload'):
                    verify(record,cert,report)
                binding['run_record_sha256']='0'*64;report.write_text(json.dumps(binding))
                with self.assertRaisesRegex(ValueError,'same-run'):
                    verify(record,cert,report)
