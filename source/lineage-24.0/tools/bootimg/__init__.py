"""Offline Android boot image analysis.

Public API:

    load(path)                 parse a boot image
    BootImage                  parsed structure with identity and patch markers
    iter_cpio(data)            walk a ramdisk archive
    detect_compression(blob)   name a container format
    decompress(blob, kind)     unpack it
"""

from .bootimage import (
    BOOT_MAGIC,
    BootImage,
    BootImageError,
    CpioEntry,
    Section,
    android_release_name,
    decompress,
    detect_compression,
    iter_cpio,
    load,
    sha256_file,
)
from . import lz4

__all__ = [
    "BOOT_MAGIC",
    "BootImage",
    "BootImageError",
    "CpioEntry",
    "Section",
    "android_release_name",
    "decompress",
    "detect_compression",
    "iter_cpio",
    "load",
    "lz4",
    "sha256_file",
]
