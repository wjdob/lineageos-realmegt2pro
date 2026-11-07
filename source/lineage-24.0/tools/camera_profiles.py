"""Generate and validate RMX3301 recording metadata against a read-only device inventory."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / 'configs/camera-recording-23.2.json'


def in_range(value, text):
    match = re.fullmatch(r'\[(\d+), (\d+)\]', text)
    return bool(match) and int(match[1]) <= value <= int(match[2])


def validate(config, inventory):
    sensors = {str(s['camera_id']): s for s in inventory['sensors']}
    if set(sensors) != set(config['cameras']):
        raise ValueError('recording camera inventory differs from reviewed topology')
    encoders = [e for e in inventory['encoders']
                if e['name'] == config['video_encoder'] and e['type'] == config['video_mime']]
    if len(encoders) != 1:
        raise ValueError('reviewed hardware video encoder is not unique/present')
    video = encoders[0]
    audio = config['audio']
    if not any(e['type'] == audio['mime'] and e.get('supports_48000hz')
               and e.get('max_channels', 0) >= audio['channels']
               and in_range(audio['bit_rate'], e['bitrate_range'])
               for e in inventory['encoders']):
        raise ValueError('AAC audio capability is not established')
    if audio['sample_rate'] != 48000 or config['frame_rate'] != 30:
        raise ValueError('unreviewed sampling/frame rate')
    for camera, qualities in config['cameras'].items():
        if not qualities or len(qualities) != len(set(qualities)):
            raise ValueError('empty/duplicate camera recording qualities')
        for quality in qualities:
            fmt = config['formats'][quality]
            if not any(x['width'] == fmt['width'] and x['height'] == fmt['height']
                       and 0 < x['min_frame_duration_ns'] <= 33333334
                       for x in sensors[camera]['recording_outputs']):
                raise ValueError('current HAL does not expose requested profile: ' + camera + '/' + quality)
            if not any(x['width'] == fmt['width'] and x['height'] == fmt['height']
                       and x['supports_30fps'] for x in video['profile_formats']):
                raise ValueError('encoder cannot advertise requested profile: ' + quality)
            if not in_range(fmt['bit_rate'], video['bitrate_range']):
                raise ValueError('profile bitrate exceeds measured encoder range')


def profiles(config):
    """Yield explicit normal/timelapse profiles, including independently testable aliases."""
    for camera, qualities in config['cameras'].items():
        sizes = sorted(qualities, key=lambda q: config['formats'][q]['width']
                       * config['formats'][q]['height'])
        for prefix, offset in [('', 0), ('timelapse', 1000)]:
            for quality, fmt in [('low', config['formats'][sizes[0]]),
                                 ('high', config['formats'][sizes[-1]])] + [
                                     (q, config['formats'][q]) for q in qualities]:
                number = {'low': 0, 'high': 1}.get(quality, fmt['quality']) + offset
                yield int(camera), prefix + quality, number, fmt


def render(config):
    root = ET.Element('MediaSettings')
    groups = {int(camera): ET.SubElement(root, 'CamcorderProfiles', cameraId=camera)
              for camera in config['cameras']}
    audio = config['audio']
    for camera, name, _, fmt in profiles(config):
        profile = ET.SubElement(groups[camera], 'EncoderProfile', quality=name,
                                fileFormat='mp4', duration='30')
        ET.SubElement(profile, 'Video', codec=config['video_codec'],
                      bitRate=str(fmt['bit_rate']), width=str(fmt['width']),
                      height=str(fmt['height']), frameRate=str(config['frame_rate']))
        ET.SubElement(profile, 'Audio', codec=audio['codec'], bitRate=str(audio['bit_rate']),
                      sampleRate=str(audio['sample_rate']), channels=str(audio['channels']))
    for group in groups.values():
        for quality in [95, 80, 70]:
            ET.SubElement(group, 'ImageEncoding', quality=str(quality))
        ET.SubElement(group, 'ImageDecoding', memCap='20000000')
    for name in ['3gp', 'mp4']:
        ET.SubElement(root, 'EncoderOutputFileFormat', name=name)
    ET.SubElement(root, 'VideoEncoderCap', name='h264', enabled='true',
                  minBitRate='64000', maxBitRate='100000000', minFrameWidth='176',
                  maxFrameWidth='3840', minFrameHeight='144', maxFrameHeight='2160',
                  minFrameRate='30', maxFrameRate='30')
    ET.SubElement(root, 'AudioEncoderCap', name='aac', enabled='true',
                  minBitRate=str(audio['bit_rate']), maxBitRate=str(audio['bit_rate']),
                  minSampleRate='48000', maxSampleRate='48000', minChannels='1', maxChannels='2')
    ET.SubElement(root, 'VideoDecoderCap', name='wmv', enabled='false')
    ET.SubElement(root, 'AudioDecoderCap', name='wma', enabled='false')
    ET.indent(root, space='    ')
    return ET.tostring(root, encoding='utf-8', xml_declaration=True) + b'\n'


def source_report(tree):
    config = json.loads(CONFIG.read_text())
    expected = render(config)
    xml = tree / 'device/realme/ferrari/configs/media/media_profiles_V1_0.xml'
    device = tree / 'device/realme/ferrari/device.mk'
    copy = ('$(LOCAL_PATH)/configs/media/media_profiles_V1_0.xml:'
            '$(TARGET_COPY_OUT_VENDOR)/etc/media_profiles_V1_0.xml')
    if xml.read_bytes() != expected or device.read_text().count(copy) != 1:
        raise ValueError('recording source XML/copy rule differs from reviewed contract')
    return dict(pass_all=True, profiles=len(list(profiles(config))),
                xml_sha256=hashlib.sha256(expected).hexdigest(),
                limits='Source XML and copy rule only; no packaged image or recording proof.')


def package_report(target_files):
    config = json.loads(CONFIG.read_text())
    expected = render(config)
    path = 'VENDOR/etc/media_profiles_V1_0.xml'
    with zipfile.ZipFile(target_files) as archive:
        names = archive.namelist()
        if names.count(path) != 1 or archive.read(path) != expected:
            raise ValueError('packaged recording XML missing/duplicated/different')
        for prefix in ['PRODUCT', 'ODM']:
            earlier = prefix + '/etc/media_profiles_V1_0.xml'
            if earlier in names:
                raise ValueError('earlier MediaProfiles search path requires review: ' + earlier)
        for member in names:
            if not member.endswith('/build.prop'):
                continue
            text = archive.read(member).decode('utf-8')
            for line in text.splitlines():
                key, sep, value = line.partition('=')
                if sep and ((key == 'media.settings.xml' and value)
                            or (key == 'ro.media.xml_variant.profiles'
                                and value not in ('', '_V1_0'))):
                    raise ValueError('unreviewed MediaProfiles property override')
    return dict(pass_all=True, profiles=len(list(profiles(config))), packaged_path=path,
                xml_sha256=hashlib.sha256(expected).hexdigest(),
                limits='Target-files XML/precedence/property check only; OTA/image binding '
                       'and actual app recording remain separate checks.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--inventory', type=Path)
    modes.add_argument('--source-tree', type=Path)
    modes.add_argument('--target-files', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    if args.inventory:
        if not args.output:
            parser.error('--inventory requires --output')
        config = json.loads(CONFIG.read_text())
        evidence = json.loads(args.inventory.read_text())
        if evidence.get('pass_all') is not True:
            raise ValueError('capability probe did not pass')
        validate(config, evidence['inventory'])
        data = render(config)
        if args.output.exists():
            raise ValueError('refusing to overwrite media profiles')
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(data)
        report = dict(profiles=len(list(profiles(config))), bytes=len(data))
    else:
        if args.output:
            parser.error('--output is only used with --inventory')
        report = source_report(args.source_tree) if args.source_tree else package_report(args.target_files)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))
