"""Check a reviewed legacy vendor XML ABI contract against collected target-files.

Symbol presence alone cannot establish C++ object layout. This gate pins the exact
reviewed provider/caller bytes as well as their dependency and symbol identities.
Changing either requires renewing the compatibility review, not just its filename.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import zipfile

from payload_image_binding import collected, sha
from elf_symbols import dynamic_symbols
from package_coverage import bind_run_inputs

REPO = Path(__file__).resolve().parents[1]


def inspect(data, path, readelf):
    if len(data) < 64 or data[:6] != b'\x7fELF\x02\x01' or int.from_bytes(data[18:20], 'little') != 183:
        raise ValueError('expected little-endian AArch64 ELF64')
    path.write_bytes(data)
    dynamic = subprocess.check_output([str(readelf), '--dynamic', '--wide', str(path)], text=True)
    symbols = subprocess.check_output([str(readelf), '--dyn-syms', '--wide', str(path)], text=True)
    needed = re.findall(r'\(NEEDED\).*?\[([^\]]+)\]', dynamic)
    soname = re.findall(r'\(SONAME\).*?\[([^\]]+)\]', dynamic)
    imports, exports = set(), set()
    for symbol in dynamic_symbols(symbols):
        name = symbol['name'].split('@')[0]
        if symbol['section'] == 'UND':
            imports.add(name)
        elif symbol['binding'] in ('GLOBAL', 'WEAK', 'UNIQUE') and symbol['visibility'] in ('DEFAULT', 'PROTECTED'):
            exports.add(name)
    return dict(sha256=hashlib.sha256(data).hexdigest(), needed=needed, soname=soname,
                xml_imports=sorted(name for name in imports if 'tinyxml2' in name)), exports


def check_archive(package, contract, readelf, scratch):
    if contract.get('schema') != 1 or not contract.get('consumers'):
        raise ValueError('nonempty reviewed ABI contract required')
    provider = contract['provider']
    members=[value['member'] for value in [provider,*contract['consumers']]]
    if len(members)!=len(set(members)):
        raise ValueError('unique reviewed provider/consumer members required')
    rows, issues, exports = [], [], None
    with zipfile.ZipFile(package) as archive:
        members = archive.namelist()
        if len(members) != len(set(members)):
            raise ValueError('duplicate target-files member')
        for index, expected in enumerate([provider, *contract['consumers']]):
            member = expected['member']
            row = dict(member=member, expected_sha256=expected['sha256'], issues=[])
            rows.append(row)
            if member not in members:
                row['issues'].append('required member absent')
                continue
            try:
                measured, defined = inspect(archive.read(member), scratch / str(index), readelf)
            except (ValueError, subprocess.CalledProcessError) as error:
                row['issues'].append(str(error))
                continue
            row.update(measured)
            if measured['sha256'] != expected['sha256']:
                row['issues'].append('bytes differ from reviewed ABI identity')
            if index == 0:
                exports = defined
                if measured['soname'] != [provider['soname']]:
                    row['issues'].append('versioned provider SONAME differs')
            else:
                if measured['needed'].count(provider['soname']) != 1:
                    row['issues'].append('exact versioned XML provider dependency required')
                if 'libtinyxml2.so' in measured['needed']:
                    row['issues'].append('unversioned platform XML dependency prohibited for this legacy consumer')
                if measured['xml_imports'] != expected['xml_imports']:
                    row['issues'].append('XML import contract changed')
                if exports is not None:
                    missing = sorted(set(measured['xml_imports']) - exports)
                    if missing:
                        row['issues'].append('provider lacks XML symbols: ' + ', '.join(missing))
    for row in rows:
        issues.extend(row['member'] + ': ' + issue for issue in row['issues'])
    return dict(vendor_xml_abi_pass=not issues, issues=issues, provider=rows[0], consumers=rows[1:],
                reviewed_layout=contract['reviewed_layout'],
                limits='Exact reviewed provider/caller ABI identities, DT_NEEDED, SONAME, architecture and XML symbols only. This is not a general C++ ABI detector, complete vendor scan or runtime/hardware certification.')


def bind_loading_context(inputs, contract):
    """Require the reviewed loader revisions, including any overlay modifications."""
    recipe = inputs.get('recipe_snapshot', {})
    if inputs.get('target') != 'otapackage' or recipe.get('manifest_sha256') != inputs.get('manifest_sha256'):
        raise ValueError('candidate recipe/input identity mismatch')
    context = contract['loading_context']
    if not context.get('projects'):
        raise ValueError('reviewed XML loading context required')
    for expected in context['projects']:
        matches = [row for row in inputs.get('projects', []) if row['path'] == expected['path']]
        if len(matches) != 1 or matches[0]['revision'] != expected['revision']:
            raise ValueError('XML loader project revision requires renewed review: ' + expected['path'])
        for relative, digest in expected['source_sha256'].items():
            path = expected['path'] + '/' + relative
            overlays = [row for row in recipe.get('files', []) if row['path'] == path]
            if len(overlays) > 1 or (overlays and overlays[0]['canonical_sha256'] != digest):
                raise ValueError('XML loader recipe modification requires renewed review: ' + path)
            if relative in matches[0].get('modified', []) and not overlays:
                raise ValueError('unbound XML loader source modification: ' + path)
    return context


def verify(run_record, candidate_inputs, contract_path, readelf):
    run_id = bind_run_inputs(run_record, candidate_inputs)
    record = json.loads(run_record.read_text())
    if record['state'] != 'success':
        raise ValueError('successful collector required')
    package, entry = collected(record, '/lineage_ferrari-target_files.zip')
    contract = json.loads(contract_path.read_text())
    context = bind_loading_context(json.loads(candidate_inputs.read_text()), contract)
    with tempfile.TemporaryDirectory(prefix='vendor-xml-abi-', dir=REPO / 'tmp') as directory:
        result = check_archive(package, contract, readelf, Path(directory))
    result.update(run_id=run_id, run_record_sha256=sha(run_record),
                  candidate_inputs_sha256=sha(candidate_inputs), loading_context=context,
                  target_files_sha256=entry['sha256'], contract_sha256=sha(contract_path),
                  readelf_sha256=sha(readelf), tool_sha256=sha(Path(__file__)))
    result['symbol_parser_sha256']=sha(Path(__file__).with_name('elf_symbols.py'))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-record', type=Path, required=True)
    parser.add_argument('--candidate-inputs', type=Path, required=True)
    parser.add_argument('--contract', type=Path, required=True)
    parser.add_argument('--readelf', type=Path, default=Path(shutil.which('readelf') or '/usr/bin/readelf'))
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    result = verify(args.run_record, args.candidate_inputs, args.contract, args.readelf.resolve())
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(dict(vendor_xml_abi_pass=result['vendor_xml_abi_pass'], consumers=len(result['consumers']), issues=len(result['issues']))))
    return 0 if result['vendor_xml_abi_pass'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
