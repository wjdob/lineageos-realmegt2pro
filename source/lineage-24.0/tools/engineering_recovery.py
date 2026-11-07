"""Prepare a separate authenticated-ADB recovery image. No device operations."""
from pathlib import Path
from datetime import datetime,timezone
import argparse,ast,base64,gzip,hashlib,json,re,struct,subprocess,tempfile,sys

PROPERTIES={'ro.debuggable':'1','ro.adb.secure':'1',
            'ro.adb.secure.recovery':'1','ro.lineage.recovery.engineering':'1'}
AVB_KEY_SHA1='2597c218aae470a130f61162feaae70afd97f011'

def canonical_keys(data):
    keys=[]
    for line in data.decode('ascii').splitlines():
        if not line.strip():continue
        token=line.split()[0]
        try:raw=base64.b64decode(token,validate=True)
        except ValueError as error:raise ValueError('invalid Android public-key encoding') from error
        if len(raw)!=524:raise ValueError('Android RSA2048 public key required')
        words,n0inv=struct.unpack_from('<II',raw)
        modulus=int.from_bytes(raw[8:264],'little');rr=int.from_bytes(raw[264:520],'little')
        exponent=struct.unpack_from('<I',raw,520)[0]
        if (words!=64 or modulus.bit_length()!=2048 or not modulus&1 or exponent not in (3,65537)
                or n0inv!=(-pow(modulus&0xffffffff,-1,1<<32))&0xffffffff
                or rr!=pow(2,4096,modulus)):
            raise ValueError('invalid Android public-key structure')
        if token in keys:raise ValueError('duplicate Android public key')
        keys.append(token)
    if not 1<=len(keys)<=16:raise ValueError('one to16 operator public keys required')
    return ''.join(key+' engineering-host-'+str(i+1)+'\n' for i,key in enumerate(keys)).encode()

def parse_cpio(data):
    entries={};position=0;normalized=set()
    while position+110<=len(data):
        start=position;header=data[position:position+110]
        if header[:6]!=b'070701':raise ValueError('newc CPIO required')
        try:values=[int(header[6+i*8:14+i*8],16) for i in range(13)]
        except ValueError as error:raise ValueError('invalid CPIO header') from error
        size,namesize=values[6],values[11];position+=110
        if not namesize or position+namesize>len(data) or data[position+namesize-1]!=0:raise ValueError('invalid CPIO name')
        name=data[position:position+namesize-1].decode();position=(position+namesize+3)&~3;end=position+size
        if end>len(data):raise ValueError('truncated CPIO payload')
        payload=data[position:end];position=(end+3)&~3
        if name=='TRAILER!!!':
            if size or any(data[position:]):raise ValueError('invalid CPIO trailer')
            return entries,data[start:position]
        norm=name
        while norm.startswith('./'):norm=norm[2:]
        if norm.startswith('/') or '\0' in norm or '..' in norm.split('/') or norm in normalized:raise ValueError('unsafe or duplicate CPIO path')
        normalized.add(norm);entries[name]={'raw':data[start:position],'data':payload,'values':values,'normalized':norm}
    raise ValueError('missing CPIO trailer')

def encode_entry(name,data,values):
    values=list(values);encoded=name.encode()+b'\0';values[6]=len(data);values[11]=len(encoded)
    if any(not 0<=value<=0xffffffff for value in values):raise ValueError('CPIO field exceeds32 bits')
    block=b'070701'+b''.join(f'{v:08x}'.encode() for v in values)+encoded
    block+=bytes(-len(block)%4);block+=data
    return block+bytes(-len(block)%4)

def update_properties(data):
    lines=data.decode('utf-8').splitlines(keepends=True)
    kept=[line for line in lines if line.split('=',1)[0] not in PROPERTIES]
    result=''.join(kept)
    if result and not result.endswith('\n'):result+='\n'
    return (result+''.join(k+'='+v+'\n' for k,v in PROPERTIES.items())).encode()

