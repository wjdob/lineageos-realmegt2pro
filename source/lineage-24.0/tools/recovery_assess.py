"""Offline recovery evidence; no device operations or boot-compatibility verdict."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import subprocess
import shutil
import sys
import tempfile
import zipfile
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from bootimg import load, sha256_file


def digest(data):return hashlib.sha256(data).hexdigest()


def inspect(path,certificates):
    image=load(str(path))
    entries=image.ramdisk_entries()
    if image.ramdisk.note or not entries:raise ValueError('ramdisk unavailable: '+str(image.ramdisk.note))
    files={entry.name:entry for entry in entries}
    if len(files)!=len(entries):raise ValueError('duplicate ramdisk path')
    result=image.as_dict()
    result['ramdisk_inventory']={name:dict(mode=oct(entry.mode),bytes=entry.size,sha256=digest(entry.data)) for name,entry in sorted(files.items())}
    result['services']={name:entry.data.decode(errors='replace') for name,entry in files.items() if name.endswith('.rc') and entry.is_file}
    result['required_files']={name:(name in files and files[name].is_file and files[name].size>0) for name in ('system/bin/recovery','system/bin/adbd','system/bin/fastbootd','system/etc/recovery.fstab','prop.default')}
    result['property_files']={name:files[name].data.decode(errors='replace') for name in ('prop.default','system/build.prop') if name in files and files[name].is_file}
    bundles=[entry for name,entry in files.items() if name.endswith('/otacerts.zip') and entry.is_file]
    fingerprints={}
    for bundle in bundles:
        with zipfile.ZipFile(io.BytesIO(bundle.data)) as archive:
            for name in archive.namelist():
                if name.endswith('/'):continue
                data=archive.read(name)
                cert=x509.load_pem_x509_certificate(data) if b'-----BEGIN CERTIFICATE-----' in data else x509.load_der_x509_certificate(data)
                fingerprints[bundle.name+':'+name]=cert.fingerprint(hashes.SHA256()).hex()
    result['ota_certificate_fingerprints']=fingerprints
    result['expected_certificates']={str(cert):x509.load_pem_x509_certificate(cert.read_bytes()).fingerprint(hashes.SHA256()).hex() in fingerprints.values() for cert in certificates}
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('image',type=Path)
    p.add_argument('--compare',type=Path)
    p.add_argument('--capacity',type=int,required=True)
    p.add_argument('--avbtool',type=Path,required=True)
    p.add_argument('--certificate',type=Path,action='append',default=[])
    p.add_argument('--report',type=Path,required=True)
    a=p.parse_args()
    if a.capacity<=0:raise ValueError('capacity must be positive')
    result=inspect(a.image,a.certificate)
    result['capacity_check']=dict(partition_bytes=a.capacity,fits=0<a.image.stat().st_size<=a.capacity)
    result['avbtool_sha256']=digest(a.avbtool.read_bytes())
    result['avb']={}
    scratch=Path(__file__).resolve().parents[1]/'tmp/recovery-assess'
    scratch.mkdir(parents=True,exist_ok=True)
    # avbtool resolves the recovery hash descriptor as a sibling recovery.img.
    # A unique scratch copy avoids verifying an unrelated same-named sibling.
    with tempfile.TemporaryDirectory(dir=scratch) as temporary:
        verification_image=Path(temporary)/'recovery.img'
        shutil.copyfile(a.image,verification_image)
        result['verification_copy_sha256']=sha256_file(str(verification_image))
        if result['verification_copy_sha256']!=result['sha256']:raise ValueError('image changed during verification copy')
        for command in ('info_image','verify_image'):
            proc=subprocess.run([sys.executable,str(a.avbtool),command,'--image',str(verification_image)],text=True,capture_output=True)
            result['avb'][command]=dict(exit_code=proc.returncode,stdout=proc.stdout,stderr=proc.stderr)
    if a.compare:
        previous=inspect(a.compare,[])
        old=previous['ramdisk_inventory'];new=result['ramdisk_inventory']
        result['comparison']=dict(path=str(a.compare),sha256=previous['sha256'],
            added=sorted(new.keys()-old.keys()),removed=sorted(old.keys()-new.keys()),
            changed=sorted(name for name in old.keys()&new.keys() if old[name]!=new[name]))
    result['limits']='Layout, captured capacity, packaged files/certificates and AVB self-integrity only. Embedded AVB key verification does not establish bootloader trust or firmware compatibility. No boot, service execution, decryption or restore claim.'
    a.report.parent.mkdir(parents=True,exist_ok=True)
    a.report.write_text(json.dumps(result,indent=2)+'\n')
    passed=result['capacity_check']['fits'] and all(result['required_files'].values()) and all(result['expected_certificates'].values()) and all(row['exit_code']==0 for row in result['avb'].values())
    print(json.dumps(dict(offline_checks_pass=passed,sha256=result['sha256'],required_files=result['required_files'],expected_certificates=result['expected_certificates'],avb_exit_codes={k:v['exit_code'] for k,v in result['avb'].items()}),indent=2))
    return 0 if passed else 1


if __name__=='__main__':raise SystemExit(main())
