"""Read-only inventory of private overlay caches and their live dependencies.

This never deletes caches, stops jobs, mounts filesystems or compacts WSL. The
review set is a closed batch, not permission to remove individual ancestors.
"""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

REPO = Path(__file__).resolve().parents[2]
WORK = Path('/build/realmegt2pro-next-work')
NAME = r'[a-z0-9][a-z0-9._-]{0,127}'


def read_document(path, boundary):
    if not path.resolve().is_relative_to(boundary):
        raise ValueError('metadata escapes its boundary')
    cursor = path
    while cursor != boundary:
        if cursor.is_symlink():
            raise ValueError('symlink metadata refused')
        cursor = cursor.parent
    if not path.is_file() or path.stat().st_size > 4 * 1024**2:
        raise ValueError('missing, nonregular or oversized metadata')
    data = path.read_bytes()
    document = json.loads(data)
    if not isinstance(document, dict):
        raise ValueError('metadata must be an object')
    return document, hashlib.sha256(data).hexdigest()


def scan_mounts(work, proc=Path('/proc')):
    """Read accessible process mount views; incomplete visibility is held.

    Do not deduplicate reads by namespace: processes can have different chroots
    inside the same mount namespace and thus expose different mount views.
    """
    references, issues, seen = {}, [], set()
    expression = re.compile(re.escape(str(work)) + r'/([^/,\s:]+)(?=/|[,\s:]|$)')
    count = 0
    for process in sorted(proc.iterdir()):
        if not process.name.isdecimal():
            continue
        count += 1
        try:
            namespace = os.readlink(process/'ns/mnt')
            text = (process/'mountinfo').read_text()
            text = re.sub(r'\\([0-7]{3})', lambda m: chr(int(m[1], 8)), text)
            seen.add(namespace)
            for name in set(expression.findall(text)):
                references.setdefault(name, []).append(dict(pid=int(process.name), namespace=namespace))
        except (FileNotFoundError, ProcessLookupError):
            # Normal process exit during the snapshot; not a terminal build claim.
            continue
        except OSError as error:
            issues.append(dict(pid=int(process.name), error=type(error).__name__))
    return dict(references=references, issues=issues, processes_seen=count,
                namespaces_seen=len(seen), complete=not issues)


