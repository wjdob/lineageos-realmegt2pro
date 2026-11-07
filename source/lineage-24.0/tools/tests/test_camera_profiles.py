"""Reject advertised profiles which exceed HAL/codec evidence, including prior front gap."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
import tempfile
import zipfile
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import camera_profiles as profile


class RecordingProfilesTests(unittest.TestCase):
    def setUp(self):
        self.config = json.loads(profile.CONFIG.read_text())
        sizes = [(176, 144), (320, 240), (352, 288), (720, 480),
                 (1280, 720), (1920, 1080), (3840, 2160)]
        # Independent compact capability fixture: front has no 4K advertisement;
        # microscope has no 1080p advertisement. These are HAL limits, not proof
        # of physical sensor ceilings. Actual device/native-parser runs are separate.
        self.inventory = dict(sensors=[dict(camera_id=str(camera), recording_outputs=[
            dict(width=w, height=h, min_frame_duration_ns=33333333)
            for w, h in sizes if (camera != 1 or w <= 1920) and (camera != 3 or w <= 1280)])
            for camera in range(5)], encoders=[
                dict(name='c2.qti.avc.encoder', type='video/avc',
                     bitrate_range='[1, 100000000]', profile_formats=[
                         dict(width=w, height=h, supports_30fps=True) for w, h in sizes]),
                dict(name='c2.android.aac.encoder', type='audio/mp4a-latm',
                     supports_48000hz=True, max_channels=6, bitrate_range='[8000, 510000]')])

    def test_front_1080p_exists_and_higher_unexposed_modes_stay_absent(self):
        profile.validate(self.config, self.inventory)
        generated = {(c, q): f for c, _, q, f in profile.profiles(self.config)}
        self.assertEqual((generated[1, 6]['width'], generated[1, 6]['height']), (1920, 1080))
        self.assertEqual(generated[1, 1006], generated[1, 6])
        self.assertNotIn((1, 8), generated)
        self.assertNotIn((3, 6), generated)
        self.assertEqual(generated[0, 1]['width'], 3840)
        self.assertEqual(generated[3, 1]['width'], 1280)
        self.assertEqual(generated[0, 0]['width'], 176)

    def test_extra_profile_requires_hal_advertisement(self):
        self.config['cameras']['1'].append('2160p')
        with self.assertRaisesRegex(ValueError, 'current HAL does not expose'):
            profile.validate(self.config, self.inventory)

    def test_missing_encoder_support_cannot_be_inferred_from_sensor(self):
        for fmt in self.inventory['encoders'][0]['profile_formats']:
            if fmt['width'] == 1920:
                fmt['supports_30fps'] = False
        with self.assertRaisesRegex(ValueError, 'encoder cannot advertise'):
            profile.validate(self.config, self.inventory)

    def test_unknown_or_too_slow_hal_timing_is_not_assumed_30fps(self):
        for duration in [0, 66666666]:
            inventory = deepcopy(self.inventory)
            inventory['sensors'][1]['recording_outputs'][-1]['min_frame_duration_ns'] = duration
            with self.assertRaisesRegex(ValueError, 'current HAL does not expose'):
                profile.validate(self.config, inventory)

    def test_out_of_range_bitrate_and_unestablished_aac_are_rejected(self):
        self.config['formats']['2160p']['bit_rate'] = 100000001
        with self.assertRaisesRegex(ValueError, 'bitrate'):
            profile.validate(self.config, self.inventory)
        self.config = json.loads(profile.CONFIG.read_text())
        self.inventory['encoders'][1]['supports_48000hz'] = False
        with self.assertRaisesRegex(ValueError, 'AAC audio'):
            profile.validate(self.config, self.inventory)

    def test_committed_xml_matches_recipe_generator_and_has_unique_profiles(self):
        path = profile.ROOT / 'overlays/lineage-23.2/ferrari/media/media_profiles_V1_0.xml'
        self.assertEqual(path.read_bytes(), profile.render(self.config))
        root = ET.fromstring(path.read_bytes())
        names = [(g.get('cameraId'), p.get('quality'))
                 for g in root.findall('CamcorderProfiles') for p in g.findall('EncoderProfile')]
        self.assertEqual(len(names), 84)
        self.assertEqual(len(names), len(set(names)))
        recipe = json.loads((profile.ROOT / 'tools/build/recipe-23.2.json').read_text())
        row, = [r for r in recipe['new_files'] if r['source'] == str(path.relative_to(profile.ROOT))]
        self.assertEqual(row['relative'], 'configs/media/media_profiles_V1_0.xml')

    def test_package_gate_rejects_missing_xml_precedence_and_property_overrides(self):
        with tempfile.TemporaryDirectory(dir=profile.ROOT / 'tmp') as directory:
            path = Path(directory) / 'target-files.zip'
            base = {'VENDOR/etc/media_profiles_V1_0.xml': profile.render(self.config)}
            cases = [(base, True), ({}, False),
                     (dict(base, **{'ODM/etc/media_profiles_V1_0.xml': b'<MediaSettings/>'}), False),
                     (dict(base, **{'VENDOR/build.prop': b'ro.media.xml_variant.profiles=_other\n'}), False),
                     (dict(base, **{'VENDOR/build.prop': b'media.settings.xml=/data/other.xml\n'}), False)]
            for files, accepted in cases:
                with zipfile.ZipFile(path, 'w') as archive:
                    for name, data in files.items():
                        archive.writestr(name, data)
                if accepted:
                    self.assertTrue(profile.package_report(path)['pass_all'])
                else:
                    with self.assertRaises(ValueError):
                        profile.package_report(path)


if __name__ == '__main__':
    unittest.main()
