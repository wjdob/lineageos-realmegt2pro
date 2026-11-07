"""Bind every same-run recipe ELF fixup to its exact installed target-files member."""
import argparse
import json
from pathlib import Path
import re
import shutil
import tempfile
import zipfile

from package_coverage import bind_run_inputs
from payload_image_binding import collected,sha
from vendor_xml_abi import inspect

REPO=Path(__file__).resolve().parents[1]


def package_member(path):
    match=re.fullmatch(r'vendor/(?:oneplus/sm8450-common|realme/ferrari)/proprietary/(vendor|odm|system_ext|product|system)/(.+)',path)
    if not match or '..' in Path(match.group(2)).parts or '\\' in path:
        raise ValueError('unreviewed fixup installation mapping: '+path)
    return match.group(1).upper()+'/'+match.group(2)


def check_archive(package,fixups,readelf,scratch):
    if not isinstance(fixups,list) or not fixups:
        raise ValueError('nonempty same-run binary fixup list required')
    rows=[];seen=set()
    with zipfile.ZipFile(package) as archive:
        names=archive.namelist()
        if len(names)!=len(set(names)):
            raise ValueError('duplicate target-files member')
        for index,fixup in enumerate(fixups):
            member=package_member(fixup['path'])
            if member in seen:raise ValueError('duplicate fixup target: '+member)
            seen.add(member)
            operation=fixup.get('operation','replace_needed')
            if operation not in ('replace_needed','add_needed'):
                raise ValueError('unsupported recipe fixup operation')
            row=dict(member=member,source_path=fixup['path'],expected_sha256=fixup['result_sha256'],operation=operation,issues=[])
            rows.append(row)
            if member not in names:
                row['issues'].append('exact installed fixup member absent');continue
            measured,_=inspect(archive.read(member),scratch/str(index),readelf)
            row.update(measured)
            if measured['sha256']!=fixup['result_sha256']:
                row['issues'].append('installed bytes differ from reviewed fixup result')
            if measured['needed'].count(fixup['new_needed'])!=1:
                row['issues'].append('required fixed DT_NEEDED entry absent or duplicated')
            if operation=='replace_needed' and fixup['old_needed'] in measured['needed']:
                row['issues'].append('old dependency still present')
    return dict(vendor_fixup_binding_pass=all(not row['issues'] for row in rows),fixups=rows,
                limits='Exact same-run recipe result bytes and dependency tags in installed package members. No provider ABI, namespace, service, policy or runtime acceptance implied.')


def verify(run_record,candidate_inputs,readelf):
    run_id=bind_run_inputs(run_record,candidate_inputs)
    record=json.loads(run_record.read_text())
    if record.get('state')!='success':raise ValueError('successful collector required')
    inputs=json.loads(candidate_inputs.read_text())
    recipe=inputs.get('recipe_snapshot',{})
    if inputs.get('target')!='otapackage' or recipe.get('manifest_sha256')!=inputs.get('manifest_sha256'):
        raise ValueError('candidate recipe/input identity mismatch')
    package,entry=collected(record,'/lineage_ferrari-target_files.zip')
    with tempfile.TemporaryDirectory(prefix='vendor-fixup-binding-',dir=REPO/'tmp') as directory:
        result=check_archive(package,recipe.get('binary_fixups'),readelf,Path(directory))
    result.update(run_id=run_id,run_record_sha256=sha(run_record),candidate_inputs_sha256=sha(candidate_inputs),
                  target_files_sha256=entry['sha256'],readelf_sha256=sha(readelf),
                  tool_sha256=sha(Path(__file__)),ELF_inspector_sha256=sha(REPO/'tools/vendor_xml_abi.py'),
                  symbol_parser_sha256=sha(REPO/'tools/elf_symbols.py'))
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-record',type=Path,required=True)
    parser.add_argument('--candidate-inputs',type=Path,required=True)
    parser.add_argument('--readelf',type=Path,default=Path(shutil.which('readelf') or '/usr/bin/readelf'))
    parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args()
    result=verify(args.run_record,args.candidate_inputs,args.readelf.resolve())
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(vendor_fixup_binding_pass=result['vendor_fixup_binding_pass'],fixups=len(result['fixups']))))
    return 0 if result['vendor_fixup_binding_pass'] else 1


if __name__=='__main__':raise SystemExit(main())
