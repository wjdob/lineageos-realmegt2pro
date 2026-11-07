"""Check exact target-files members using same-run module installation metadata.

Presence is not ELF dependency resolution, VINTF compatibility or hardware validation.
The CLI requires successful collector provenance for both inputs; it never scans staging.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path, PurePosixPath
import zipfile


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(4*1024*1024),b''): h.update(chunk)
    return h.hexdigest()


def archive_path(installed, product):
    prefix=product.rstrip('/')+'/'
    if not installed.startswith(prefix): raise ValueError('installation outside selected product: '+installed)
    relative=installed[len(prefix):]
    path=PurePosixPath(relative)
    if path.is_absolute() or '..' in path.parts or '\\' in relative or len(path.parts)<2:
        raise ValueError('unsafe installation path')
    partition=path.parts[0]
    if partition not in ('vendor','odm','system','system_ext','product','vendor_dlkm','odm_dlkm','system_dlkm'):
        raise ValueError('unsupported installation partition: '+partition)
    return '/'.join((partition.upper(),*path.parts[1:]))


def is_host_artifact(installed):
    """Host tools can appear in module-info but are not installed into target-files."""
    path=PurePosixPath(installed)
    return (not path.is_absolute() and len(path.parts)>=4 and
            path.parts[:2]==('out','host') and '..' not in path.parts and
            '\\' not in installed)


def merge_requirements(groups):
    """Merge source lists once per module while preserving duplicate-source evidence."""
    entries=[name for group in groups for name in group]
    if not entries: raise ValueError('required module list must not be empty')
    counts=Counter(entries)
    unique=list(dict.fromkeys(entries))
    duplicates=sorted(name for name,count in counts.items() if count>1)
    return unique,duplicates,len(entries)


def validate_requirement_source(requirements, candidate_inputs):
    """Bind the requirements list to the source file reconstructed for this ROM run."""
    if candidate_inputs.get('target')!='otapackage':
        raise ValueError('candidate input record is not for an otapackage run')
    recipe=candidate_inputs.get('recipe_snapshot',{})
    if recipe.get('manifest_sha256')!=candidate_inputs.get('manifest_sha256'):
        raise ValueError('candidate input manifest and recipe snapshot disagree')
    source=requirements.get('source_makefile')
    matches=[row for row in recipe.get('files',[]) if row.get('path')==source]
    if len(matches)!=1:
        raise ValueError('requirements source is not uniquely present in candidate recipe')
    row=matches[0]
    if requirements.get('source_revision_before_recipe')!=row.get('revision'):
        raise ValueError('requirements source revision differs from candidate recipe')
    if requirements.get('source_sha256')!=row.get('canonical_sha256'):
        raise ValueError('requirements source hash differs from reconstructed candidate')
    return {'path':source,'revision':row['revision'],'sha256':row['canonical_sha256'],
            'manifest_sha256':candidate_inputs['manifest_sha256']}


def bind_requirement_source(requirements, candidate_inputs=None):
    """Require recipe evidence for candidate configs that declare a source revision."""
    if requirements.get('source_revision_before_recipe') and candidate_inputs is None:
        raise ValueError('candidate input record required to bind 23.2 requirements')
    if candidate_inputs is None:
        return None
    return validate_requirement_source(requirements,candidate_inputs)


def bind_additional_requirements(requirements, candidate_inputs=None):
    """Require each extra vendor list to carry its own same-run source binding."""
    entries=requirements.get('additional_requirement_groups',[])
    if not isinstance(entries,list):
        raise ValueError('additional requirement groups must be a list')
    groups=[];bindings=[];seen=set()
    for entry in entries:
        if not isinstance(entry,dict):
            raise ValueError('additional requirement group must be an object')
        name=entry.get('name')
        if not isinstance(name,str) or not name or name in seen:
            raise ValueError('unique nonempty additional requirement group name required')
        seen.add(name)
        modules=entry.get('modules')
        if not isinstance(modules,list) or not modules or any(not isinstance(value,str) or not value for value in modules):
            raise ValueError('nonempty additional module list required')
        if candidate_inputs is None:
            raise ValueError('candidate input record required for additional requirement group')
        binding=validate_requirement_source(entry,candidate_inputs)
        binding.update(group=name,module_entries=len(modules))
        groups.append(modules);bindings.append(binding)
    return groups,bindings


def bind_run_inputs(run_record_path, candidate_inputs_path):
    """Reject pairing collected artifacts with a different candidate's input snapshot."""
    run_id = Path(run_record_path).parent.name
    expected_name = run_id + '-inputs.json'
    if not run_id.startswith('candidate-') or Path(candidate_inputs_path).name != expected_name:
        raise ValueError('candidate input snapshot does not match the artifact run ID')
    return run_id


