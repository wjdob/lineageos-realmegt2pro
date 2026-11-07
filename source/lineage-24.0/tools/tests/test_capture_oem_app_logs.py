from pathlib import Path
import hashlib
import json
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'device'))
import capture_oem_app_logs as app


class AppLogPreflightTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root_patch = mock.patch.object(app, 'ROOT', Path(temporary.name))
        root_patch.start()
        self.addCleanup(root_patch.stop)
        self.profile = app.ROOT/'configs/test-gallery-profile.json'
        self.profile.parent.mkdir()
        self.apk = '/product/app/RealmeStockPhotos-test/base.apk'
        self.digest = 'a'*64
        self.profile.write_text(json.dumps({
            'model': 'RMX3301', 'sdk': 36, 'lineage': '23.2',
            'profiles': {'photos': {'package': 'com.coloros.gallery3d',
                                    'sha256': self.digest}},
        }))
        self.responses = {
            ('getprop', 'ro.product.model'): 'RMX3301',
            ('getprop', 'ro.build.version.sdk'): '36',
            ('am', 'get-current-user'): '0',
            ('pm', 'path', 'com.coloros.gallery3d'): 'package:'+self.apk,
            ('sha256sum', self.apk): self.digest+'  '+self.apk,
            ('cmd', 'package', 'list', 'packages', '-U', '--user', '0', 'com.coloros.gallery3d'):
                'package:com.coloros.gallery3d uid:10214',
            ('getprop', 'ro.build.version.incremental'): 'test-build',
        }
        self.commands = []

    def run_adb(self, command, **kwargs):
        self.assertEqual(command[:4], ['adb', '-s', 'example', 'shell'])
        self.commands.append(tuple(command[4:]))
        return SimpleNamespace(stdout=self.responses[tuple(command[4:])].encode())

    def test_verified_public_apk_and_actual_user_uid_without_mutation_or_app_start(self):
        with mock.patch.object(subprocess, 'run', side_effect=self.run_adb):
            command, identity = app.preflight('adb', 'example', self.profile, 'photos')
        self.assertEqual(command, ['adb', '-s', 'example'])
        self.assertEqual(identity['uid'], 10214)
        self.assertEqual(identity['apk_sha256'], self.digest)
        self.assertEqual(set(self.commands), set(self.responses))

    def test_wrong_device_hash_or_uid_and_split_package_refuse(self):
        cases = [(('getprop', 'ro.product.model'), 'other-phone'),
                 (('getprop', 'ro.build.version.sdk'), '37'),
                 (('sha256sum', self.apk), '0'*64+'  '+self.apk),
                 (('pm', 'path', 'com.coloros.gallery3d'), 'package:'+self.apk+'\npackage:/product/split.apk'),
                 (('cmd', 'package', 'list', 'packages', '-U', '--user', '0', 'com.coloros.gallery3d'),
                  'package:com.coloros.gallery3d uid:1010214')]
        for key, value in cases:
            with self.subTest(key=key), mock.patch.dict(self.responses, {key: value}), \
                    mock.patch.object(subprocess, 'run', side_effect=self.run_adb), self.assertRaises(ValueError):
                app.preflight('adb', 'example', self.profile, 'photos')

    def test_android17_profile_requires_matching_measured_sdk(self):
        data=json.loads(self.profile.read_text());data.update(sdk=37,lineage='24.0')
        self.profile.write_text(json.dumps(data))
        with mock.patch.dict(self.responses,{('getprop','ro.build.version.sdk'):'37'}), \
                mock.patch.object(subprocess,'run',side_effect=self.run_adb):
            _,identity=app.preflight('adb','example',self.profile,'photos')
        self.assertEqual((identity['sdk'],identity['lineage']),(37,'24.0'))
        with mock.patch.object(subprocess,'run',side_effect=self.run_adb),self.assertRaises(ValueError):
            app.preflight('adb','example',self.profile,'photos')

    def test_unreviewed_sdk_or_lineage_pair_starts_no_transport(self):
        original=json.loads(self.profile.read_text())
        for sdk,lineage in [(38,'24.0'),(37,'23.2'),(36,'24.0'),(True,'23.2')]:
            with self.subTest(sdk=sdk,lineage=lineage):
                data={**original,'sdk':sdk,'lineage':lineage};self.profile.write_text(json.dumps(data))
                with mock.patch.object(subprocess,'run') as run,self.assertRaises(ValueError):
                    app.preflight('adb','example',self.profile,'photos')
                run.assert_not_called()

    def test_serial_and_configuration_boundaries_refuse_before_adb(self):
        with mock.patch.object(subprocess, 'run') as run:
            for serial in ['-e', '', 'example;reboot', 'device name']:
                with self.assertRaises(ValueError): app.preflight('adb', serial, self.profile, 'photos')
            with self.assertRaises(ValueError): app.preflight('adb', 'example', Path('/tmp/untrusted.json'), 'photos')
            run.assert_not_called()

    def test_output_is_new_private_and_cannot_follow_escape_symlink(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name); private = root/'.local'; private.mkdir()
            self.assertEqual(app.private_output(private/'new', root), private/'new')
            for path in [root/'public', private]:
                with self.assertRaises(ValueError): app.private_output(path, root)
            link = private/'link'; link.symlink_to(root/'outside')
            with self.assertRaises(ValueError): app.private_output(link, root)


class AppLogCaptureTests(unittest.TestCase):
    def run_child(self, source, seconds=0.4, limit=app.LIMIT):
        with tempfile.TemporaryDirectory() as name:
            output = Path(name)
            report = app.capture([sys.executable, '-c', source], output, seconds, limit)
            data = (output/'app-logcat.txt').read_bytes()
            self.assertEqual(report['artifacts'][0]['sha256'], hashlib.sha256(data).hexdigest())
            return report, data

    def test_deadline_stops_real_child_and_records_data_without_claiming_feature_success(self):
        report, data = self.run_child("import time;print('trace-ready',flush=True);time.sleep(5)")
        self.assertEqual(report['stop_reason'], 'duration')
        self.assertIn(b'trace-ready', data)
        self.assertTrue(report['nonempty_log'])
        self.assertLess(report['elapsed_seconds'], 3)

    def test_transport_exit_is_distinct_from_complete_observation(self):
        report, data = self.run_child("import sys;print('partial');sys.exit(2)", seconds=2)
        self.assertEqual(report['stop_reason'], 'process-exit')
        self.assertEqual(report['exit_code'], 2)
        self.assertIn(b'partial', data)

    def test_size_threshold_stops_real_child_and_invalid_limits_start_nothing(self):
        report, data = self.run_child("import sys,time;sys.stdout.write('x'*4096);sys.stdout.flush();time.sleep(5)", seconds=2, limit=1024)
        self.assertEqual(report['stop_reason'], 'size-threshold')
        self.assertGreaterEqual(len(data), 1024)
        with mock.patch.object(subprocess, 'Popen') as popen:
            for seconds in [-1, 0, 121, float('nan'), float('inf')]:
                with self.assertRaises(ValueError): app.capture([], Path('/unused'), seconds)
            popen.assert_not_called()


if __name__ == '__main__': unittest.main()
