"""Reuse a qualified Ninja graph for C++-only init diagnostics, never for an OTA."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path

from apply_recipe import isolated, safe_file
from init_diagnostic_cache_24 import validate_cache


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def graph_files(output):
    found = {}
    pending = ['out/combined-lineage_ferrari.ninja']
    while pending:
        name = pending.pop()
        if name in found:
            continue
        if not name.startswith('out/') or '$' in name:
            raise ValueError('unsupported graph include')
        path = safe_file(output, name[4:])
        if not path.is_file():
            raise ValueError('missing qualified graph: ' + name)
        found[name] = {'sha256': sha(path), 'mtime_ns': path.stat().st_mtime_ns}
        with path.open() as stream:
            for line in stream:
                if line.startswith(('include ', 'subninja ')):
                    pending.append(line.split(None, 1)[1].strip())
    return found


def cohort(inputs):
    common=inputs.get('common_runtime',{})
    if not common.get('contract_sha256') or not common.get('receipt_sha256'):
        raise ValueError('cached graph requires the reviewed common runtime input identity')
    return {'manifest_sha256': inputs['manifest_sha256'],
            'recipe_sha256': inputs['recipe_sha256'],
            'vendor_contract_sha256': inputs['vendor_inputs']['contract_sha256'],
            'vendor_receipt_sha256': inputs['vendor_inputs']['receipt_sha256'],
            'common_contract_sha256':common['contract_sha256'],
            'common_receipt_sha256':common['receipt_sha256'],
            'cache_identity': inputs['output_cache']['identity'], 'release': inputs['release']}


def validate_inputs(current, previous):
    if current.get('target') != 'init-diagnostic':
        raise ValueError('cached graph is confined to first-stage diagnostics')
    if cohort(current) != previous['cohort']:
        raise ValueError('source/vendor/recipe/cache cohort changed; regenerate normally')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--freeze-output', type=Path)
    parser.add_argument('--source-records', type=Path)
    parser.add_argument('--source-inputs', type=Path)
    parser.add_argument('--source-tree', type=Path)
    parser.add_argument('--candidate-inputs', type=Path)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    if args.freeze_output:
        output = validate_cache(args.freeze_output)
        result_path = args.source_records/'result.json'
        result = json.loads(result_path.read_text())
        inputs = json.loads(args.source_inputs.read_text())
        if result['state'] != 'success' or inputs['target'] != 'init-diagnostic':
            raise ValueError('completed matching diagnostic source build required')
        fd = os.open(output.parent/'lease.lock', os.O_RDWR | os.O_NOFOLLOW)
        with os.fdopen(fd, 'r+b') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            files = graph_files(output)
            if any(row['mtime_ns'] > result['finished_ns'] for row in files.values()):
                raise ValueError('graph changed after the accepted source build')
            record = {'cohort': cohort(inputs), 'graphs': files,
                      'source_result_sha256': sha(result_path),
                      'source_inputs_sha256': sha(args.source_inputs),
                      'source_build_identity': inputs['build_identity'],
                      'scope': 'Known successful graph; reusable only for first-stage C++ diagnostic source changes. No build files, release, vendor contract, source manifest or product identity changes.'}
            tag = output.parent/'init-graph.json'
            with tag.open('x') as stream:
                json.dump(record, stream, indent=2)
            args.report.write_text(json.dumps(record, indent=2))
            print(json.dumps({'qualified_graphs': len(files), 'tag': str(tag)}))
        return
    isolated(args.source_tree)
    inputs = json.loads(args.candidate_inputs.read_text())
    relative = str(Path(__file__).relative_to(Path(__file__).resolve().parents[2]))
    if inputs.get('source_hashes', {}).get(relative) != sha(__file__):
        raise ValueError('graph qualifier differs from frozen run inputs')
    output = validate_cache(Path(inputs['output_cache']['path']))
    if not (args.source_tree/'out').samefile(output):
        raise ValueError('graph differs from this leased output bind')
    tag = safe_file(output.parent, 'init-graph.json')
    record = json.loads(tag.read_text())
    validate_inputs(inputs, record)
    actual = graph_files(output)
    if {n: row['sha256'] for n, row in actual.items()} != {n: row['sha256'] for n, row in record['graphs'].items()}:
        raise ValueError('cached graph changed; regenerate normally')
    args.report.write_text(json.dumps({'mode': 'qualified-cached-init-graph',
        'graph_receipt_sha256': sha(tag), 'graphs': len(actual),
        'source_graph_build_identity': record['source_build_identity'],
        'limits': 'Existing compile rules only; same canonical source/vendor/build configuration. New C++ diagnostic preimages checked separately. Artifact is an init probe, not a new OS/version claim.'}, indent=2))
    print('Qualified cached init graph; source analysis is unnecessary for these C++ changes.')


if __name__ == '__main__':
    main()
