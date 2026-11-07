"""Build/collect with explicit run records; only the CLI may operate on a build tree."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import shutil
import subprocess
import sys
import time
from apply_recipe import apply, isolated, REPO, safe_file


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(4*1024*1024),b''): h.update(chunk)
    return h.hexdigest()


def write_json(path,data):
    tmp=path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data,indent=2)+'\n')
    # Windows readers may briefly deny delete-sharing on a DrvFS destination.
    # Keep atomic replacement and fail on persistent denial; do not kill a build
    # merely because one heartbeat collided with a short-lived reader.
    for attempt in range(51):
        try:
            os.replace(tmp,path)
            return
        except PermissionError:
            if attempt==50:raise
            time.sleep(.1)


def reset_run_metrics(tree):
    isolated(tree)
    # Soong renames this disposable directory at startup. A lower-layer directory
    # cannot be renamed on this overlay; remove its view so Soong creates a new
    # upper-layer directory. Original metrics remain in the preserved lower tree.
    metrics=safe_file(tree,'out/soong/metrics_aggregation')
    if metrics.exists():
        if not metrics.is_dir():raise ValueError('metrics path is not a directory')
        shutil.rmtree(metrics)


def execute(command,tree,artifacts,records,*,timeout=7200,min_free=20*1024**3,space_path=Path('/mnt/c'),poll=5,
            max_used=None,allocation_path=None,extra_space_floors=()):
    records.mkdir(parents=True,exist_ok=False)
    report={'state':'preparing','command':command,'started_ns':time.time_ns(),'artifacts':[]}
    record=records/'result.json'
    write_json(record,report)
    child=None
    def check_extra_space(collection_bytes=0):
        for path, floor in extra_space_floors:
            if floor < 0 or shutil.disk_usage(path).free < floor + collection_bytes:
                raise RuntimeError('storage reserve reached: ' + str(path))
    interrupted=[]
    handlers={}
    def stop(sig,_frame): interrupted.append(sig)
    try:
        for sig in (signal.SIGTERM,signal.SIGINT):
            handlers[sig]=signal.signal(sig,stop)
        outputs=[]
        for relative in artifacts:
            path=safe_file(tree,relative)
            # A compiled Android17 ABI probe needs this one vendor provider.
            # Keep arbitrary libraries and source paths outside the collector.
            codec_probe=relative=='out/target/product/ferrari/vendor/lib64/libcodec2_hidl@1.0.so'
            init_probe=relative in ('out/target/product/ferrari/ramdisk/init','out/target/product/ferrari/system/bin/init')
            allowed_kind=path.suffix in ('.img','.zip') or path.name=='module-info.json' or codec_probe or init_probe
            if not Path(relative).parts or Path(relative).parts[0]!='out' or not allowed_kind:
                raise ValueError('artifact must be a named image, zip, module-info.json, exact Codec2 probe or exact init diagnostic probe under out/')
            if path.exists() and not path.is_file(): raise ValueError('artifact is not a file')
            outputs.append(path)
        if len(set(outputs))!=len(outputs): raise ValueError('duplicate artifact paths')
        if shutil.disk_usage(space_path).free<min_free: raise RuntimeError('insufficient physical storage')
        check_extra_space()
        if max_used is not None:
            if allocation_path is None or max_used <= 0: raise ValueError('invalid allocation budget')
            if shutil.disk_usage(allocation_path).used>max_used: raise RuntimeError('allocation budget reached')
        # CLI has already proved private-overlay isolation. Unlinking hides old lower-layer
        # artifacts so a no-op success cannot collect an old image. Unit tests use scratch.
        for path in outputs:
            if path.exists(): path.unlink()
        report['state']='running'; report['build_started_ns']=time.time_ns()
        write_json(record,report)
        start=time.monotonic()
        with (records/'build.log').open('wb') as log:
            child=subprocess.Popen(command,cwd=tree,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            reason=None
            while child.poll() is None:
                report['heartbeat_ns']=time.time_ns()
                report['physical_free_bytes']=shutil.disk_usage(space_path).free
                check_extra_space()
                write_json(record,report)
                if interrupted: reason='interrupted'
                elif (records/'cancel').exists(): reason='cancel requested'
                elif time.monotonic()-start>timeout: reason='timeout'
                elif shutil.disk_usage(space_path).free<min_free: reason='physical storage reserve reached'
                elif max_used is not None and shutil.disk_usage(allocation_path).used>max_used: reason='allocation budget reached'
                if reason:
                    os.killpg(child.pid,signal.SIGTERM)
                    try: child.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        os.killpg(child.pid,signal.SIGKILL); child.wait()
                    raise RuntimeError(reason)
                time.sleep(poll)
        report['exit_code']=child.returncode
        if interrupted: raise RuntimeError('interrupted')
        if child.returncode: raise RuntimeError('build exited nonzero')
        for path in outputs:
            if not path.is_file() or path.stat().st_size==0: raise RuntimeError('missing/empty output: '+str(path))
            if path.stat().st_mtime_ns<report['build_started_ns']: raise RuntimeError('stale output timestamp: '+str(path))
            entry={'path':str(path.relative_to(tree)),'bytes':path.stat().st_size,'sha256':sha(path),'mtime_ns':path.stat().st_mtime_ns}
            destination=records/'artifacts'/entry['path']
            if shutil.disk_usage(space_path).free<min_free+entry['bytes']: raise RuntimeError('insufficient collection space')
            check_extra_space(entry['bytes'])
            destination.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(path,destination)
            if sha(destination)!=entry['sha256']: raise RuntimeError('artifact copy hash mismatch')
            entry['collected']=str(destination)
            report['artifacts'].append(entry)
        if interrupted or (records/'cancel').exists(): raise RuntimeError('interrupted during collection')
        report['state']='success'
    except Exception as exc:
        report['state']='failed'; report['error']=str(exc)
    finally:
        if child is not None and child.poll() is None:
            os.killpg(child.pid,signal.SIGKILL); child.wait()
        if child is not None: report['exit_code']=child.returncode
        for sig,handler in handlers.items(): signal.signal(sig,handler)
        report['finished_ns']=time.time_ns()
        if (records/'build.log').exists(): report['log_sha256']=sha(records/'build.log')
        write_json(record,report)
    return report


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--target',choices=['recoveryimage','otapackage','nothing'],required=True)
    p.add_argument('--run-id',required=True)
    args=p.parse_args()
    import re
    if not re.fullmatch('[a-z0-9][a-z0-9-]{0,63}',args.run_id): raise SystemExit('invalid run id')
    tree=Path('/build/lineage')
    isolated(tree)
    records=REPO/'.local/goals/runs'/args.run_id
    if records.exists(): raise SystemExit('run id already exists')
    reset_run_metrics(tree)
    inputs=REPO/'.local/goals/run-inputs'/args.run_id
    inputs.mkdir(parents=True,exist_ok=False)
    profile='rom' if args.target=='otapackage' else 'recovery'
    recipe=apply(tree,REPO/'tmp/goals/recipe',write=True,profile=profile)
    write_json(inputs/'recipe.json',recipe)
    revision=subprocess.check_output(['git','-c','safe.directory='+str(REPO),'-C',str(REPO),'rev-parse','HEAD'],text=True).strip()
    paths=(tree/'.repo/project.list').read_text().splitlines()
    projects=[]
    for path in paths:
        git=['git','-C',str(tree/path)]
        head=subprocess.check_output(git+['rev-parse','HEAD'],text=True).strip()
        dirty=subprocess.check_output(git+['status','--porcelain=v1','--untracked-files=normal'],text=True)
        projects.append({'path':path,'head':head,'status':dirty})
        if dirty:
            dest=inputs/'diffs'/path/'tracked.patch';dest.parent.mkdir(parents=True,exist_ok=True)
            dest.write_bytes(subprocess.check_output(git+['diff','--binary','HEAD']))
    source_inputs={str(p.relative_to(REPO)):sha(p) for p in [*sorted((REPO/'tools/build').glob('*.py')),*sorted((REPO/'tools/build').glob('*.sh')),REPO/'tools/build/recipe.json',REPO/'tools/lineage_local_manifest.xml',REPO/'manifests/lineage-23.0-locked.xml',*sorted((REPO/'patches').glob('*')),*sorted((REPO/'certs').glob('*'))] if p.is_file()}
    write_json(inputs/'provenance.json',{'repository_commit':revision,'inputs':source_inputs,'projects':projects,'uname':list(os.uname()),'python':sys.version,'cache_policy':'private overlay of preserved build tree including existing intermediates; expected final artifacts removed before build'})
    product='out/target/product/ferrari/'
    artifact={'recoveryimage':[product+'recovery.img'],
              'otapackage':[product+'lineage_ferrari-ota.zip',
                            product+'obj/PACKAGING/target_files_intermediates/lineage_ferrari-target_files.zip',
                            product+'module-info.json'],
              'nothing':[]}[args.target]
    result=execute(['bash',str(REPO/'tools/build/build_target.sh'),args.target,'5'],tree,artifact,records,timeout=36000)
    print(json.dumps(result,indent=2))
    return 0 if result['state']=='success' else 1


if __name__=='__main__': sys.exit(main())
