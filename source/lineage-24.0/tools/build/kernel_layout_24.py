"""Check the proven Ferrari 5.10/HIDL cohort before first Android17 builds."""
import hashlib
from pathlib import Path
import re
import shlex
import xml.etree.ElementTree as ET


SUBSYSTEM_BOOT_NODES = ('/sys/kernel/boot_adsp/boot', '/sys/kernel/boot_cdsp/boot',
                        '/sys/devices/virtual/cvp/cvp/boot')
SUBSYSTEM_WRITE_SOURCE = 'vendor/oneplus/sm8450-common/proprietary/vendor/bin/init.qti.write.sh'


def check_subsystem_boot_actions(text):
    """Require normal subsystem boot actions before framework startup completes."""
    commands=[]
    section=None
    for line in text.splitlines():
        tokens=shlex.split(line,comments=True)
        if not tokens:continue
        if not line[0].isspace():
            section=tokens
        else:
            commands.append((section,tokens))
    for node in SUBSYSTEM_BOOT_NODES:
        expected=['exec_background','u:r:vendor_qti_init_shell_bg:s0','--',
                  '/vendor/bin/init.qti.write.sh',node,'1']
        matching=[(section,tokens) for section,tokens in commands if node in tokens]
        if matching!=[(['on','early-boot'],expected)]:
            raise ValueError('missing/ambiguous early-boot subsystem start: '+node)
    return list(SUBSYSTEM_BOOT_NODES)


def assignments(text):
    result={}
    for line in text.replace('\\\n',' ').splitlines():
        line=line.split('#',1)[0]
        match=re.fullmatch(r'\s*([A-Z0-9_]+)\s*:?=\s*(.*?)\s*',line)
        if match:result[match[1]]=match[2]
    return result


