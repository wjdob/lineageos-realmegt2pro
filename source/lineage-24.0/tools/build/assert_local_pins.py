#!/usr/bin/env python3
"""Check every project in an explicitly pinned local manifest against Git HEAD.

Run from the build-tree root. This checks revisions only, not working-tree edits,
unlisted projects, build outputs, or device compatibility.
"""

import subprocess
import sys
from manifest import read_pins


def controlled(path):
    return {location: (name, revision) for (name, location), revision in read_pins(path).items()}


def main(argv):
    if len(argv) != 2:
        print('usage: assert_local_pins.py <lineage_local_manifest.xml>')
        return 2
    try:
        pins = controlled(argv[1])
    except (OSError, ValueError) as exc:
        print('::error::invalid manifest: %s' % exc)
        return 2
    print('controlled projects: %d' % len(pins))
    bad = 0
    for path, (name, want) in sorted(pins.items()):
        try:
            got = subprocess.run(['git', '-C', path, 'rev-parse', 'HEAD'],
                                 capture_output=True, text=True, check=True).stdout.strip()
        except Exception as exc:
            print('  MISSING  %-40s %s' % (path, exc))
            bad += 1
            continue
        if got != want:
            print('  DRIFT    %-40s pinned=%s actual=%s' % (path, want[:12], got[:12]))
            bad += 1
        else:
            print('  OK       %-40s %s' % (path, want[:12]))
    if bad:
        print('::error::%d controlled project(s) not at their pinned revision' % bad)
        return 1
    print('OK: all controlled projects match their pinned revisions')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
