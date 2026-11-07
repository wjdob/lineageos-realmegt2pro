"""Bind the reviewed WFD APK selection to its actual init route and ARM64 executable."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import zipfile

from package_coverage import bind_run_inputs
from payload_image_binding import collected,sha


def check_archive(package,contract):
    issues=[];measured={}
    with zipfile.ZipFile(package) as archive:
        names=archive.namelist()
        if len(names)!=len(set(names)):raise ValueError('duplicate target-files member')
        for label in ('init','executable','APK','seccomp'):
            member=contract[label+'_member']
            if member not in names:
                issues.append('required '+label+' member absent: '+member);continue
            data=archive.read(member)
            measured[label]=dict(member=member,bytes=len(data),sha256=hashlib.sha256(data).hexdigest())
            if not data:issues.append('empty '+label+' member')
            if label in ('init','executable') and measured[label]['sha256']!=contract[label+'_sha256']:
                issues.append('reviewed '+label+' identity changed')
            if label=='executable':
                if len(data)<20 or data[:6]!=b'\x7fELF\x02\x01' or int.from_bytes(data[18:20],'little')!=183:
                    issues.append('selected WFD executable is not little-endian AArch64 ELF64')
            if label=='APK':
                with zipfile.ZipFile(io.BytesIO(data)) as app:
                    dex_names=[name for name in app.namelist() if re.fullmatch(r'classes[0-9]*\.dex',name)]
                    if dex_names!=[contract['DEX_member']]:
                        issues.append('exact reviewed DEX member required')
                    else:
                        digest=hashlib.sha256(app.read(contract['DEX_member'])).hexdigest()
                        measured['DEX_sha256']=digest
                        if digest!=contract['DEX_sha256']:issues.append('WFD selection bytecode changed; re-review board/property selection')
            if label=='init':
                text=data.decode()
                for service in ('wfdservice','wfdservice64'):
                    expected='service '+service+' /system_ext/bin/wfdservice'
                    if len(re.findall('^'+re.escape(expected)+r'\s*$',text,re.M))!=1:
                        issues.append('service executable route missing or ambiguous: '+service)
                    for state,action in (('enable','start'),('disable','stop')):
                        pattern=r'^on property:vendor\.'+service+'='+state+r'\s*\n\s+'+action+' '+service+r'\s*$'
                        if len(re.findall(pattern,text,re.M))!=1:issues.append('property action missing or ambiguous: '+service+'='+state)
                if '/system_ext/bin/wfdservice64' in text:
                    issues.append('init still references the uninstalled executable name')
        boards=[]
        for name in ('SYSTEM/build.prop','VENDOR/build.prop','PRODUCT/etc/build.prop','SYSTEM_EXT/etc/build.prop'):
            if name in names:boards+=re.findall(r'^ro\.board\.platform=(.*)$',archive.read(name).decode(),re.M)
        if not boards or set(boards)!={contract['board_platform']}:
            issues.append('board selection differs from reviewed WFD bytecode route')
        measured['board_platform']=boards
    return dict(vendor_wfd_wiring_pass=not issues,issues=issues,measured=measured,
                limits='Reviewed APK DEX, init identity/property route, ARM64 executable identity and seccomp presence. Signing is checked separately; no WFD session, SELinux, codec, display or ROM boot pass implied.')


def verify(run_record,candidate_inputs,contract_path):
    run_id=bind_run_inputs(run_record,candidate_inputs)
    record=json.loads(run_record.read_text());inputs=json.loads(candidate_inputs.read_text());contract=json.loads(contract_path.read_text())
    if record.get('state')!='success':raise ValueError('successful collector required')
    recipe=inputs.get('recipe_snapshot',{})
    if inputs.get('target')!='otapackage' or recipe.get('manifest_sha256')!=inputs.get('manifest_sha256'):
        raise ValueError('candidate recipe/input identity mismatch')
    source=[row for row in recipe.get('files',[]) if row['path']==contract['recipe_source']]
    if len(source)!=1 or source[0]['canonical_sha256']!=contract['init_sha256']:
        raise ValueError('WFD init contract does not bind to the same-run source recipe')
    package,entry=collected(record,'/lineage_ferrari-target_files.zip')
    result=check_archive(package,contract)
    result.update(run_id=run_id,target_files_sha256=entry['sha256'],candidate_inputs_sha256=sha(candidate_inputs),
                  run_record_sha256=sha(run_record),contract_sha256=sha(contract_path),tool_sha256=sha(Path(__file__)))
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-record',type=Path,required=True)
    parser.add_argument('--candidate-inputs',type=Path,required=True)
    parser.add_argument('--contract',type=Path,required=True)
    parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args();result=verify(args.run_record,args.candidate_inputs,args.contract)
    args.report.parent.mkdir(parents=True,exist_ok=True);args.report.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(vendor_wfd_wiring_pass=result['vendor_wfd_wiring_pass'],issues=result['issues'])))
    return 0 if result['vendor_wfd_wiring_pass'] else 1


if __name__=='__main__':raise SystemExit(main())
