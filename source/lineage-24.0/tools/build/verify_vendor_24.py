"""Bind every selected Ferrari vendor file to its actual target-files member."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
import zipfile
from common_runtime_24 import check_package as check_common, CONTRACT as COMMON_CONTRACT
from kernel_layout_24 import check_subsystem_boot_actions, SUBSYSTEM_WRITE_SOURCE
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from device_responsibilities24 import check as check_responsibilities

REPO = Path(__file__).resolve().parents[2]
SENSOR_SOURCE = 'vendor/oneplus/sm8450-common/proprietary/vendor/lib64/sensors.ssc.so'
SENSOR_MEMBER = 'VENDOR/lib64/sensors.ssc.so'


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def member(path):
    parts = PurePosixPath(path).parts
    if (len(parts)<3 or parts[0]!='proprietary' or parts[1] not in
            ('odm','vendor','system','system_ext','product') or '\\' in path or
            ':' in path or any(p in ('','.','..') for p in path.split('/'))):
        raise ValueError('unsupported vendor package path: '+path)
    return parts[1].upper()+'/'+str(PurePosixPath(*parts[2:]))


def check(package, rows):
    files = [row for row in rows if row['path'].startswith('proprietary/')]
    if not files:
        raise ValueError('nonempty vendor file contract required')
    expected = [member(row['path']) for row in files]
    if len(expected)!=len(set(expected)):
        raise ValueError('duplicate expected package destination')
    issues=[]
    with zipfile.ZipFile(package) as archive:
        names=archive.namelist()
        if len(names)!=len(set(names)):
            raise ValueError('duplicate target-files ZIP entry')
        for row,name in zip(files,expected):
            if name not in names:
                issues.append(name+': missing');continue
            info=archive.getinfo(name)
            if stat.S_IFMT(info.external_attr>>16)==stat.S_IFLNK:
                issues.append(name+': unexpected symlink');continue
            with archive.open(info) as stream:
                digest=hashlib.file_digest(stream,'sha256').hexdigest()
            if info.file_size!=row['bytes'] or digest!=row['sha256']:
                issues.append(name+': differs from prepared vendor bytes')
        if 'VENDOR/lib64/libtinyxml2-v34.so' not in names:
            issues.append('reviewed TinyXML v34 provider is missing')
    return {'vendor_package_pass':not issues,'vendor_files_checked':len(files),'issues':issues,
            'limits':'Exact prebuilt/configuration package bytes and required v34 presence only; no full ABI, service, boot or hardware acceptance.'}


def check_boot_startup(package, loader_sha256, dispatcher_sha256=None, write_helper_sha256=None):
    """Check normal module/RNG delivery and required subsystem boot actions."""
    issues=[]
    with zipfile.ZipFile(package) as archive:
        names=archive.namelist()
        if len(names)!=len(set(names)):
            raise ValueError('duplicate target-files ZIP entry')
        def regular(name):
            if name not in names:
                issues.append(name+': missing');return b''
            info=archive.getinfo(name)
            if stat.S_IFMT(info.external_attr>>16)==stat.S_IFLNK:
                issues.append(name+': unexpected symlink');return b''
            return archive.read(name)
        loader=regular('VENDOR/etc/init/hw/init.qti.kernel.rc')
        if hashlib.sha256(loader).hexdigest()!=loader_sha256:
            issues.append('vendor module-loader init differs from the source recipe')
        try:
            check_subsystem_boot_actions(loader.decode())
        except (ValueError,UnicodeError) as error:
            issues.append(str(error))
        helper=regular('VENDOR/bin/init.qti.write.sh')
        if write_helper_sha256 is not None and hashlib.sha256(helper).hexdigest()!=write_helper_sha256:
            issues.append('subsystem write helper differs from the same-run pinned source')
        caller=regular('VENDOR/etc/init/hw/init.target.rc')
        if b'import /vendor/etc/init/hw/init.qti.kernel.rc' not in caller:
            issues.append('vendor module-loader init is not imported')
        script=regular('VENDOR/bin/vendor_modprobe.sh')
        if b'setprop vendor.all.modules.ready 1' not in script:
            issues.append('vendor module-loader readiness publisher is absent')
        fsconfig=regular('META/vendor_filesystem_config.txt')
        modes=[line.split()[3] for line in fsconfig.decode().splitlines()
               if len(line.split())>=4 and line.split()[0]=='vendor/bin/vendor_modprobe.sh']
        if len(modes)!=1 or not int(modes[0],8)&0o111:
            issues.append('vendor module-loader script lacks executable filesystem configuration')
        helper_modes=[line.split()[3] for line in fsconfig.decode().splitlines()
                      if len(line.split())>=4 and line.split()[0]=='vendor/bin/init.qti.write.sh']
        if len(helper_modes)!=1 or not int(helper_modes[0],8)&0o111:
            issues.append('subsystem write helper lacks executable filesystem configuration')
        early=regular('VENDOR_BOOT/RAMDISK/lib/modules/modules.load')
        modules={line.strip().removesuffix(b'.ko') for line in early.splitlines()}
        if b'msm_rng' not in modules:
            issues.append('hardware RNG is absent from normal first-stage module loading')
        rng=regular('VENDOR_BOOT/RAMDISK/lib/modules/msm_rng.ko')
        if not rng.startswith(b'\x7fELF'):
            issues.append('packaged early hardware RNG is not an ELF module')
        if dispatcher_sha256 is not None:
            dispatcher=regular('VENDOR/bin/init.kernel.post_boot.sh')
            if hashlib.sha256(dispatcher).hexdigest()!=dispatcher_sha256:
                issues.append('post-boot dispatcher differs from the source recipe')
            for name in ('init.qti.kernel.sh','init.kernel.post_boot-taro.sh',
                         'init.kernel.post_boot-cape.sh','msm_irqbalance'):
                regular('VENDOR/bin/'+name)
            regular('VENDOR/etc/msm_irqbalance.conf')
    return {'boot_startup_pass':not issues,'issues':issues,
            'limits':'Actual init import, recipe-bound loader, early subsystem boot actions, executable helpers and early RNG delivery. Module initialization, DSP readiness, entropy and Android boot still need live acceptance.'}


def check_thermal_startup(package, script_sha256, config_sha256):
    """Catch service-name drift and loss of the selected daemon configuration."""
    issues=[]
    with zipfile.ZipFile(package) as archive:
        def read(name):
            if name not in archive.namelist():
                issues.append(name+': missing');return b''
            info=archive.getinfo(name)
            if stat.S_ISLNK(info.external_attr>>16):
                issues.append(name+': unexpected symlink');return b''
            return archive.read(name)
        data=read('VENDOR/etc/init/android.hardware.thermal-service.qti.rc')
        if hashlib.sha256(data).hexdigest()!=script_sha256:
            issues.append('thermal init differs from same-run source')
        text=data.decode(errors='replace')
        services=re.findall(r'^service\s+(\S+)\s+(\S+)',text,re.M)
        restarts=re.findall(r'^\s+restart\s+(\S+)\s*$',text,re.M)
        if len(services)!=1 or restarts!=[services[0][0]]:
            issues.append('thermal restart does not name its declared service')
        if services and services[0][1]!='/vendor/bin/hw/android.hardware.thermal-service.qti':
            issues.append('unexpected thermal executable')
        read('VENDOR/bin/hw/android.hardware.thermal-service.qti')
        config=read('VENDOR/etc/thermal-engine.conf')
        if hashlib.sha256(config).hexdigest()!=config_sha256:
            issues.append('thermal daemon default config differs from same-run source')
    return {'thermal_startup_pass':not issues,'issues':issues,
            'limits':'Exact selected init/configuration and restart target only; sensor response, limits and thermal control require runtime qualification.'}


def sensor_correction_issues(data):
    """Independently require both corrections in this exact OEM binary layout."""
    issues=[]
    if len(data)!=860144 or data[:6]!=b'\x7fELF\x02\x01' or data[18:20]!=b'\xb7\x00':
        return ['unqualified OEM sensor ELF layout']
    # pjgowtham e7432ff: remove the streaming branch for lux_aod. The exact
    # strcmp call and on-change fallthrough were checked against this revision.
    if data[0x61004:0x61014]!=bytes.fromhex('21581491e00315aa099901941f2003d5'):
        issues.append('lux_aod on-change request correction is missing')
    if (data[0xa6bdc:0xa6be4]!=bytes.fromhex('3f2303d508860014') or
            data[0xc8400:0xc841c]!=bytes.fromhex('282840b91f09027160000054ff8304d1f579ff17bf2303d5c0035fd6')):
        issues.append('OEM sensor error-event parser defense is missing')
    normalized=bytearray(data)
    normalized[0x308:0x318]=bytes(16)
    if data[0x308:0x318]!=hashlib.sha256(normalized).digest()[:16]:
        issues.append('OEM sensor combined diagnostic build identity is stale')
    return issues


def check_sensor_error_guard(package, expected_sha256):
    """Require same-run sensor bytes and both independently qualified fixes."""
    if not re.fullmatch('[0-9a-f]{64}', expected_sha256):
        raise ValueError('full same-run sensor source SHA-256 required')
    issues=[]
    with zipfile.ZipFile(package) as archive:
        names=archive.namelist()
        if len(names)!=len(set(names)):
            raise ValueError('duplicate target-files ZIP entry')
        if SENSOR_MEMBER not in names:
            issues.append('guarded OEM sensor library is missing')
        else:
            info=archive.getinfo(SENSOR_MEMBER)
            if stat.S_IFMT(info.external_attr>>16)==stat.S_IFLNK:
                issues.append('guarded OEM sensor library is a symlink')
            else:
                data=archive.read(info)
                if not info.file_size or hashlib.sha256(data).hexdigest()!=expected_sha256:
                    issues.append('OEM sensor library differs from the same-run guarded source')
                issues.extend(sensor_correction_issues(data))
    return {'sensor_error_guard_pass':not issues, 'issues':issues,
            'limits':'Same-run OEM sensor bytes, on-change request mode, parser guard and combined identity only. Runtime sensor data and hardware acceptance remain separate.'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target-files',type=Path,required=True)
    parser.add_argument('--candidate-inputs',type=Path,required=True)
    parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args()
    contract_path=REPO/'configs/lineage-24.0-vendor-output.json'
    contract=json.loads(contract_path.read_text())
    inputs=json.loads(args.candidate_inputs.read_text())
    if (inputs['vendor_inputs']['contract_sha256']!=sha(contract_path) or
            inputs['source_hashes']['tools/build/verify_vendor_24.py']!=sha(Path(__file__)) or
            inputs['source_hashes'].get('tools/build/kernel_layout_24.py')!=sha(Path(__file__).with_name('kernel_layout_24.py'))):
        raise ValueError('package gate differs from the same-run inputs')
    result=check(args.target_files,contract['files'])
    responsibility_tool=REPO/'tools/device_responsibilities24.py'
    if inputs['source_hashes'].get('tools/device_responsibilities24.py')!=sha(responsibility_tool):
        raise ValueError('device responsibility checker differs from same-run inputs')
    responsibilities=check_responsibilities(args.target_files)
    result['device_responsibilities']=responsibilities
    result['issues'].extend(responsibilities['issues'])
    result['vendor_package_pass']=result['vendor_package_pass'] and responsibilities['passed']
    loaders=[row for row in inputs['recipe_snapshot']['new_files']
             if row['path']=='device/realme/ferrari/init/init.ferrari.modules.rc']
    if len(loaders)!=1:
        raise ValueError('one same-run module-loader source required')
    dispatchers=[row for row in inputs['recipe_snapshot']['new_files']
                 if row['path']=='device/realme/ferrari/init/init.ferrari.post_boot.sh']
    if len(dispatchers)!=1:
        raise ValueError('one same-run post-boot dispatcher source required')
    startup=check_boot_startup(args.target_files,loaders[0]['canonical_sha256'],
                               dispatchers[0]['canonical_sha256'],
                               inputs['kernel_layout']['source_sha256'][SUBSYSTEM_WRITE_SOURCE])
    result['boot_startup']=startup
    result['issues'].extend(startup['issues'])
    result['vendor_package_pass']=result['vendor_package_pass'] and startup['boot_startup_pass']
    if (inputs.get('common_runtime',{}).get('contract_sha256')!=sha(COMMON_CONTRACT) or
            inputs['source_hashes'].get('tools/build/common_runtime_24.py')!=sha(Path(__file__).with_name('common_runtime_24.py'))):
        raise ValueError('common runtime checker/contract differs from same-run inputs')
    runtime=check_common(args.target_files,json.loads(COMMON_CONTRACT.read_text()))
    result['common_runtime']=runtime
    result['issues'].extend(runtime['issues'])
    result['vendor_package_pass']=result['vendor_package_pass'] and runtime['common_runtime_pass']
    thermal_scripts=[row for row in inputs['recipe_snapshot']['files']
                     if row['path']=='hardware/qcom-caf/thermal/android.hardware.thermal-service.qti.rc']
    thermal_configs=[row for row in inputs['recipe_snapshot']['new_files']
                     if row['path']=='device/realme/ferrari/configs/thermal/thermal-engine.conf']
    if len(thermal_scripts)!=1 or len(thermal_configs)!=1:
        raise ValueError('same-run thermal init and default configuration source required')
    thermal=check_thermal_startup(args.target_files,thermal_scripts[0]['canonical_sha256'],
                                  thermal_configs[0]['canonical_sha256'])
    result['thermal_startup']=thermal
    result['issues'].extend(thermal['issues'])
    result['vendor_package_pass']=result['vendor_package_pass'] and thermal['thermal_startup_pass']
    sensors=[row for row in inputs['recipe_snapshot']['files'] if row['path']==SENSOR_SOURCE]
    if len(sensors)!=1:
        raise ValueError('one same-run guarded sensor source required')
    sensor=check_sensor_error_guard(args.target_files,sensors[0]['canonical_sha256'])
    result['sensor_error_guard']=sensor
    result['issues'].extend(sensor['issues'])
    result['vendor_package_pass']=result['vendor_package_pass'] and sensor['sensor_error_guard_pass']
    result.update(contract_sha256=sha(contract_path),target_files_sha256=sha(args.target_files),
                  candidate_inputs_sha256=sha(args.candidate_inputs),tool_sha256=sha(Path(__file__)))
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))
    return 0 if result['vendor_package_pass'] else 1


if __name__=='__main__':
    raise SystemExit(main())