def check(package, module_info, required, product='out/target/product/ferrari'):
    if not required or len(set(required))!=len(required): raise ValueError('required modules must be nonempty and unique')
    rows=[]
    with zipfile.ZipFile(package) as archive:
        names=archive.namelist()
        if len(set(names))!=len(names): raise ValueError('duplicate target-files member')
        members=set(names)
        for name in required:
            module=module_info.get(name)
            row=dict(module=name,files=[],host_paths=[],issues=[])
            if not module:
                row['issues'].append('missing module metadata')
            else:
                row['source_paths']=module.get('path',[])
                row['declared_dependencies']={key:module.get(key,[]) for key in ('shared_libs','system_shared_libs','runtime_dependencies','required')}
                installed=module.get('installed',[])
                if not installed: row['issues'].append('no installed paths')
                device_installs=0
                for path in installed:
                    if is_host_artifact(path):
                        row['host_paths'].append(path)
                        continue
                    try: member=archive_path(path,product)
                    except ValueError as exc:
                        row['issues'].append(str(exc));continue
                    device_installs+=1
                    if member not in members:
                        row['issues'].append('missing exact member: '+member);continue
                    info=archive.getinfo(member)
                    if info.is_dir() or info.file_size==0:
                        row['issues'].append('empty/non-file member: '+member);continue
                    h=hashlib.sha256()
                    with archive.open(info) as stream:
                        for chunk in iter(lambda:stream.read(1024*1024),b''):h.update(chunk)
                    row['files'].append(dict(member=member,bytes=info.file_size,sha256=h.hexdigest()))
                if installed and device_installs==0:
                    row['issues'].append('no target-product installation')
            rows.append(row)
    return dict(package_presence_pass=all(not row['issues'] for row in rows),modules=rows,
                limits='exact packaged-file presence only; declared dependencies still require ELF/namespace resolution; no VINTF or runtime certification')


def check_ramdisk_files(package, requirements):
    """Recovery variants are not normal partition installs or reliably named module aliases."""
    if not isinstance(requirements,list) or not requirements:raise ValueError('nonempty ramdisk requirements list required')
    rows=[];seen=set()
    with zipfile.ZipFile(package) as archive:
        names=archive.namelist()
        if len(names)!=len(set(names)):raise ValueError('duplicate target-files member')
        for entry in requirements:
            member=entry['member'];path=PurePosixPath(member)
            if (not member.startswith(('RECOVERY/RAMDISK/','VENDOR_BOOT/RAMDISK/')) or
                    '..' in path.parts or '\\' in member or member in seen):
                raise ValueError('unique exact recovery/vendor ramdisk member required')
            seen.add(member);row=dict(module_alias=entry['module_alias'],member=member,issues=[]);rows.append(row)
            if member not in names:row['issues'].append('missing exact ramdisk member');continue
            info=archive.getinfo(member)
            if info.is_dir() or info.file_size==0:
                row['issues'].append('empty/non-file ramdisk member');continue
            row.update(bytes=info.file_size,sha256=hashlib.sha256(archive.read(member)).hexdigest())
    return dict(ramdisk_presence_pass=all(not row['issues'] for row in rows),ramdisk_files=rows)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run-record',type=Path,required=True)
    p.add_argument('--requirements',type=Path,required=True)
    p.add_argument('--report',type=Path,required=True)
    p.add_argument('--candidate-inputs',type=Path)
    a=p.parse_args()
    record=json.loads(a.run_record.read_text())
    if record.get('state')!='success':raise ValueError('successful collector record required')
    def input_file(suffix):
        matches=[entry for entry in record['artifacts'] if entry['path'].endswith(suffix)]
        if len(matches)!=1:raise ValueError('one collected '+suffix+' required')
        entry=matches[0]; path=Path(entry['collected'])
        if path.stat().st_size!=entry['bytes'] or sha(path)!=entry['sha256']:
            raise ValueError('collected input changed: '+str(path))
        return path
    package=input_file('/lineage_ferrari-target_files.zip')
    metadata=input_file('/module-info.json')
    requirements=json.loads(a.requirements.read_text())
    candidate_inputs=json.loads(a.candidate_inputs.read_text()) if a.candidate_inputs else None
    run_id = bind_run_inputs(a.run_record, a.candidate_inputs) if candidate_inputs is not None else None
    source_binding=bind_requirement_source(requirements,candidate_inputs)
    extra_groups,extra_bindings=bind_additional_requirements(requirements,candidate_inputs)
    required,duplicates,input_count=merge_requirements(
        (requirements['tail_modules'],requirements['sensor_modules'],
         requirements.get('runtime_dependency_modules', []),*extra_groups))
    result=check(package,json.loads(metadata.read_text()),required)
    if 'ramdisk_file_requirements' in requirements:
        ramdisk=check_ramdisk_files(package,requirements['ramdisk_file_requirements'])
        result.update(ramdisk)
        result['package_presence_pass'] &= ramdisk['ramdisk_presence_pass']
    result['requirement_audit']={'input_entries':input_count,
        'unique_modules_checked':len(required),'duplicate_source_names':duplicates}
    if source_binding:
        result['requirement_source']=source_binding
        result['provenance_candidate_inputs_sha256']=sha(a.candidate_inputs)
        result['provenance_run_id']=run_id
    if extra_bindings:
        result['additional_requirement_sources']=extra_bindings
    result['provenance']={str(path):sha(path) for path in (a.run_record,a.requirements,metadata,package)}
    a.report.parent.mkdir(parents=True,exist_ok=True)
    a.report.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(package_presence_pass=result['package_presence_pass'],modules=len(result['modules']))))
    return 0 if result['package_presence_pass'] else 1


if __name__=='__main__':raise SystemExit(main())
