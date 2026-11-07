"""Fetch only hash-bound LFS payloads for pinned projects in the dedicated 24.0 tree."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

from check_candidate import contained
from manifest import read_pins
from storage_24 import STORE, verify_store

REPO = Path(__file__).resolve().parents[2]


def inspect(project, env):
    data = json.loads(subprocess.check_output(
        ['git','-C',str(project),'lfs','ls-files','--json'],env=env))
    rows = []
    for row in data['files'] or []:
        path = contained(project,row['name'])
        digest = None
        if path.is_file() and path.stat().st_size == row['size']:
            with path.open('rb') as stream:
                digest = hashlib.file_digest(stream,'sha256').hexdigest()
        rows.append({**row,'verified':digest == row['oid']})
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',action='append',required=True)
    parser.add_argument('--fetch',action='store_true')
    parser.add_argument('--report',type=Path,required=True)
    args = parser.parse_args()
    verify_store()
    if args.report.exists():
        raise ValueError('preserve previous LFS evidence')
    tree = STORE/'tree'
    pins = {path:revision for (_,path),revision in read_pins(REPO/'manifests/lineage-24.0-candidate.xml').items()}
    manifest = ET.parse(REPO/'manifests/lineage-24.0-candidate.xml').getroot()
    default = manifest.find('default')
    remotes = {p.get('path',p.get('name')):p.get('remote',default.get('remote') if default is not None else None)
               for p in manifest.findall('project')}
    env = {**os.environ,'GIT_OPTIONAL_LOCKS':'0','TMPDIR':str(STORE/'tmp'),'GIT_TERMINAL_PROMPT':'0'}
    report = {'projects':[],'fetch_requested':args.fetch,'ok':True,
              'limits':'Host LFS objects/worktree materialization only. No revision reset, build, device or firmware write.'}
    args.report.parent.mkdir(parents=True,exist_ok=True)
    try:
        for name in args.project:
            if name not in pins:
                raise ValueError('project is not pinned: '+name)
            project = contained(tree,name)
            head = subprocess.check_output(['git','-C',str(project),'rev-parse','HEAD'],env=env,text=True).strip()
            if head != pins[name]:
                raise ValueError('project HEAD differs from pin: '+name)
            row = {'project':name,'revision':head,'before':inspect(project,env)}
            report['projects'].append(row)
            missing = [r['name'] for r in row['before'] if not r['verified']]
            if missing and args.fetch:
                remote = remotes[name]
                available = subprocess.check_output(['git','-C',str(project),'remote'],env=env,text=True).splitlines()
                if not remote or remote not in available:
                    raise ValueError('manifest remote is missing: '+name)
                log = args.report.parent/(name.replace('/','_')+'.log')
                with log.open('xb') as output:
                    subprocess.run(['git','-C',str(project),'lfs','fetch',remote,head],env=env,
                                   stdout=output,stderr=subprocess.STDOUT,check=True,timeout=3600)
                    subprocess.run(['git','-C',str(project),'lfs','checkout','--',*missing],env=env,
                                   stdout=output,stderr=subprocess.STDOUT,check=True,timeout=600)
            row['after'] = inspect(project,env)
            report['ok'] &= all(r['verified'] for r in row['after'])
            print(name,'verified',sum(r['verified'] for r in row['after']),'of',len(row['after']),flush=True)
    except Exception as exc:
        report['ok'] = False
        report['error'] = str(exc)
        raise
    finally:
        args.report.write_text(json.dumps(report,indent=2)+'\n')
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
