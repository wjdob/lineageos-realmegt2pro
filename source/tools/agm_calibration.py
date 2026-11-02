"""Check RMX3301 AGM path selection in reconstructed C and evaluated Soong variables."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import zipfile

from package_coverage import archive_path,bind_run_inputs
from payload_image_binding import collected

REPO=Path(__file__).resolve().parents[1]


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_configuration(variables,contract):
    actual=variables.get('VendorVars',{}).get(contract['namespace'],{}).get(contract['variable'])
    if actual!=contract['path']:
        raise ValueError('evaluated AGM calibration path differs from reviewed device setting: '+repr(actual))
    return dict(namespace=contract['namespace'],variable=contract['variable'],value=actual)


def bind_sources(inputs,contract):
    recipe=inputs.get('recipe_snapshot',{})
    if inputs.get('target')!='otapackage' or recipe.get('manifest_sha256')!=inputs.get('manifest_sha256'):
        raise ValueError('candidate recipe/input identity mismatch')
    for path,expected in contract['source_sha256'].items():
        matches=[row for row in recipe.get('files',[]) if row['path']==path]
        if len(matches)!=1 or matches[0]['canonical_sha256']!=expected:
            raise ValueError('AGM source contract differs from same-run recipe: '+path)
    return contract['source_sha256']


def verify_package(run_record,candidate_inputs,contract_path,contract):
    run_id=bind_run_inputs(run_record,candidate_inputs)
    record=json.loads(run_record.read_text());inputs=json.loads(candidate_inputs.read_text())
    if record.get('state')!='success':raise ValueError('successful collector required')
    bind_sources(inputs,contract)
    config_report=run_record.parent/'agm-configuration.json'
    configuration=json.loads(config_report.read_text())
    if (configuration.get('agm_calibration_check_pass') is not True or
            configuration.get('value')!=contract['path'] or
            configuration.get('contract_sha256')!=sha(contract_path) or
            inputs.get('source_hashes',{}).get('configs/agm-calibration-23.2.json')!=sha(contract_path) or
            inputs.get('source_hashes',{}).get('tools/agm_calibration.py')!=configuration.get('tool_sha256')):
        raise ValueError('same-run evaluated AGM configuration/provenance mismatch')
    package,entry=collected(record,'/lineage_ferrari-target_files.zip')
    metadata,_=collected(record,'/module-info.json')
    module=json.loads(metadata.read_text()).get(contract['module'],{})
    paths={archive_path(path,'out/target/product/ferrari') for path in module.get('installed',[]) if path.startswith('out/target/product/ferrari/')}
    if contract['module_source'] not in module.get('path',[]) or contract['library_member'] not in paths:
        raise ValueError('packaged AGM module does not resolve to the reviewed source/installation')
    with zipfile.ZipFile(package) as archive:
        if len(archive.namelist())!=len(set(archive.namelist())):raise ValueError('duplicate target-files member')
        calibration=archive.read(contract['calibration_member']);library=archive.read(contract['library_member'])
        if hashlib.sha256(calibration).hexdigest()!=contract['calibration_sha256']:
            raise ValueError('reviewed RMX3301 calibration identity changed')
        if len(library)<20 or library[:6]!=b'\x7fELF\x02\x01' or int.from_bytes(library[18:20],'little')!=183:
            raise ValueError('AGM library is not AArch64 ELF64')
    return dict(run_id=run_id,target_files_sha256=entry['sha256'],candidate_inputs_sha256=sha(candidate_inputs),
                configuration_report_sha256=sha(config_report),library_sha256=hashlib.sha256(library).hexdigest(),
                calibration_sha256=hashlib.sha256(calibration).hexdigest(),
                limits='Same-run reconstructed source contract, evaluated product configuration, module source/install identity and reviewed calibration bytes. Does not certify full native ABI, GSL/DSP negotiation, SELinux or live audio.')


def verify_source(tree,contract):
    sources={}
    for relative,expected in contract['source_sha256'].items():
        path=(tree/relative).resolve()
        if not path.is_relative_to(tree.resolve()) or sha(path)!=expected:
            raise ValueError('reconstructed AGM source identity differs: '+relative)
        sources[relative]=path.read_text()
    graph=sources[contract['graph_source']]
    match=re.search(r'(static int select_acdb_path\([^\n]*\n.*?\n}\n)',graph,re.S)
    if not match:raise ValueError('reviewed actual C selector is absent')
    extension=re.search(r'^#define ARRAX_FILE_PATH_EXTN ("[^"]+")$',graph,re.M).group(1)
    soc=re.search(r'^#define ARRAX_SOC_ID (\d+)$',graph,re.M).group(1)
    if not re.fullmatch(r'/[A-Za-z0-9_/-]+',contract['path']):raise ValueError('invalid configured path')
    compiler=Path(shutil.which('cc') or '/usr/bin/cc').resolve()
    prefix='#include <stdio.h>\n#include <stddef.h>\n#include <string.h>\n#include <errno.h>\n'
    prefix+='#define ACDB_PATH '+json.dumps(contract['legacy_root'])+'\n#define ARRAX_FILE_PATH_EXTN '+extension+'\n#define ARRAX_SOC_ID '+soc+'\n'
    main='''
int main(void) {
    char path[80];
    if (select_acdb_path(path, sizeof(path), CONFIGURED_PATH, "waipio_mtp", ARRAX_SOC_ID) || strcmp(path, CONFIGURED_PATH)) return 1;
    if (select_acdb_path(path, sizeof(path), "", "waipio_mtp", -1) || strcmp(path, ACDB_PATH "waipio_mtp")) return 2;
    if (select_acdb_path(path, sizeof(path), "", "waipio_mtp", ARRAX_SOC_ID) || strcmp(path, ACDB_PATH "waipio_mtp" ARRAX_FILE_PATH_EXTN)) return 3;
    if (select_acdb_path(path, 4, CONFIGURED_PATH, "waipio_mtp", -1) != -ENAMETOOLONG) return 4;
    return 0;
}
'''
    with tempfile.TemporaryDirectory(prefix='agm-selector-',dir=REPO/'tmp') as directory:
        source=Path(directory)/'selector.c';binary=Path(directory)/'selector'
        source.write_text(prefix+'#define CONFIGURED_PATH '+json.dumps(contract['path'])+'\n'+match.group(1)+main)
        subprocess.run([str(compiler),'-std=c11','-Wall','-Wextra','-Werror',str(source),'-o',str(binary)],check=True,capture_output=True)
        subprocess.run([str(binary)],check=True,capture_output=True)
    return dict(source_sha256=contract['source_sha256'],actual_C_selector_cases=4,compiler=str(compiler),compiler_sha256=sha(compiler),
                limits='Actual reconstructed selector compiled/executed on host. Does not compile all AGM/GSL, evaluate Soong or prove live audio.')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--source-tree',type=Path)
    mode.add_argument('--soong-variables',type=Path)
    mode.add_argument('--run-record',type=Path)
    parser.add_argument('--candidate-inputs',type=Path)
    parser.add_argument('--contract',type=Path,required=True)
    parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args();contract=json.loads(args.contract.read_text())
    if args.source_tree:
        result=verify_source(args.source_tree,contract)
    elif args.soong_variables:
        result=verify_configuration(json.loads(args.soong_variables.read_text()),contract)
        result.update(soong_variables_sha256=sha(args.soong_variables),limits='Actual evaluated Soong product setting. Does not establish source/object identity, calibration contents or live audio; source reconstruction and package checks remain required.')
    else:
        if args.candidate_inputs is None:parser.error('--run-record requires --candidate-inputs')
        result=verify_package(args.run_record,args.candidate_inputs,args.contract,contract)
    result.update(agm_calibration_check_pass=True,contract_sha256=sha(args.contract),tool_sha256=sha(Path(__file__)))
    args.report.parent.mkdir(parents=True,exist_ok=True);args.report.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result));return 0


if __name__=='__main__':raise SystemExit(main())
