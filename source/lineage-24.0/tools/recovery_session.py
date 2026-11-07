"""Run a narrow operation on an exact, separately reviewed engineering recovery.

This tool never flashes recovery or changes slots. A package installation needs
the owner's reviewed device/backup/return plan in addition to these identity checks.
"""
from pathlib import Path
import argparse,hashlib,json,re,subprocess,time

OPERATIONS=('status','mount-system-ro','unmount-system','sideload-addon','sideload-ota')
REMOTE='/tmp/realme-recovery-control'

def digest(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def checked_hash(value):
    if not re.fullmatch('[0-9a-f]{64}',value):raise ValueError('full SHA-256 required')
    return value

def validate_devices(text,serial,expected='recovery'):
    rows=[line.split()[:2] for line in text.splitlines() if line and not line.startswith('List of devices')]
    if rows!=[[serial,expected]]:raise ValueError('one exact device in expected transport state required')

def perform(adb,serial,slot,recovery_sha,helper,helper_sha,operation,package=None,package_sha=None,mapper=None,mapper_sha=None,journal=None):
    if not re.fullmatch('[A-Za-z0-9._-]+',serial) or slot not in ('a','b') or operation not in OPERATIONS:
        raise ValueError('invalid device, slot or operation')
    checked_hash(recovery_sha);checked_hash(helper_sha)
    if digest(helper)!=helper_sha:raise ValueError('control helper hash mismatch')
    if operation=='mount-system-ro':
        if not mapper or not mapper_sha or digest(mapper)!=checked_hash(mapper_sha):
            raise ValueError('exact mapper and hash required for mount')
    if package is not None:
        if not operation.startswith('sideload-') or not package_sha or digest(package)!=checked_hash(package_sha):
            raise ValueError('exact package and hash required for installation')
    elif package_sha:raise ValueError('package hash without package')
    commands=[]
    def run(args,timeout=30,transition=False):
        result=subprocess.run([str(adb),*args],capture_output=True,text=True,timeout=timeout)
        commands.append({'arguments':args,'exit_code':result.returncode,'stdout':result.stdout,'stderr':result.stderr})
        if journal:journal({'state':'in-progress; acceptance pending','commands':commands})
        if result.returncode:
            detail=result.stdout+'\n'+result.stderr
            # A successful socket request can stop adbd before its shell exit
            # status reaches the host. Accept only this bounded transport race,
            # followed below by exact-serial sideload-state confirmation.
            disconnect=re.search(r'closed|disconnected|device .*not found|no devices/emulators',detail,re.I)
            if not transition or 'recovery control refused:' in detail or not disconnect:
                raise RuntimeError('ADB operation failed: '+str(args[:3]))
        return result.stdout.strip()
    def shell(*args):return run(['-s',serial,'shell',*args])
    validate_devices(run(['devices']),serial)
    expected={'ro.bootmode':'recovery','ro.product.model':'RMX3301','ro.build.version.sdk':'37',
              'ro.lineage.recovery.engineering':'1','ro.adb.secure':'1','ro.adb.secure.recovery':'1',
              'ro.boot.slot_suffix':'_'+slot,'ro.boot.vbmeta.device_state':'unlocked'}
    for key,value in expected.items():
        if shell('getprop',key)!=value:raise ValueError('recovery property mismatch: '+key)
    if shell('id','-u')!='0':raise ValueError('root recovery shell required')
    def remote_hash(path,expected):
        row=shell('sha256sum',path).split()
        if len(row)!=2 or row[0]!=expected or row[1]!=path:raise ValueError('remote hash mismatch: '+path)
    remote_hash('/dev/block/by-name/recovery_'+slot,recovery_sha)
    run(['-s',serial,'push',str(helper),REMOTE]);remote_hash(REMOTE,helper_sha);shell('chmod','700',REMOTE)
    shell(REMOTE,'status')
    if mapper is not None and operation=='mount-system-ro':
        dest='/tmp/realme-prepare-logical'
        run(['-s',serial,'push',str(mapper),dest]);remote_hash(dest,mapper_sha)
        shell('chmod','700',dest);shell(dest,'--prepare-missing')
    result=run(['-s',serial,'shell',REMOTE,operation],transition=operation.startswith('sideload-'))
    if operation.startswith('sideload-'):
        deadline=time.monotonic()+30
        while True:
            devices=run(['devices'])
            try:validate_devices(devices,serial,'sideload');break
            except ValueError:
                if time.monotonic()>=deadline:raise RuntimeError('sideload transport did not appear; no package sent')
                time.sleep(1)
        if package is not None:
            run(['-s',serial,'sideload',str(package)],timeout=3600)
            result='transfer ended; installer result, recovery log and independent readback still required'
    return {'operation':operation,'serial':serial,'slot':slot,'recovery_sha256':recovery_sha,
            'helper_sha256':helper_sha,'package_sha256':package_sha,'result':result,'commands':commands,
            'limits':'Transport success is not installation/readback/boot acceptance. Signature prompts are preserved. No image flash, reboot, slot switch or erase operation is exposed.'}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('adb','helper','package','mapper','out'):p.add_argument('--'+name,type=Path,required=name in ('adb','helper','out'))
    for name in ('serial','slot','recovery-sha256','helper-sha256','package-sha256','mapper-sha256'):
        p.add_argument('--'+name,required=name in ('serial','slot','recovery-sha256','helper-sha256'))
    p.add_argument('--operation',choices=OPERATIONS,required=True)
    a=p.parse_args()
    if a.out.exists():raise ValueError('new result path required')
    a.out.parent.mkdir(parents=True,exist_ok=True)
    def journal(value):a.out.write_text(json.dumps(value,indent=2)+'\n')
    try:
        result=perform(a.adb,a.serial,a.slot,a.recovery_sha256,a.helper,a.helper_sha256,a.operation,a.package,a.package_sha256,a.mapper,a.mapper_sha256,journal)
    except Exception as error:
        prior=json.loads(a.out.read_text()) if a.out.exists() else {}
        journal(dict(prior,state='failed; installer and device state must be inspected',error=str(error)))
        raise
    journal(result)
    print(result['result'])

if __name__=='__main__':main()
