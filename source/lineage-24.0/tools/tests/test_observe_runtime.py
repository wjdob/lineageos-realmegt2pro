"""Reject misleading endurance claims from elapsed time, restarts or inconsistent clocks."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from observe_runtime import compare, load_baseline, parse_suspend, compare_suspend


class RuntimeEvidenceTests(unittest.TestCase):
    def checkpoint(self, seconds=0, uptime=100, boot='boot-one', build='candidate-one'):
        return dict(observed_utc=(datetime(2026, 10, 27, tzinfo=timezone.utc) +
                                 timedelta(seconds=seconds)).isoformat(),
                    uptime=str(uptime) + ' 0', boot_id=boot, build_incremental=build)

    def test_exact_day_uptime_is_still_not_normal_use_acceptance(self):
        result = compare(self.checkpoint(), self.checkpoint(86400, 86500))
        self.assertTrue(result['same_build_uninterrupted_24_hours'])
        self.assertTrue(result['normal_use_acceptance'].startswith('unproven'))
        self.assertFalse(compare(self.checkpoint(), self.checkpoint(86399, 86499))[
            'same_build_uninterrupted_24_hours'])

    def test_owner_selected_twelve_hour_boundary_and_explicit_override(self):
        before = self.checkpoint()
        at_boundary = self.checkpoint(43200, 43300)
        result = compare(before, at_boundary, required_hours=12)
        self.assertTrue(result['same_build_uninterrupted_required_duration'])
        self.assertEqual(result['required_observation_hours'], 12)
        self.assertFalse(result['same_build_uninterrupted_24_hours'])
        self.assertFalse(compare(before, self.checkpoint(43199, 43299), required_hours=12)[
            'same_build_uninterrupted_required_duration'])
        self.assertFalse(compare(before, at_boundary, required_hours=24)[
            'same_build_uninterrupted_required_duration'])
        self.assertTrue(result['normal_use_acceptance'].startswith('unproven'))
        for hours in (0, -1, float('inf'), float('nan')):
            with self.assertRaises(ValueError):
                compare(before, at_boundary, required_hours=hours)

    def test_twelve_hour_clock_duration_does_not_hide_restart_or_short_uptime(self):
        for later in (self.checkpoint(43200, 300, boot='boot-two'),
                      self.checkpoint(43200, 43300, build='candidate-two'),
                      self.checkpoint(43200, 200)):
            self.assertFalse(compare(self.checkpoint(), later, required_hours=12)[
                'same_build_uninterrupted_required_duration'])

    def test_beta_monitoring_has_no_default_duration_gate(self):
        result = compare(self.checkpoint(), self.checkpoint(60, 160))
        self.assertEqual(result['wall_elapsed_seconds'], 60)
        self.assertIsNone(result['required_observation_hours'])
        self.assertIsNone(result['wall_clock_required_duration_elapsed'])
        self.assertIsNone(result['same_build_uninterrupted_required_duration'])
        self.assertTrue(result['normal_use_acceptance'].startswith('unproven'))

    def test_reboot_build_change_or_clock_jump_cannot_prove_uninterrupted_day(self):
        for later in (self.checkpoint(86400, 300, boot='boot-two'),
                      self.checkpoint(86400, 86500, build='candidate-two'),
                      self.checkpoint(86400, 200)):
            self.assertFalse(compare(self.checkpoint(), later)['same_build_uninterrupted_24_hours'])

    def test_inconsistent_time_is_rejected(self):
        for later in (self.checkpoint(-1, 101), self.checkpoint(1, 99)):
            with self.assertRaises(ValueError):
                compare(self.checkpoint(), later)
        naive = self.checkpoint()
        naive['observed_utc'] = '2026-10-27T00:00:00'
        with self.assertRaises(ValueError):
            compare(naive, self.checkpoint(1, 101))

    def test_baseline_capture_drift_and_path_escape_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            capture = root / 'crash-start.txt'
            capture.write_bytes(b'no fatal patterns\n')
            data = dict(captures={'crash': {'sha256': hashlib.sha256(capture.read_bytes()).hexdigest()}})
            path = root / 'baseline.json'
            path.write_text(json.dumps(data))
            self.assertEqual(load_baseline(path), data)
            capture.write_bytes(b'changed\n')
            with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                load_baseline(path)
            data['captures']['crash']['file'] = '../outside.txt'
            path.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, 'filename'):
                load_baseline(path)

    def test_suspend_parser_uses_the_actual_stats_section(self):
        raw = ('unrelated success: 999\n----- Suspend Stats -----\n'
               'success: 7\nfail: 5\nfailed_resume: 0\nLast Failures:\n'
               'last_failed_dev: alarmtimer\nSuspend Info:\n'
               'suspend attempts: 12\ntotal suspend time: 120882 ms\n')
        self.assertEqual(parse_suspend(raw), dict(success=7, fail=5, failed_resume=0,
                                                  total_suspend_ms=120882))
        self.assertIsNone(parse_suspend('Service not available\n'))

    def test_suspend_abort_only_or_missing_duration_cannot_pass(self):
        before = dict(self.checkpoint(), suspend_stats=dict(success=7, fail=5, total_suspend_ms=100))
        after = dict(self.checkpoint(300, 400), suspend_stats=dict(success=7, fail=9, total_suspend_ms=100))
        self.assertFalse(compare_suspend(before, after)['progress_observed'])
        after['suspend_stats'] = dict(success=8, fail=9)
        self.assertFalse(compare_suspend(before, after)['progress_observed'])

    def test_suspend_progress_requires_same_boot_and_nonreset_counters(self):
        before = dict(self.checkpoint(), suspend_stats=dict(success=7, fail=5, total_suspend_ms=100))
        after = dict(self.checkpoint(300, 400), suspend_stats=dict(success=8, fail=5, total_suspend_ms=200100))
        self.assertTrue(compare_suspend(before, after)['progress_observed'])
        after['boot_id'] = 'new-boot'
        self.assertFalse(compare_suspend(before, after)['progress_observed'])
        after['boot_id'] = before['boot_id']
        after['suspend_stats']['total_suspend_ms'] = 1
        self.assertIn('reset', compare_suspend(before, after)['status'])

    def test_structured_suspend_counter_tampering_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            capture = root/'suspend.txt'
            capture.write_text('----- Suspend Stats -----\nsuccess: 1\nfail: 0\n')
            data = dict(captures={'suspend': dict(file=capture.name,
                sha256=hashlib.sha256(capture.read_bytes()).hexdigest())},
                suspend_stats=dict(success=100, fail=0))
            path = root/'baseline.json'; path.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, 'structured suspend counters'):
                load_baseline(path)


if __name__ == '__main__':
    unittest.main()
