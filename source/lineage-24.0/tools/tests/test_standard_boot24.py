"""Exercise identity/phase/readback failures; simulated ADB is not device evidence."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import standard_boot24 as observer

BASE = '00000000-0000-0000-0000-000000000001'
FIRST = '00000000-0000-0000-0000-000000000002'
SECOND = '00000000-0000-0000-0000-000000000003'


class StandardBootTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.scope = patch.object(observer, 'ROOT', self.root)
        self.scope.start()
        self.addCleanup(self.scope.stop)
        self.local = self.root/'.local'
        self.local.mkdir()
        self.config = dict(schema=1, kind=observer.KIND, serial='example-serial',
            source=dict(build='source', slot='_a', sensor_sha256='1'*64),
            target=dict(build='target', slot='_b', sensor_sha256='2'*64,
                        boot_sha256='3'*64, boot_bytes=100),
            evidence=dict(handoff_sha256='4'*64, target_files_sha256='5'*64,
                          run='candidate-24-native-22', source_commit='6'*40))
        self.path = self.local/'expect.json'
        self.save_config()
        self.calls = []

    def save_config(self):
        self.path.write_text(json.dumps(self.config))

    def runner(self, boot, target=False, overrides=None, uid=0):
        expected = self.config['target' if target else 'source']
        responses = {observer.IDENTITY['boot_id']: boot,
                     observer.IDENTITY['build']: expected['build'],
                     observer.IDENTITY['sdk']: '37', observer.IDENTITY['slot']: expected['slot'],
                     observer.IDENTITY['unlocked']: 'unlocked',
                     'getprop sys.boot_completed': '1', 'getenforce': 'Enforcing',
                     'getprop sys.user.0.ce_available': 'true', 'id': 'uid=0(root)' if uid == 0 else 'uid=2000(shell)',
                     'sha256sum /vendor/lib64/sensors.ssc.so': expected['sensor_sha256']+'  /vendor/lib64/sensors.ssc.so',
                     'cat /proc/self/mountinfo': '1 2 0:1 / / ro - rootfs rootfs ro',
                     'sha256sum /dev/block/by-name/boot_b': '3'*64+'  /dev/block/by-name/boot_b',
                     'logcat -d -b crash -v epoch -t 200': ''}
        responses.update(overrides or {})
        def run(args, **kwargs):
            self.assertEqual(args[:4], ['fake-adb', '-s', 'example-serial', 'shell'])
            self.assertGreater(kwargs['timeout'], 0)
            self.assertLessEqual(kwargs['timeout'], 8)
            command = args[4]
            self.calls.append(command)
            value = responses.get(command)
            if value is None:
                value = '' if command.startswith(('getprop init.svc_debug_pid.', 'for p in ')) else 'running' if command.startswith('getprop init.svc.') else 'captured evidence'
            if isinstance(value, BaseException):
                raise value
            if isinstance(value, tuple):
                return SimpleNamespace(returncode=value[0], stdout=value[1], stderr=value[2])
            return SimpleNamespace(returncode=0, stdout=value, stderr='')
        return run

    def capture(self, label, phase='baseline', boot=BASE, prior=None, overrides=None, uid=0):
        output = self.local/label
        result = observer.capture(self.path, observer.sha(self.path), phase, output, 'fake-adb',
                                  prior, observer.sha(prior) if prior else None,
                                  runner=self.runner(boot, phase != 'baseline', overrides, uid))
        return result, output/'capture.json'

    def chain(self):
        baseline, path = self.capture('baseline')
        first, receipt = self.capture('first', 'first-standard', FIRST, path)
        self.assertTrue(baseline['automatic_checks_pass'])
        self.assertTrue(first['automatic_checks_pass'])
        return receipt

    def test_fresh_baseline_first_and_second_link_distinct_kernel_boots(self):
        first = self.chain()
        result, _ = self.capture('second', 'second-standard', SECOND, first)
        self.assertTrue(result['automatic_checks_pass'])
        self.assertEqual(result['baseline_boot_id'], BASE)
        self.assertEqual(result['prior_receipt_sha256'], observer.sha(first))
        self.assertEqual(result['manual_uat'], 'pending')

    def test_nonroot_capture_preserves_other_results_and_blocks_image_proof(self):
        _, baseline = self.capture('baseline')
        result, _ = self.capture('shell', 'first-standard', FIRST, baseline, uid=2000,
            overrides={'sha256sum /dev/block/by-name/boot_b': (1, '', 'Permission denied')})
        self.assertTrue(result['capture_complete'])
        self.assertFalse(result['root_observed'])
        self.assertEqual(result['checks']['boot_completed']['status'], 'pass')
        self.assertIn('standard_packaged_boot', result['blocked_checks'])
        self.assertFalse(result['automatic_checks_pass'])

    def test_failed_crash_read_cannot_establish_absence_of_fatals(self):
        result, _ = self.capture('denied-crash', overrides={
            'logcat -d -b crash -v epoch -t 200': 'Permission Denial: logcat'})
        self.assertIn('capture_crash', result['blocked_checks'])
        self.assertIn('no_captured_fatal_entries', result['blocked_checks'])
        self.assertIn('crash', result['readings'])

    def test_wrong_build_slot_sdk_or_locked_device_stops_before_privileged_reads(self):
        for key, value in [('build', 'Native21'), ('slot', '_b'), ('sdk', '36'), ('unlocked', 'locked')]:
            self.calls = []
            result, _ = self.capture('wrong-'+key, overrides={observer.IDENTITY[key]: value})
            self.assertFalse(result['capture_complete'])
            self.assertIn('identity', result['failed_checks'])
            self.assertNotIn('sha256sum /vendor/lib64/sensors.ssc.so', self.calls)

    def test_reused_prior_boot_and_mid_capture_reboot_do_not_pass(self):
        _, baseline = self.capture('baseline')
        result, _ = self.capture('same', 'first-standard', BASE, baseline)
        self.assertIn('distinct_phase_boot', result['failed_checks'])
        runner = self.runner(BASE)
        count = [0]
        def reboot(args, **kwargs):
            row = runner(args, **kwargs)
            if args[4] == observer.IDENTITY['boot_id']:
                count[0] += 1
                if count[0] == 2:row.stdout = SECOND
            return row
        result = observer.capture(self.path, observer.sha(self.path), 'baseline', self.local/'midboot',
                                  'fake-adb', runner=reboot)
        self.assertIn('same_boot', result['failed_checks'])

    def test_stale_phase_config_and_structured_prior_tampering_are_rejected(self):
        _, prior = self.capture('baseline')
        for mutation in ['phase', 'config', 'boot']:
            row = json.loads(prior.read_text())
            if mutation == 'phase':row['phase'] = 'first-standard'
            if mutation == 'config':row['config_sha256'] = 'a'*64
            if mutation == 'boot':row['boot_id'] = FIRST
            changed = self.local/('prior-'+mutation+'.json');changed.write_text(json.dumps(row))
            self.calls = []
            with self.assertRaises(ValueError):
                self.capture('refused-'+mutation, 'first-standard', FIRST, changed)
            self.assertFalse(self.calls)

    def test_unknown_prior_hash_and_output_outside_private_scope_fail_before_adb(self):
        with self.assertRaises(ValueError):
            observer.capture(self.path, '0'*64, 'baseline', self.local/'bad', runner=lambda *a,**k: self.fail('ADB called'))
        with self.assertRaises(ValueError):
            observer.capture(self.path, observer.sha(self.path), 'baseline', self.root/'public-output', runner=lambda *a,**k: self.fail('ADB called'))

    def test_timeouts_and_zero_exit_error_text_stay_blocked(self):
        result, _ = self.capture('timeout', overrides={
            'getenforce': subprocess.TimeoutExpired('getenforce', 1),
            'dumpsys sensorservice': "Can't find service: sensorservice"})
        self.assertTrue(result['capture_complete'])
        self.assertIn('selinux_enforcing', result['blocked_checks'])
        self.assertIn('capture_sensors', result['blocked_checks'])
        self.assertFalse(result['automatic_checks_pass'])

    def test_disconnected_transport_is_blocked_without_privileged_commands(self):
        def absent(args, **kwargs):
            self.calls.append(args[4])
            return SimpleNamespace(returncode=1, stdout='', stderr='device not found')
        result = observer.capture(self.path, observer.sha(self.path), 'baseline',
                                  self.local/'disconnected', 'fake-adb', runner=absent)
        self.assertFalse(result['capture_complete'])
        self.assertEqual(result['blocked_checks'], ['identity'])
        self.assertEqual(self.calls, list(observer.IDENTITY.values()))
        self.assertTrue((self.local/'disconnected/capture.json').exists())

    def test_sensor_drift_fatal_logs_or_service_restart_remain_failures(self):
        for name, values, failed in [
                ('sensor', {'sha256sum /vendor/lib64/sensors.ssc.so': '0'*64+'  /vendor/lib64/sensors.ssc.so'}, 'sensor_library'),
                ('fatal', {'logcat -d -b crash -v epoch -t 200': 'Fatal signal 11'}, 'no_captured_fatal_entries'),
                ('service', {'getprop init.svc.keystore2': 'restarting'}, 'service_keystore2')]:
            result, _ = self.capture(name, overrides=values)
            self.assertIn(failed, result['failed_checks'])

    def test_prior_identity_can_be_used_without_promoting_known_baseline_failures(self):
        result, baseline = self.capture('baseline', overrides={'logcat -d -b crash -v epoch -t 200': 'Fatal signal 11'})
        self.assertFalse(result['automatic_checks_pass'])
        first, _ = self.capture('first', 'first-standard', FIRST, baseline)
        self.assertTrue(first['automatic_checks_pass'])

    def test_package_preparation_binds_actual_image_sensor_and_build(self):
        archive = self.local/'target.zip';boot = b'packaged standard boot';sensor = b'packaged sensor'
        with zipfile.ZipFile(archive, 'w') as z:
            z.writestr('SYSTEM/build.prop', 'ro.build.version.sdk=37\nro.build.version.incremental=target\n')
            z.writestr('IMAGES/boot.img', boot);z.writestr('VENDOR/lib64/sensors.ssc.so', sensor)
        handoff = self.local/'handoff.json'
        data = dict(state='host-artifacts-staged', metadata={'post-sdk-level': '37', 'post-build-incremental': 'target'},
                    standard_packaged_boot_sha256=observer.digest(boot), run='candidate-24-native-22', source_commit='6'*40)
        handoff.write_text(json.dumps(data))
        def prepare(output):
            return observer.prepare(handoff, observer.sha(handoff), archive, observer.sha(archive),
                'example-serial', 'source', '_a', '1'*64, '_b', output)
        output = self.local/'prepared.json';result = prepare(output)
        self.assertEqual(result['target']['boot_sha256'], observer.digest(boot))
        self.assertEqual(result['target']['sensor_sha256'], observer.digest(sensor))
        with self.assertRaises(ValueError):prepare(output)
        data['metadata']['post-build-incremental'] = 'Native21';handoff.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, 'identity differs'):prepare(self.local/'wrong.json')
        self.assertFalse((self.local/'wrong.json').exists())

    def test_invalid_generation_or_slot_config_is_rejected(self):
        for key, value in [('slot', '_a'), ('boot_sha256', 'short'), ('boot_bytes', 0)]:
            config = copy.deepcopy(self.config);config['target'][key] = value
            with self.assertRaises(ValueError):observer.validate(config)


if __name__ == '__main__':
    unittest.main()