def inventory(work, records, keep=(), mounts=None, measure=False):
    work, records = Path(work), Path(records)
    if (not work.is_absolute() or work.resolve() != work or not work.is_dir()
            or records.resolve() != records or not records.is_dir()):
        raise ValueError('canonical existing work and record directories required')
    rows, issues = {}, []
    for child in sorted(work.iterdir()):
        name = child.name
        row = dict(name=name, path=str(child), base=None, state=None, terminal=False,
                   protected_reasons=[], allocated_bytes=None)
        rows[name] = row
        try:
            if (not re.fullmatch(NAME, name) or child.is_symlink() or not child.is_dir()
                    or child.resolve().parent != work):
                raise ValueError('unmanaged or symlink entry')
            marker, row['marker_sha256'] = read_document(child/'upper/.realme-next-isolated.json', work)
            if marker.get('run') != str(child):
                raise ValueError('marker does not name its exact run')
            base = marker.get('base_run')
            if base is not None:
                if not isinstance(base, str):
                    raise ValueError('invalid base identity')
                parent = Path(base)
                if (parent.parent != work or not re.fullmatch(NAME, parent.name)
                        or parent.resolve() != parent):
                    raise ValueError('base escapes work root or resolves through a symlink')
                row['base'] = parent.name
            result, row['result_sha256'] = read_document(records/name/'result.json', records)
            state, finished = result.get('state'), result.get('finished_ns')
            row['state'] = state if isinstance(state, str) else None
            row['terminal'] = (state in ('success', 'failed') and type(finished) is int and finished > 0)
        except (ValueError, OSError, KeyError) as error:
            issues.append(dict(name=name, error=str(error)))

    mounts = scan_mounts(work) if mounts is None else mounts
    if not mounts['complete']:
        issues.append(dict(error='mount namespace visibility incomplete'))
    for name in mounts['references']:
        if name not in rows:
            issues.append(dict(name=name, error='live reference to an unindexed cache'))
    keep = set(keep)
    for name in keep:
        if name not in rows:
            issues.append(dict(name=name, error='requested retained root missing'))

    ancestry = {}
    for name in rows:
        chain, current = [], name
        while current is not None:
            if current not in rows:
                issues.append(dict(name=name, error='missing cache ancestor: '+current))
                break
            if current in chain:
                issues.append(dict(name=name, error='cyclic cache ancestry'))
                break
            chain.append(current)
            current = rows[current]['base']
        ancestry[name] = chain
    roots = {name: [] for name in rows}
    for name, row in rows.items():
        if name in keep:
            roots[name].append('explicitly retained')
        if not row['terminal']:
            roots[name].append('nonterminal or unverified completion')
        if name in mounts['references']:
            roots[name].append('live mount namespace reference')
    for root, reasons in roots.items():
        if reasons:
            for name in ancestry[root]:
                rows[name]['protected_reasons'].extend(
                    reasons if name == root else ['ancestor required by '+root])
    for name, row in rows.items():
        row['protected_reasons'] = sorted(set(row['protected_reasons']))
        row['ancestors'] = ancestry[name][1:]
        row['dependents'] = sorted(n for n, r in rows.items() if r['base'] == name)
        row['live_references'] = mounts['references'].get(name, [])
    # Any unknown ownership/dependency/visibility stops review-set generation.
    selected = []
    if not issues and keep:
        selected = sorted((n for n, r in rows.items() if not r['protected_reasons']),
                          key=lambda n: (-len(ancestry[n]), n))
    if measure:
        for name in selected:
            path = work/name
            result = subprocess.run(['du', '-s', '-x', '-B1', '-P', '--', str(path)],
                                    capture_output=True, text=True, timeout=120)
            if result.returncode:
                issues.append(dict(name=name, error='allocated-byte measurement failed'))
                continue
            value, measured = result.stdout.rstrip('\n').split('\t', 1)
            if measured != str(path) or not value.isdecimal():
                raise ValueError('unexpected du output')
            rows[name]['allocated_bytes'] = int(value)
    complete = not issues
    return dict(schema=1, observed_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                work_root=str(work), records_root=str(records), complete=complete,
                retained_roots=sorted(keep), rows=list(rows.values()), issues=issues,
                mount_scan=mounts, closed_review_set_child_first=selected if complete else [],
                measured_review_bytes=(sum(rows[n]['allocated_bytes'] for n in selected)
                                       if measure and complete and keep else None),
                limits='Read-only point-in-time inventory, not deletion authorization or an atomic quiescence proof. '
                'The review set is one closed batch, never individually removable ancestors. '
                'Missing/invalid metadata, cycles, unknown live references or inaccessible namespaces hold all selection. '
                'No selection without an explicit retained root. Optional du measures only unprotected review trees; '
                'hardlinks across separate trees may be counted twice. Linux allocated bytes are not Windows reclaimable '
                'bytes or VHD allocation. Original source, Git, signing, collected artifacts and backups are outside this inventory. '
                'Revalidate ownership, live services/mounts, source reconstruction and protected artifacts before any separately reviewed cleanup.')


def write_report(path, report):
    path = path.resolve()
    if not any(path.is_relative_to(REPO/root) for root in ('.local', 'tmp')):
        raise ValueError('machine evidence must stay under repository .local or tmp')
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream:
        stream.write(json.dumps(report, indent=2)+'\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--keep', action='append', default=[], help='retain this exact cache and all its ancestors')
    parser.add_argument('--measure', action='store_true', help='du allocated bytes of the unprotected review batch only')
    parser.add_argument('--report', type=Path, help='new private JSON evidence file under repository .local or tmp')
    args = parser.parse_args()
    if sys.platform != 'linux':
        parser.error('run in the build WSL distribution')
    report = inventory(WORK, REPO/'.local/goals/runs', args.keep, measure=args.measure)
    report['tool_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    if args.report:
        write_report(args.report, report)
    print(json.dumps(report, indent=2))
    return 0 if report['complete'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