def check(tree,recipe_view=None):
    tree=Path(tree)
    files={}
    def source(relative):
        path=Path(recipe_view)/relative if recipe_view is not None else tree/relative
        if not path.is_file():path=tree/relative
        if not path.is_file():raise ValueError('missing kernel input: '+relative)
        data=path.read_bytes();files[relative]=hashlib.sha256(data).hexdigest()
        return data.decode()
    device=source('device/realme/ferrari/BoardConfig.mk')
    include='include device/oneplus/sm8450-common/BoardConfigCommon.mk'
    selection='TARGET_KERNEL_VERSION := 5.10'
    if (device.count(selection)!=1 or include not in device or
            device.index(selection)>device.index(include) or
            assignments(device).get('TARGET_USES_KERNEL_6_6') not in (None,'false')):
        raise ValueError('Ferrari must select kernel5.10 before the common BoardConfig')
    common=source('device/oneplus/sm8450-common/BoardConfigCommon.mk')
    start='else\nTARGET_KERNEL_SOURCE := kernel/oneplus/sm8450\n'
    if common.count(start)!=1:raise ValueError('legacy kernel branch is absent or ambiguous')
    legacy=common.split(start,1)[1].split('\nendif',1)[0]
    config=assignments('TARGET_KERNEL_SOURCE := kernel/oneplus/sm8450\n'+legacy)
    kernel=config.get('TARGET_KERNEL_SOURCE')
    modules=config.get('TARGET_KERNEL_EXT_MODULE_ROOT')
    if kernel!='kernel/oneplus/sm8450' or modules!='kernel/oneplus/sm8450-modules':
        raise ValueError('kernel5.10 source paths differ from the pinned manifest')
    version=assignments(source(kernel+'/Makefile'))
    if (version.get('VERSION'),version.get('PATCHLEVEL'),version.get('SUBLEVEL'))!=('5','10','246'):
        raise ValueError('selected kernel source is not5.10.246')
    manifest=ET.fromstring(source('device/oneplus/sm8450-common/vintf/manifest.xml'))
    if manifest.get('target-level')!='7':raise ValueError('reviewed kernel5.10 requires device FCM7')
    matrices=source('hardware/interfaces/compatibility_matrices/Android.bp')
    support=re.search(r'name:\s*"framework_compatibility_matrix\.7\.xml".*?kernel_configs:\s*\[(.*?)\]',matrices,re.S)
    if not support or '"kernel_config_t_5.10"' not in support[1]:
        raise ValueError('Android17 FCM7 lacks the selected5.10 kernel configuration')
    for name in config.get('TARGET_KERNEL_CONFIG','').split():source(kernel+'/arch/arm64/configs/'+name)
    compiler_version=assignments(device).get('TARGET_KERNEL_CLANG_VERSION')
    if compiler_version!='r563880c':raise ValueError('kernel must use the accepted23b compiler r563880c')
    compiler='prebuilts/clang/host/linux-x86/clang-'+compiler_version+'/bin/clang'
    if not (tree/compiler).is_file():raise ValueError('selected kernel compiler is absent')
    entries=config.get('TARGET_KERNEL_EXT_MODULES','').split()
    if len(entries)!=len(set(entries)) or not entries:raise ValueError('duplicate/empty external module selection')
    directories=[]
    for entry in entries:
        parts=entry.split(':')
        if len(parts)>2 or len(parts)==2 and parts[1]!='kbuild':raise ValueError('unknown external module mode')
        relative=parts[0]
        if relative.startswith('/') or '..' in Path(relative).parts:raise ValueError('escaped module path')
        source(modules+'/'+relative+'/Makefile')
        directories.append((tree/modules/relative).resolve())
    display=(tree/modules/'qcom/opensource/display-drivers/msm').resolve()
    if display not in directories:raise ValueError('display module is not selected')
    display_make=source(modules+'/qcom/opensource/display-drivers/msm/Makefile')
    dependencies=[]
    for relative in re.findall(r'\$\(OUT_DIR\)/\.\./sm8450-modules/([^\s]+?)/Module\.symvers',display_make):
        dependency=(tree/modules/relative).resolve()
        if dependency not in directories or directories.index(dependency)>=directories.index(display):
            raise ValueError('display symbol provider must be selected earlier: '+str(dependency))
        dependencies.append(str(dependency.relative_to(tree)))
    if not dependencies:raise ValueError('display symbol-provider declaration missing')
    dts=tree/kernel/'arch/arm64/boot/dts/vendor'
    if dts.resolve()!=(tree/'kernel/oneplus/sm8450-devicetrees').resolve():
        raise ValueError('kernel vendor DTS link differs from the pinned project')
    board=assignments(device)
    if board.get('TARGET_MERGE_DTBS_WILDCARD')!='waipio*' or board.get('TARGET_MERGE_DTBOS_WILDCARD')!='ferrari-21631-waipio-overlay':
        raise ValueError('Ferrari base/combined-overlay selection differs')
    overlay=source('kernel/oneplus/sm8450-devicetrees/oplus/ferrari-21631-waipio-overlay.dts')
    for token in ('#include "../qcom/waipio-mtp.dtsi"', '#include "ferrari_21631_overlay_common.dtsi"', 'oplus,project-id = <21631', '&qseecom_ta_mem', '0x02000000'):
        if token not in overlay:raise ValueError('combined Ferrari overlay missing '+token)
    source('kernel/oneplus/sm8450-devicetrees/oplus/ferrari_21631_overlay_common.dtsi')
    for name in ('modules.load','modules.load.vendor_boot','modules.load.recovery'):
        source('device/oneplus/sm8450-common/'+name)
    early=source('device/oneplus/sm8450-common/modules.load.vendor_boot').splitlines()
    if 'msm_rng.ko' not in early:
        raise ValueError('hardware RNG must load before the early prng_seeder')
    loader=source('device/realme/ferrari/init/init.ferrari.modules.rc')
    for token in ('on early-init\n    start vendor.modprobe',
                  'on init\n    wait_for_prop vendor.all.modules.ready 1',
                  'service vendor.modprobe /vendor/bin/vendor_modprobe.sh',
                  'seclabel u:r:vendor_modprobe:s0'):
        if token not in loader:
            raise ValueError('missing vendor module-loader startup contract: '+token)
    subsystem_nodes=check_subsystem_boot_actions(loader)
    source(SUBSYSTEM_WRITE_SOURCE)
    packaging=source('device/realme/ferrari/device.mk')
    mapping='$(LOCAL_PATH)/init/init.ferrari.modules.rc:$(TARGET_COPY_OUT_VENDOR)/etc/init/hw/init.qti.kernel.rc'
    if mapping not in packaging:
        raise ValueError('vendor module-loader init import target is not packaged')
    return {'ok':True,'kernel':kernel,'version':'.'.join(version[k] for k in ('VERSION','PATCHLEVEL','SUBLEVEL')),
            'compiler':compiler,'external_modules':len(entries),'display_symbol_providers':dependencies,
            'source_sha256':files,
            'device_fcm':'7','audio_transport':'HIDL',
            'early_boot_subsystems':subsystem_nodes,
            'limits':'Literal pinned5.10/FCM7 source/config/path and display-provider order checks. Actual Make/Soong evaluation, compilation, module symbols, built DTBs and Android17 physical boot remain separate.'}