def patch_ramdisk(raw,key_data):
    keys=canonical_keys(key_data);entries,tail=parse_cpio(raw)
    properties=[name for name,row in entries.items() if row['normalized'] in ('prop.default','system/etc/prop.default') and row['values'][1]&0o170000==0o100000]
    if len(properties)!=1:raise ValueError('one regular recovery default-property file required')
    property_name=properties[0]
    key_names=[name for name,row in entries.items() if row['normalized']=='adb_keys']
    if len(key_names)>1:raise ValueError('ambiguous root key file')
    allowed_types=(0o100000,0o120000)
    changed=[];parts=[]
    for name,row in entries.items():
        if name==property_name:
            parts.append(encode_entry(name,update_properties(row['data']),row['values']));changed.append(name)
        elif name in key_names:
            if row['values'][1]&0o170000 not in allowed_types:raise ValueError('unexpected root-key file type')
            values=list(row['values']);values[1]=0o100600;values[2]=values[3]=0;values[4]=1
            parts.append(encode_entry(name,keys,values));changed.append(name)
        else:parts.append(row['raw'])
    if not key_names:
        values=[max(row['values'][0] for row in entries.values())+1,0o100600,0,0,1,0,0,0,0,0,0,0,0]
        parts.append(encode_entry('adb_keys',keys,values));changed.append('adb_keys')
    result=b''.join(parts)+tail;result+=bytes(-len(result)%512)
    after,_=parse_cpio(result)
    expected_names=set(entries)|({'adb_keys'} if not key_names else set())
    assert set(after)==expected_names
    assert all(after[name]['raw']==row['raw'] for name,row in entries.items() if name not in changed)
    return result,{'changed_entries':changed,'preserved_entries':len(entries)-len([n for n in changed if n in entries]),
                  'key_count':len(keys.splitlines()),'keys_sha256':hashlib.sha256(keys).hexdigest()}

def avb_fields(text):
    def field(label,indent=''):
        rows=re.findall('^'+re.escape(indent+label)+r':\s*(.*?)\s*$',text,re.M)
        if len(rows)!=1:raise ValueError('expected one AVB field: '+label)
        return rows[0]
    if (text.count('    Hash descriptor:')!=1 or '    Hashtree descriptor:' in text or '    Chain Partition descriptor:' in text
            or field('Partition Name','      ')!='recovery' or field('Algorithm')!='SHA256_RSA4096'
            or field('Hash Algorithm','      ')!='sha256' or field('Public key (sha1)')!=AVB_KEY_SHA1
            or field('Flags')!='0' or field('Flags','      ')!='0' or field('Rollback Index Location')!='0'):
        raise ValueError('unqualified recovery AVB policy')
    props=[(name,ast.literal_eval(value)) for name,value in re.findall(r'^    Prop: (\S+) -> (.*)$',text,re.M)]
    names={name for name,value in props}
    supported=({'com.android.build.recovery.fingerprint'},
               {'com.android.build.recovery.'+s for s in ('os_version','fingerprint','security_patch')})
    if len(names)!=len(props) or names not in supported:
        raise ValueError('unexpected recovery AVB properties')
    return {'algorithm':field('Algorithm'),'partition_size':int(field('Image size').split()[0]),
            'rollback_index':field('Rollback Index'),'salt':field('Salt','      '),'properties':props}

def policy_lines(text):
    return [line for line in text.splitlines() if not any(label in line for label in ('Original image size:','VBMeta offset:','Image Size:','Digest:'))]

