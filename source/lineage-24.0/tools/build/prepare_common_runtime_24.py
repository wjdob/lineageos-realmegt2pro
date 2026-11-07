"""Reproduce the private performance inputs from the accepted23b target-files."""
import argparse
import json
from pathlib import Path
import shutil
import stat
import zipfile

from common_runtime_24 import CONTRACT, REPO, rows, sha, validate_provider
from storage_24 import STORE, verify_store


def prepare(package, output):
    verify_store()
    contract = json.loads(CONTRACT.read_text())
    if output != STORE / contract['provider'] or output.exists():
        raise ValueError('new contract-selected input provider required')
    if sha(package) != contract['source']['sha256']:
        raise ValueError('accepted source target-files hash differs')
    selected = rows(contract)
    # Read and validate the complete selected set before creating the provider.
    with zipfile.ZipFile(package) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError('duplicate source target-files member')
        for row in selected:
            info = archive.getinfo(row['member'])
            if stat.S_ISLNK(info.external_attr >> 16) or info.file_size != row['bytes']:
                raise ValueError('unexpected runtime source member: ' + row['member'])
        output.mkdir(parents=True, exist_ok=False)
        for row in selected:
            dst = output / row['path']
            dst.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(row['member']) as src, dst.open('xb') as stream:
                shutil.copyfileobj(src, stream)
    validate_provider(contract, output)
    receipt = {'schema': 1, 'contract_sha256': sha(CONTRACT),
               'preparer_sha256': sha(Path(__file__)), 'source_sha256': contract['source']['sha256'],
               'files': contract['files'],
               'distribution_scope': 'Private local engineering; proprietary assets are not committed or approved for redistribution.'}
    (output / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    return {'files_verified': len(selected), 'receipt_sha256': sha(output / 'receipt.json')}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target-files', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare(args.target_files, args.output), indent=2))
