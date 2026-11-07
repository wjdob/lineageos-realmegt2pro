"""Run OEM transaction fixtures in a bounded private tmpfs under repository tmp.

Launch with unshare --mount --propagation private. Only the new transaction-test
fixture directory is mounted; no Android source, build cache or device is touched.
"""
from pathlib import Path
import os
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
scratch=ROOT/'tmp/oem-coinstall-transactions'
if os.readlink('/proc/self/ns/mnt') == os.readlink('/proc/1/ns/mnt'):
    raise SystemExit('Run in a private mount namespace')
scratch.mkdir(parents=True,exist_ok=True)
if scratch.is_symlink() or scratch.resolve() != ROOT.resolve()/'tmp/oem-coinstall-transactions':
    raise SystemExit('Unexpected test scratch path')
subprocess.run(['mount','-t','tmpfs','-o','size=128m,mode=0700,nodev,nosuid','tmpfs',str(scratch)],check=True)
try:
    result=subprocess.run([sys.executable,'-m','unittest',*(sys.argv[1:] or ['test_oem_coinstall_transactions','-v'])],
        cwd=ROOT,env={**os.environ,'PYTHONPATH':'tools:tools/tests'})
finally:
    subprocess.run(['umount',str(scratch)],check=True)
raise SystemExit(result.returncode)
