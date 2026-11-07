"""Decode a captured misc BCB/VAB message; never writes or contacts a device.

Layout: pinned bootable/recovery/bootloader_message/include/bootloader_message/
bootloader_message.h and hardware/interfaces/boot/1.1/types.hal.
"""
import argparse
import json
from pathlib import Path
import struct


def decode(data):
    if len(data)<32768+64: raise ValueError('capture too short for the VAB message')
    version,magic,status,slot=struct.unpack_from('<BIBB',data,32768)
    if version!=2 or magic!=0x56740AB0: raise ValueError('unsupported/invalid VAB header')
    if status not in range(5) or slot not in (0,1): raise ValueError('unrecognized merge/slot value')
    command=data[:32].split(b'\0')[0].decode('ascii',errors='strict')
    recovery=data[64:832].split(b'\0')[0].decode('ascii',errors='strict')
    return dict(command=command,recovery=recovery,vab_version=version,source_slot=slot,
                merge_status=['NONE','UNKNOWN','SNAPSHOTTED','MERGING','CANCELLED'][status],
                scope='captured misc only; not a live bootloader query or approval to write')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('image',type=Path)
    args=p.parse_args();print(json.dumps(decode(args.image.read_bytes()),indent=2))
