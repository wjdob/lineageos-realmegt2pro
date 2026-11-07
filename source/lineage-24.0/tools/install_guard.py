"""Constrain fastboot commands to OS installation; never changes device state itself.

Call this before every fastboot invocation in an installation runner. Raw ADB/block
writes are not an alternative to this guard and are outside the current firmware hold.
"""
from firmware_policy import OS_PARTITIONS


def validate_recovery_ab_ota_mappings(names):
    """Require this device's fresh, unmapped recovery profile before a VAB OTA.

    Unmounted filesystems can still have live device-mapper mappings. Standalone
    add-on ZIPs use a separate path and are not subject to this A/B OTA gate.
    This checks observed names only; it neither unmaps devices nor resets
    recovery's internal mapping flags. A fresh recovery session is also required.
    """
    if not isinstance(names, (list, tuple)) or any(not isinstance(n, str) or not n for n in names):
        raise ValueError('explicit observed recovery mapper names required')
    if names:
        raise ValueError('logical partitions remain mapped; restart recovery before A/B OTA')


def validate_fastboot(args, *, permitted_writes=(), allow_super_restore=False,
                      allow_slot_change=False):
    args = list(args)
    if not args or any(not isinstance(value, str) or not value for value in args):
        raise ValueError('nonempty explicit fastboot arguments required')
    if any(value.startswith('-') or any(c in value for c in ('\0','\r','\n')) for value in args):
        raise ValueError('flags and control characters are prohibited')
    verb = args[0]
    if verb == 'getvar' and len(args) == 2:
        return
    if verb in ('reboot', 'reboot-bootloader') and len(args) == 1:
        return
    if verb == 'reboot' and len(args) == 2 and args[1] in ('bootloader','recovery','fastboot'):
        return
    if verb == 'set_active' and len(args) == 2 and args[1] in ('a','b'):
        if allow_slot_change:
            return
        raise ValueError('manual slot change requires the reviewed return scope')
    if verb == 'flash' and len(args) == 3:
        target = args[1]
        if target == 'super':
            if allow_super_restore and target in set(permitted_writes):
                return
            raise ValueError('super write requires the reviewed stock-return scope')
        if target.endswith(('_a','_b')) and target[:-2] in OS_PARTITIONS:
            if target in set(permitted_writes):
                return
            raise ValueError('OS partition is not in this operation write set')
        raise ValueError('firmware, bootloader or unlock-state partition write prohibited')
    # Fail closed: no oem/flashing lock/unlock, erase, update ZIP, flashall,
    # unknown flags, automatic wipe, raw/alias command or snapshot mutation.
    raise ValueError('fastboot command outside reviewed OS-only scope')
