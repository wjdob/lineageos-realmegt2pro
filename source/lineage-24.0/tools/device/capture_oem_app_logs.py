"""Capture bounded, UID-filtered OEM app logs without starting or changing the app.

Run with build-WSL Python. Output must be a new directory under repository .local.
Plan-only verifies public package metadata/hash but starts no logger. Captures are
diagnostic evidence, never feature acceptance or installation authorization.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
PACKAGES = {'photos': 'com.coloros.gallery3d', 'camera': 'com.oplus.camera'}
LIMIT = 8 * 1024 * 1024


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def private_output(path, root=ROOT):
    if path.is_symlink():
        raise ValueError('output must not be a symlink')
    path = path.resolve()
    private = (root / '.local').resolve()
    if not private.is_relative_to(root.resolve()) or not path.is_relative_to(private) or path == private:
        raise ValueError('output must stay under repository .local')
    if path.exists():
        raise ValueError('output directory must be new')
    return path


def preflight(adb, serial, config, profile):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}', serial):
        raise ValueError('invalid serial')
    config = config.resolve()
    if not config.is_relative_to((ROOT / 'configs').resolve()):
        raise ValueError('use a repository configuration')
    data = json.loads(config.read_text())
    app = data['profiles'][profile]
    sdk = data.get('sdk')
    supported = {36: '23.2', 37: '24.0'}
    if (data.get('model') != 'RMX3301' or type(sdk) is not int
            or sdk not in supported or data.get('lineage') != supported[sdk]
            or app.get('package') != PACKAGES[profile]
            or not re.fullmatch('[a-f0-9]{64}', app.get('sha256', ''))):
        raise ValueError('unexpected profile/platform identity')
    command = [str(adb), '-s', serial]

    def shell(*args):
        result = subprocess.run(command + ['shell', *args], capture_output=True, timeout=45, check=True)
        return result.stdout.decode().strip()

    if shell('getprop', 'ro.product.model') != 'RMX3301':
        raise ValueError('unexpected device')
    if shell('getprop', 'ro.build.version.sdk') != str(sdk):
        raise ValueError('device SDK differs from the selected profile')
    user_text = shell('am', 'get-current-user')
    if not re.fullmatch(r'\d+', user_text):
        raise ValueError('unknown Android user')
    user = int(user_text)
    output = shell('pm', 'path', app['package']).splitlines()
    if len(output) != 1 or not output[0].startswith('package:'):
        raise ValueError('single installed APK required')
    apk = output[0][len('package:'):]
    if not re.fullmatch(r'/(?:system|product|data/app)/[A-Za-z0-9_+./=~%-]+\.apk', apk):
        raise ValueError('unexpected installed APK path')
    measured = shell('sha256sum', apk).split()[0]
    if measured != app['sha256']:
        raise ValueError('installed APK differs from the selected profile')
    package = shell('cmd', 'package', 'list', 'packages', '-U', '--user', str(user), app['package'])
    match = re.fullmatch(r'package:' + re.escape(app['package']) + r' uid:(\d+)', package)
    if not match:
        raise ValueError('unambiguous package UID required')
    uid = int(match[1])
    if uid // 100000 != user or uid % 100000 < 10000:
        raise ValueError('unexpected app UID/user')
    return command, {'package': app['package'], 'profile': profile, 'config': str(config.relative_to(ROOT)),
                     'config_sha256': digest(config), 'apk_path': apk, 'apk_sha256': measured,
                     'user': user, 'uid': uid, 'sdk': sdk, 'lineage': supported[sdk],
                     'build_incremental': shell('getprop', 'ro.build.version.incremental')}


def capture(command, output, seconds, limit=LIMIT):
    if not math.isfinite(seconds) or not 0 < seconds <= 120 or limit <= 0:
        raise ValueError('invalid capture bounds')
    process = None
    start = time.monotonic()
    reason = None
    stdout = output / 'app-logcat.txt'
    stderr = output / 'app-logcat.stderr'
    with stdout.open('xb') as out, stderr.open('xb') as error:
        try:
            process = subprocess.Popen(command, stdout=out, stderr=error)
            while True:
                remaining = seconds - (time.monotonic() - start)
                if remaining <= 0:
                    reason = 'duration'; break
                if stdout.stat().st_size + stderr.stat().st_size >= limit:
                    reason = 'size-threshold'; break
                try:
                    process.wait(timeout=min(0.25, remaining))
                    reason = 'process-exit'; break
                except subprocess.TimeoutExpired:
                    pass
        finally:
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait(timeout=3)
    return {'stop_reason': reason, 'exit_code': process.returncode,
            'elapsed_seconds': time.monotonic() - start,
            'artifacts': [{'file': path.name, 'bytes': path.stat().st_size, 'sha256': digest(path)}
                          for path in [stdout, stderr]],
            'nonempty_log': stdout.stat().st_size > 0,
            'limits': 'UID-filtered app buffers only; vendor/system emitters may be omitted. '
                      'One initial tail line may predate capture. Size stop is checked every250ms '
                      'and may overshoot by one interval. Nonempty output is not feature success.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--adb', type=Path, required=True)
    parser.add_argument('--serial', required=True)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--profile', choices=PACKAGES, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seconds', type=float, default=60)
    parser.add_argument('--plan-only', action='store_true')
    args = parser.parse_args()
    if not math.isfinite(args.seconds) or not 0 < args.seconds <= 120:
        raise ValueError('capture duration must be positive and at most120seconds')
    output = private_output(args.output)
    command, identity = preflight(args.adb, args.serial, args.config, args.profile)
    logcat = command + ['logcat', '-b', 'main', '-b', 'system', '-b', 'crash', '-v', 'threadtime',
                        '--uid=' + str(identity['uid']), '-T', '1']
    output.mkdir(parents=True, mode=0o700)
    report = {'started_utc': datetime.now(timezone.utc).isoformat(), 'identity': identity,
              'tool_sha256': digest(Path(__file__)), 'python': sys.version,
              'state': 'plan-only' if args.plan_only else 'capturing',
              'seconds_requested': args.seconds, 'logcat_command': logcat,
              'scope': 'Read-only public APK/UID verification and app-scoped logcat. No app start, '
                       'root request, reboot, log clear, property/grant, private-file or media operation.'}
    record = output / 'report.json'
    record.write_text(json.dumps(report, indent=2)+'\n')
    try:
        if not args.plan_only:
            report['capture'] = capture(logcat, output, args.seconds)
            report['state'] = 'captured-bounded' if report['capture']['stop_reason'] in ('duration', 'size-threshold') else 'stream-ended'
    except Exception as error:
        report['state'] = 'failed'; report['error'] = type(error).__name__ + ': ' + str(error)
        raise
    finally:
        report['finished_utc'] = datetime.now(timezone.utc).isoformat()
        record.write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps({'state': report['state'], 'output': str(output)}))
    return 0 if args.plan_only or report['state'] == 'captured-bounded' else 1


if __name__ == '__main__':
    raise SystemExit(main())
