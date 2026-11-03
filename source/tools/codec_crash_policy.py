"""Check the narrow audio sandbox crash-reporting delta and packaged delivery."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / 'configs/codec-crash-policy-23.2.json'


def check_bytes(data, contract=None):
    contract = contract or json.loads(CONTRACT.read_text())
    suffix = contract['append'].encode()
    if hashlib.sha256(data).hexdigest() != contract['candidate_sha256']:
        raise ValueError('unreviewed audio crash-report policy')
    if not data.endswith(suffix) or hashlib.sha256(data[:-len(suffix)]).hexdigest() != contract['base_sha256']:
        raise ValueError('inherited audio policy changed')
    rules = [line for line in suffix.decode().splitlines() if line and not line.startswith('#')]
    if rules != ['uname: 1']:
        raise ValueError('crash-report delta exceeds uname')
    return {'sha256': hashlib.sha256(data).hexdigest(), 'added_syscalls': ['uname'],
            'limits': 'Exact policy delta only. Native minijail parsing, original-fault reproduction, crash-report delivery and device media behavior require separate evidence.'}


def check_source(tree):
    contract = json.loads(CONTRACT.read_text())
    return check_bytes((Path(tree)/contract['project']/contract['relative']).read_bytes(), contract)


def check_package(target_files):
    contract = json.loads(CONTRACT.read_text())
    with zipfile.ZipFile(target_files) as archive:
        return check_bytes(archive.read(contract['target_member']), contract)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--source-tree', type=Path)
    group.add_argument('--target-files', type=Path)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    result = check_source(args.source_tree) if args.source_tree else check_package(args.target_files)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result, indent=2))
