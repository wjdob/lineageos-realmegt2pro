"""Exercise the actual HIDL death callback in an isolated host handler harness."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

SOURCE = 'frameworks/base/services/core/java/com/android/server/biometrics/sensors/fingerprint/hidl/HidlToAidlSensorAdapter.java'


def method_block(source):
    marker = 'public void serviceDied(long cookie)'
    if source.count(marker) != 1:
        raise ValueError('one reviewed serviceDied callback required')
    start = source.index(marker)
    opening = source.index('{', start)
    level = 1
    for index in range(opening+1, len(source)):
        level += (source[index] == '{') - (source[index] == '}')
        if level == 0:
            return source[start:index+1]
    raise ValueError('unterminated serviceDied callback')


HARNESS = '''
import java.util.ArrayDeque;
class UserHandle { static final int USER_NULL = -10000; }
class Slog { static void d(String tag, String text) {} }
class Handler {
    final ArrayDeque<Runnable> queue = new ArrayDeque<>();
    boolean dispatching;
    boolean post(Runnable task) { queue.add(task); return true; }
    void dispatchAll() {
        dispatching = true;
        try { while (!queue.isEmpty()) queue.remove().run(); }
        finally { dispatching = false; }
    }
}
class Sensor {
    Object activeClient;
    int deaths;
    void onBinderDied() {
        HidlToAidlSensorAdapter sensor = (HidlToAidlSensorAdapter) this;
        if (!sensor.handler.dispatching || sensor.mSession != null || sensor.mDaemon != null
                || sensor.mCurrentUserId != UserHandle.USER_NULL)
            throw new AssertionError("Parent cleanup received stale state or wrong thread");
        activeClient = null;
        deaths++;
    }
}
public class HidlToAidlSensorAdapter extends Sensor {
    static final String TAG = "host";
    final Handler handler = new Handler();
    Object mSession, mDaemon;
    int mCurrentUserId;
    Handler getHandler() { return handler; }
    CALLBACK
    public static void main(String[] ignored) {
        int cases = 0;
        for (int user : new int[] {0, 2, 10}) for (boolean active : new boolean[] {false, true}) {
            HidlToAidlSensorAdapter sensor = new HidlToAidlSensorAdapter();
            Object session = new Object(), daemon = new Object(), client = active ? new Object() : null;
            sensor.mSession = session; sensor.mDaemon = daemon;
            sensor.mCurrentUserId = user; sensor.activeClient = client;
            sensor.serviceDied(0);
            if (sensor.mSession != session || sensor.mDaemon != daemon || sensor.activeClient != client
                    || sensor.mCurrentUserId != user || sensor.deaths != 0 || sensor.handler.queue.size() != 1)
                throw new AssertionError("Binder thread changed handler-owned state or failed to queue");
            sensor.handler.dispatchAll();
            if (sensor.mSession != null || sensor.mDaemon != null || sensor.activeClient != null
                    || sensor.mCurrentUserId != UserHandle.USER_NULL || sensor.deaths != 1)
                throw new AssertionError("Death cleanup or same-user reinitialization missing");
            sensor.serviceDied(0); sensor.handler.dispatchAll();
            if (sensor.deaths != 2 || sensor.mCurrentUserId != UserHandle.USER_NULL)
                throw new AssertionError("Repeated death lost reset state");
            cases++;
        }
        System.out.println("cases=" + cases);
    }
}
'''


def check_source(path):
    source = Path(path).read_text()
    callback = method_block(source)
    javac, java = shutil.which('javac'), shutil.which('java')
    if not javac or not java:
        raise ValueError('host JDK required; recovery behavior check blocked')
    with tempfile.TemporaryDirectory(prefix='fingerprint-death-') as scratch:
        directory = Path(scratch)
        candidate = directory/'HidlToAidlSensorAdapter.java'
        candidate.write_text(HARNESS.replace('CALLBACK', callback))
        compiled = subprocess.run([javac, '--release', '8', '-d', scratch, str(candidate)],
                                  capture_output=True, text=True, timeout=30)
        if compiled.returncode:
            raise ValueError('recovery harness compilation failed: '+compiled.stderr)
        result = subprocess.run([java, '-cp', scratch, 'HidlToAidlSensorAdapter'],
                                capture_output=True, text=True, timeout=10)
        if result.returncode or result.stdout.strip() != 'cases=6':
            raise ValueError('recovery behavior failed: '+result.stderr)
    return {'cases_passed': 6, 'source_sha256': hashlib.sha256(Path(path).read_bytes()).hexdigest(),
            'callback_sha256': hashlib.sha256(callback.encode()).hexdigest(),
            'limits': 'Actual callback compiled against host state/handler/parent shims. Full Android class, Sensor implementation, native build, HAL restart and fingerprint UI remain separate checks.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    result = check_source(args.source)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result, indent=2))