def build(parent,expected_sha,public_key,android,out):
    if not re.fullmatch('[0-9a-f]{64}',expected_sha):raise ValueError('full parent image hash required')
    if out.exists():raise ValueError('new output directory required')
    with parent.open('rb') as stream:actual=hashlib.file_digest(stream,'sha256').hexdigest()
    if actual!=expected_sha:raise ValueError('recovery parent hash mismatch')
    with parent.open('rb') as stream:header=stream.read(4096)
    if header[:8]!=b'ANDROID!' or struct.unpack_from('<I',header,40)[0] not in (3,4):raise ValueError('reviewed header3/4 recovery required')
    if struct.unpack_from('<I',header,40)[0]==4 and struct.unpack_from('<I',header,1580)[0]:raise ValueError('separate GKI signature review required')
    keys=public_key.read_bytes();canonical_keys(keys)
    def run(args):return subprocess.run(list(map(str,args)),capture_output=True,check=True,timeout=180).stdout
    avb=android/'external/avb/avbtool.py';unpack=android/'system/tools/mkbootimg/unpack_bootimg.py';mkboot=android/'system/tools/mkbootimg/mkbootimg.py'
    info=run([sys.executable,avb,'info_image','--image',parent]).decode();fields=avb_fields(info)
    if fields['partition_size']!=parent.stat().st_size:raise ValueError('parent capacity differs from AVB image size')
    out.mkdir(parents=True,exist_ok=False)
    with tempfile.TemporaryDirectory(prefix='engineering-recovery-',dir=out) as folder:
        work=Path(folder);unpacked=work/'unpacked'
        args=run([sys.executable,unpack,'--boot_img',parent,'--out',unpacked,'--format','mkbootimg','-0']).split(b'\0')
        assert args[-1]==b'';args=[s.decode() for s in args[:-1]];assert args.count('--ramdisk')==1
        compressed=(unpacked/'ramdisk').read_bytes()
        if compressed.startswith(b'\x1f\x8b'):raw=gzip.decompress(compressed);kind='gzip'
        else:raw=run(['lz4','-d','-c',unpacked/'ramdisk']);kind='lz4-legacy' if compressed[:4]==b'\x02\x21\x4c\x18' else 'lz4-frame'
        changed,delta=patch_ramdisk(raw,keys);cpio=work/'ramdisk.cpio';cpio.write_bytes(changed)
        encoded=gzip.compress(changed,compresslevel=9,mtime=0) if kind=='gzip' else run(['lz4',*(['-l'] if kind=='lz4-legacy' else []),'-9','-c',cpio])
        rebuilt=work/'ramdisk';rebuilt.write_bytes(encoded);args[args.index('--ramdisk')+1]=str(rebuilt)
        # avbtool resolves a hash descriptor through <partition>.img beside the
        # input. Keep that exact name in this clearly separate private folder.
        destination=out/'recovery.img'
        run([sys.executable,mkboot,*args,'--output',destination])
        key=android/'external/avb/test/data/testkey_rsa4096.pem'
        run([sys.executable,avb,'verify_image','--image',parent,'--key',key])
        command=[sys.executable,avb,'add_hash_footer','--image',destination,'--partition_name','recovery','--partition_size',fields['partition_size'],
                 '--algorithm',fields['algorithm'],'--key',key,'--rollback_index',fields['rollback_index'],'--salt',fields['salt']]
        for name,value in fields['properties']:command+=['--prop',name+':'+value]
        run(command);verification=run([sys.executable,avb,'verify_image','--image',destination,'--key',key]).decode()
        after_info=run([sys.executable,avb,'info_image','--image',destination]).decode()
        if policy_lines(info)!=policy_lines(after_info):raise ValueError('recovery AVB policy changed')
        # Independent unpack verifies actual packed payloads, not just the CPIO prototype.
        final=work/'final';run([sys.executable,unpack,'--boot_img',destination,'--out',final])
        assert (final/'kernel').read_bytes()==(unpacked/'kernel').read_bytes()
        with destination.open('rb') as stream:after_header=stream.read(4096)
        assert header[:12]+bytes(4)+header[16:]==after_header[:12]+bytes(4)+after_header[16:]
        final_raw=gzip.decompress((final/'ramdisk').read_bytes()) if kind=='gzip' else run(['lz4','-d','-c',final/'ramdisk'])
        assert final_raw==changed
        for name in ('dtb','recovery_dtbo','second'):
            if (unpacked/name).exists():assert (final/name).read_bytes()==(unpacked/name).read_bytes()
        report={'created_utc':datetime.now(timezone.utc).isoformat(),'status':'offline engineering candidate; recovery boot unverified',
                'parent_sha256':actual,'engineering_sha256':hashlib.sha256(destination.read_bytes()).hexdigest(),
                'image_bytes':destination.stat().st_size,'kernel_sha256':hashlib.sha256((unpacked/'kernel').read_bytes()).hexdigest(),
                'compression':kind,'ramdisk':delta,'properties':PROPERTIES,'avb_policy_preserved':True,'avb_verification':verification,
                'tools_sha256':{str(p.relative_to(android)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (avb,unpack,mkboot)},
                'limits':'Separate operator-keyed recovery only. No production image, init executable, OTA trust certificate, partition, BCB or device change. Authenticated ADB, remote controls and recovery boot require a reviewed live test.'}
        (out/'source-avb.txt').write_text(info);(out/'engineering-avb.txt').write_text(after_info)
        (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    return report

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--parent',type=Path,required=True);p.add_argument('--expected-parent-sha256',required=True)
    p.add_argument('--adb-public-key',type=Path,required=True);p.add_argument('--android-tree',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();r=build(a.parent,a.expected_parent_sha256,a.adb_public_key,a.android_tree,a.out)
    print(json.dumps({k:r[k] for k in ('status','parent_sha256','engineering_sha256','image_bytes')}))

if __name__=='__main__':
    main()
