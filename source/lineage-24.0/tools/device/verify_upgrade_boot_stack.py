"""Read-only recovery verification of exact image prefixes and full partitions.

Use the seven actual packaged images from the reviewed handoff. Short vbmeta
images are compared over their image length; full partition hashes are separate.
No write, mode transition, root request or slot change is implemented.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import threading

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from device.backup_upgrade_state import BOOT_STACK


def measure_exact(stream, expected):
    if type(expected) is not int or expected <= 0:
        raise ValueError('positive exact image size required')
    digest=hashlib.sha256()
    count=0
    for data in iter(lambda:stream.read(1024*1024),b''):
        count+=len(data)
        if count>expected:
            raise ValueError('readback contains extra bytes')
        digest.update(data)
    if count!=expected:
        raise ValueError('readback is shorter than packaged image')
    return digest.hexdigest()


def run(args):
    if not re.fullmatch('[A-Za-z0-9]+',args.serial) or not re.fullmatch('[A-Za-z0-9._-]+',args.build):
        raise ValueError('explicit safe serial/build required')
    if args.report.exists():raise ValueError('new private report required')
    record=dict(observed_utc=datetime.now(timezone.utc).isoformat(),complete=False,
        serial=args.serial,recovery_build=args.build,recovery_slot=args.recovery_slot,
        target_slot=args.target_slot,tool_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        commands=[],images=[],limits='Read-only physical image-prefix and whole-partition hashes. This is not boot, dynamic-system, firmware or userdata acceptance.')
    def read(command):
        p=subprocess.run([str(args.adb),'-s',args.serial,'shell',command],capture_output=True,text=True,timeout=300)
        record['commands'].append(dict(command=command,exit_code=p.returncode,stdout=p.stdout.strip(),stderr=p.stderr.strip()))
        if p.returncode:raise ValueError('read-only recovery command failed')
        return p.stdout.strip()
    def state():
        identity={'getprop ro.product.model':'RMX3301','getprop ro.product.device':'RED8ACL1',
            'getprop ro.boot.prjname':'21631','getprop ro.build.version.incremental':args.build,
            'getprop ro.boot.slot_suffix':'_'+args.recovery_slot,'getprop ro.boot.vbmeta.device_state':'unlocked'}
        if any(read(k)!=v for k,v in identity.items()) or 'uid=0(root)' not in read('id'):
            raise ValueError('recovery device/build/slot/root identity changed')
        if not read('pidof recovery'):
            raise ValueError('recovery required')
        p=subprocess.run([str(args.adb),'-s',args.serial,'shell','pidof update_engine_sideload'],capture_output=True,text=True,timeout=30)
        if p.returncode not in (0,1) or p.stdout.strip():raise ValueError('installer is active or its state is unknown')
        boot=read('cat /proc/sys/kernel/random/boot_id')
        if record.get('boot_id',boot)!=boot:raise ValueError('recovery rebooted during readback')
        record['boot_id']=boot
    try:
        state()
        for part in BOOT_STACK:
            image=args.images/(part+'.img')
            if image.is_symlink() or not image.is_file():raise ValueError('regular packaged image required')
            size=image.stat().st_size
            if size<=0:raise ValueError('empty packaged image')
            with image.open('rb') as stream:expected=measure_exact(stream,size)
            source='/dev/block/by-name/'+part+'_'+args.target_slot
            resolved=read('readlink -f '+source)
            if not re.fullmatch(r'/dev/block/(sd[a-z]\d+|mmcblk\d+p\d+)',resolved):raise ValueError('unexpected physical source')
            physical_size=int(read('blockdev --getsize64 '+source))
            if size>physical_size:raise ValueError('packaged image exceeds partition')
            before=read('sha256sum '+source).split()[0]
            if not re.fullmatch('[a-f0-9]{64}',before):raise ValueError('invalid physical digest')
            command='head -c '+str(size)+' '+source
            p=subprocess.Popen([str(args.adb),'-s',args.serial,'exec-out',command],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            watchdog=threading.Timer(300,p.kill);watchdog.start()
            try:
                actual=measure_exact(p.stdout,size)
                error=p.stderr.read().decode(errors='replace')
                if p.wait()!=0 or error.strip():raise ValueError('binary readback transport failed')
            finally:
                watchdog.cancel();p.stdout.close();p.stderr.close()
                if p.poll() is None:p.kill();p.wait()
            after=read('sha256sum '+source).split()[0]
            if actual!=expected or before!=after:raise ValueError('image prefix mismatch or changing source')
            record['images'].append(dict(partition=part+'_'+args.target_slot,image_bytes=size,image_sha256=expected,
                prefix_sha256=actual,physical_bytes=physical_size,physical_sha256=after,resolved_source=resolved,match=True))
            print(json.dumps(dict(partition=part+'_'+args.target_slot,prefix_match=True,image_bytes=size,physical_bytes=physical_size)),flush=True)
        state()
        record.update(complete=True,finished_utc=datetime.now(timezone.utc).isoformat())
    finally:
        args.report.parent.mkdir(parents=True,exist_ok=True)
        with args.report.open('x',encoding='utf-8') as output:json.dump(record,output,indent=2)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--adb',type=Path,required=True);p.add_argument('--serial',required=True)
    p.add_argument('--build',required=True);p.add_argument('--recovery-slot',choices=('a','b'),required=True)
    p.add_argument('--target-slot',choices=('a','b'),required=True)
    p.add_argument('--images',type=Path,required=True);p.add_argument('--report',type=Path,required=True)
    run(p.parse_args())


if __name__=='__main__':main()
