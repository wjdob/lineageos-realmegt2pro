"""Offline integrity/coverage checks for explicit captures, never a restore recipe.

The catalogue maps filenames to partition IDs explicitly. Several captures may map
to one partition. Observation-time hashes do not establish original capture provenance.
No device command, manifest creation, or partition write is implemented here.
"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re


def validate(catalog):
    if catalog.get('schema') != 1 or catalog.get('purpose') != 'capture-integrity-inventory':
        raise ValueError('unsupported catalogue schema/purpose')
    if 'complete' in catalog and not isinstance(catalog['complete'], bool):
        raise ValueError('capture completion flag must be boolean')
    rows=catalog.get('captures')
    if not isinstance(rows,list) or not rows: raise ValueError('no captures')
    seen=set()
    for row in rows:
        name=row['file']; path=PurePosixPath(name)
        if not name or path.is_absolute() or '..' in path.parts or '\\' in name or ':' in name or str(path)=='.':
            raise ValueError('unsafe capture path')
        key=str(path)
        if key in seen: raise ValueError('duplicate capture path')
        seen.add(key)
        if not re.fullmatch('[A-Za-z0-9_]+',row['partition']): raise ValueError('invalid partition ID')
        if not isinstance(row['bytes'],int) or isinstance(row['bytes'],bool) or row['bytes']<=0: raise ValueError('invalid byte count')
        if not re.fullmatch('[a-f0-9]{64}',row['sha256']): raise ValueError('invalid SHA-256')
        if row.get('provenance') not in ('historical-capture-unverified','fresh-device-hash-verified'):
            raise ValueError('capture provenance must be explicit')
        if not row.get('observed_utc'): raise ValueError('hash observation time required')
    return rows


def verify(catalog,root,required=()):
    rows=validate(catalog)
    planned = {}
    if 'plan' in catalog:
        if not isinstance(catalog['plan'], list) or not catalog['plan']:
            raise ValueError('empty capture plan')
        for entry in catalog['plan']:
            name, size = entry['partition'], entry['bytes']
            if not re.fullmatch('[A-Za-z0-9_]+', name) or name in planned:
                raise ValueError('invalid or duplicate planned partition')
            if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
                raise ValueError('invalid planned byte count')
            planned[name] = size
        for row in rows:
            if planned.get(row['partition']) != row['bytes']:
                raise ValueError('capture differs from declared partition plan')
    root=Path(root).resolve()
    results=[];verified_partitions=set()
    for row in rows:
        path=root/row['file']
        if not path.resolve().is_relative_to(root): raise ValueError('capture escapes root')
        if path.is_symlink(): raise ValueError('capture is a symlink')
        state='match'
        if not path.is_file(): state='missing'
        elif path.stat().st_size!=row['bytes']: state='size-mismatch'
        else:
            h=hashlib.sha256()
            with path.open('rb') as f:
                for block in iter(lambda:f.read(4*1024*1024),b''):h.update(block)
            if h.hexdigest()!=row['sha256']:state='hash-mismatch'
        if state=='match':verified_partitions.add(row['partition'])
        results.append({'file':row['file'],'partition':row['partition'],'state':state,'provenance':row['provenance']})
    missing=sorted((set(required) | set(planned))-verified_partitions)
    return {'integrity_pass':catalog.get('complete') is not False and not missing and all(r['state']=='match' for r in results),
            'capture_complete':catalog.get('complete'),
            'capture_count':len(rows),'distinct_partitions':len({r['partition'] for r in rows}),
            'missing_required_captures':missing,'captures':results,
            'meaning':'stored-file integrity and requested capture coverage only; no restore procedure or original provenance certification'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('catalog',type=Path)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--require',default='',help='comma-separated required backup IDs, not a write set')
    parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args()
    result=verify(json.loads(args.catalog.read_text(encoding='utf-8-sig')),args.root,[p for p in args.require.split(',') if p])
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='captures'},indent=2))
    return 0 if result['integrity_pass'] else 1


if __name__=='__main__':raise SystemExit(main())
