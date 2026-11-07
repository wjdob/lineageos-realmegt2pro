import gzip
import hashlib
import importlib.util
from pathlib import Path
import unittest
import zlib
import struct

module_path = Path(__file__).resolve().parents[1]/'device/backup_upgrade_state.py'
spec = importlib.util.spec_from_file_location('backup_upgrade_state', module_path)
backup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup)


class BackupStreamTests(unittest.TestCase):
    def test_component_scope_has_all_os_and_metadata_but_no_userdata(self):
        parts=backup.selected_partitions('quiet',True)
        self.assertEqual(len(parts),16)
        self.assertNotIn('userdata',parts)
        self.assertIn('metadata',parts)
        self.assertIn('super',parts)
        self.assertEqual(set(parts)|{'userdata'},set(backup.QUIET_PARTITIONS))

    def test_full_quiet_scope_keeps_userdata(self):
        self.assertEqual(backup.selected_partitions('quiet'),backup.QUIET_PARTITIONS)

    def test_component_capture_cannot_be_an_android_probe(self):
        with self.assertRaises(ValueError):backup.selected_partitions('probe',True)

    def snapshot_fixture(self):
        message = bytes([2])+struct.pack('<I',0x56740ab0)+bytes([0,1])+bytes(57)
        evidence = dict(purpose='quiet-recovery-vab-evidence',serial='owner',build='23b',slot='b',boot_id='quiet',
            metadata_sha256='a'*64,metadata_state_bytes=0,metadata_state_sha256=hashlib.sha256(b'').hexdigest(),
            metadata_filesystem_clean=True,misc_message_sha256=hashlib.sha256(message).hexdigest())
        arguments = dict(serial='owner',build='23b',slot='b',boot_id='quiet',metadata_sha='a'*64,message=message)
        return evidence,arguments

    def test_exact_quiet_snapshot_evidence_is_accepted(self):
        evidence,arguments = self.snapshot_fixture()
        self.assertEqual(backup.validate_quiet_snapshot_evidence(evidence,**arguments)['merge_status'],0)

    def test_pending_merge_is_refused(self):
        evidence,arguments = self.snapshot_fixture()
        message=bytearray(arguments['message']);message[5]=3;arguments['message']=bytes(message)
        with self.assertRaises(ValueError): backup.validate_quiet_snapshot_evidence(evidence,**arguments)

    def test_wrong_virtual_ab_magic_is_refused(self):
        evidence,arguments = self.snapshot_fixture()
        message=bytearray(arguments['message']);message[1]^=1;arguments['message']=bytes(message)
        with self.assertRaises(ValueError): backup.validate_quiet_snapshot_evidence(evidence,**arguments)

    def test_other_recovery_boot_is_refused(self):
        evidence,arguments = self.snapshot_fixture();arguments['boot_id']='new-boot'
        with self.assertRaises(ValueError): backup.validate_quiet_snapshot_evidence(evidence,**arguments)

    def test_changed_metadata_is_refused(self):
        evidence,arguments = self.snapshot_fixture();arguments['metadata_sha']='b'*64
        with self.assertRaises(ValueError): backup.validate_quiet_snapshot_evidence(evidence,**arguments)

    def test_nonempty_unreviewed_snapshot_proto_is_refused(self):
        evidence,arguments = self.snapshot_fixture();evidence['metadata_state_bytes']=2
        with self.assertRaises(ValueError): backup.validate_quiet_snapshot_evidence(evidence,**arguments)

    def test_bounded_large_expansion_matches_all_source_bytes(self):
        raw = b'\0'*(25*1024*1024)+b'end'
        measurement = backup.GzipMeasurement(len(raw))
        measurement.feed(gzip.compress(raw, compresslevel=1))
        self.assertEqual(measurement.finish(), hashlib.sha256(raw).hexdigest())

    def test_fragmented_gzip_header_and_body(self):
        raw = b'firmware remains untouched'*30
        measurement = backup.GzipMeasurement(len(raw))
        for byte in gzip.compress(raw):
            measurement.feed(bytes([byte]))
        self.assertEqual(measurement.finish(), hashlib.sha256(raw).hexdigest())

    def test_truncation_is_rejected(self):
        measurement = backup.GzipMeasurement(4)
        measurement.feed(gzip.compress(b'data')[:-3])
        with self.assertRaises(ValueError):
            measurement.finish()

    def test_overrun_is_rejected(self):
        measurement = backup.GzipMeasurement(3)
        with self.assertRaises(ValueError):
            measurement.feed(gzip.compress(b'data'))

    def test_extra_member_is_rejected(self):
        measurement = backup.GzipMeasurement(4)
        with self.assertRaises(ValueError):
            measurement.feed(gzip.compress(b'data')+gzip.compress(b'extra'))

    def test_crc_corruption_is_rejected(self):
        data = bytearray(gzip.compress(b'data'))
        data[-8] ^= 1
        measurement = backup.GzipMeasurement(4)
        with self.assertRaises(zlib.error):
            measurement.feed(data)

    def test_userdata_bind_mount_is_not_quiet(self):
        with self.assertRaises(ValueError):
            backup.require_quiet_mounts('/dev/block/dm-9 /data/media f2fs rw 0 0')

    def test_writable_os_mapping_is_not_quiet(self):
        with self.assertRaises(ValueError):
            backup.require_quiet_mounts('/dev/block/dm-1 /product ext4 rw,noatime 0 0')

    def test_ramdisk_and_readonly_os_are_allowed(self):
        backup.require_quiet_mounts('tmpfs /tmp tmpfs rw 0 0\n/dev/block/dm-1 /product ext4 ro 0 0')

    def test_protected_partitions_are_not_capture_targets(self):
        self.assertNotIn('abl_b', backup.QUIET_PARTITIONS)
        self.assertNotIn('xbl_b', backup.QUIET_PARTITIONS)
        self.assertNotIn('frp', backup.QUIET_PARTITIONS)
        self.assertIn('userdata', backup.QUIET_PARTITIONS)
        self.assertIn('metadata', backup.QUIET_PARTITIONS)


if __name__ == '__main__':
    unittest.main()
