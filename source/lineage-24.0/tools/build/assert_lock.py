#!/usr/bin/env python3
"""Assert the synced tree matches the committed manifest lock (M3/D33).

Changed 2026-10-20 after review found the first version keyed on `name` alone.
Fourteen project names are reused across 48 additional paths with different
revisions - eleven display projects among them - so name-keyed comparison
collapsed 1,138 entries to 1,090 keys and let duplicates escape detection.

Now keyed on (name, path). Extras are rejected as well as missing/moved.
"""

import sys
from manifest import read_pins


def locked(path):
    return read_pins(path)


def main(argv):
    if len(argv) != 3:
        print('usage: assert_lock.py <locked.xml> <actual.xml>')
        return 2
    try:
        want, got = locked(argv[1]), locked(argv[2])
    except (OSError, ValueError) as exc:
        print('::error::invalid manifest: %s' % exc)
        return 2
    print('locked (name,path) entries: %d   actual: %d' % (len(want), len(got)))
    if not want:
        print('::error::the lock contains no pinned entries')
        return 1
    missing = sorted(k for k in want if k not in got)
    moved = sorted(k for k in want if k in got and got[k] != want[k])
    extra = sorted(k for k in got if k not in want)
    for k in missing[:10]:
        print('  MISSING %s @ %s' % k)
    for k in moved[:10]:
        print('  MOVED   %s @ %s  pinned=%s actual=%s' % (k[0], k[1], want[k][:12], got[k][:12]))
    for k in extra[:10]:
        print('  EXTRA   %s @ %s' % k)
    if missing or moved or extra:
        print('::error::tree differs from lock: %d missing, %d moved, %d extra'
              % (len(missing), len(moved), len(extra)))
        return 1
    print('OK: every locked (name, path) revision matches and no extras exist')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
