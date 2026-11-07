"""Storage-review selection must retain live/kept ancestry and refuse ambiguity."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'build'))
import cache_inventory as cache


class CacheInventoryTests(unittest.TestCase):
    def setUp(self):
        (cache.REPO/'tmp').mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(prefix='cache-review-', dir=cache.REPO/'tmp')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.work, self.records = self.root/'runs', self.root/'records'
        self.work.mkdir(); self.records.mkdir()
        self.empty = dict(references={}, issues=[], complete=True,
                          processes_seen=0, namespaces_seen=0)
        self.create('keep')

    def create(self, name, base=None, state='success', finished=123):
        run = self.work/name
        (run/'upper').mkdir(parents=True)
        (run/'upper/.realme-next-isolated.json').write_text(json.dumps(
            dict(run=str(run), base_run=str(self.work/base) if base else None)))
        (self.records/name).mkdir(parents=True)
        (self.records/name/'result.json').write_text(json.dumps(dict(state=state, finished_ns=finished)))
        return run

    def get(self, keep=('keep',), mounts=None, measure=False):
        return cache.inventory(self.work, self.records, keep,
                               mounts=self.empty if mounts is None else mounts, measure=measure)

    def test_closed_batch_is_child_first_and_retained_chain_is_protected(self):
        self.create('old-parent'); self.create('old-child', base='old-parent')
        self.create('new', base='keep')
        result = self.get(keep=['new'])
        self.assertTrue(result['complete'])
        self.assertEqual(result['closed_review_set_child_first'], ['old-child', 'old-parent'])
        rows = {r['name']: r for r in result['rows']}
        self.assertEqual(rows['new']['ancestors'], ['keep'])
        self.assertIn('ancestor required by new', rows['keep']['protected_reasons'])
        self.assertIsNone(result['measured_review_bytes'])

    def test_nonterminal_or_unverified_child_retains_ancestors(self):
        self.create('parent')
        self.create('running', base='parent', state='running', finished=None)
        self.create('bad-finished', base='parent', finished='123')
        self.assertEqual(self.get()['closed_review_set_child_first'], [])

    def test_live_completed_child_retains_its_entire_chain(self):
        self.create('parent'); self.create('child', base='parent')
        mounts = dict(self.empty, references={'child': [{'pid': 10, 'namespace': 'mnt:[1]'}]})
        result = self.get(mounts=mounts)
        self.assertEqual(result['closed_review_set_child_first'], [])
        parent = next(r for r in result['rows'] if r['name']=='parent')
        self.assertIn('ancestor required by child', parent['protected_reasons'])

    def test_no_retention_choice_never_proposes_cleanup(self):
        self.create('old')
        result = self.get(keep=[])
        self.assertTrue(result['complete'])
        self.assertEqual(result['closed_review_set_child_first'], [])

    def test_missing_requested_retained_root_holds_all(self):
        self.create('old')
        self.assertFalse(self.get(keep=['typo'])['complete'])
        self.assertEqual(self.get(keep=['typo'])['closed_review_set_child_first'], [])

    def test_missing_metadata_or_ancestor_holds_all(self):
        self.create('old')
        self.create('broken', base='absent')
        self.assertFalse(self.get()['complete'])
        self.assertEqual(self.get()['closed_review_set_child_first'], [])
        (self.records/'broken/result.json').unlink()
        self.assertFalse(self.get()['complete'])

    def test_cyclic_graph_holds_otherwise_unused_caches(self):
        self.create('old'); self.create('cycle-a', base='cycle-b'); self.create('cycle-b', base='cycle-a')
        result = self.get()
        self.assertFalse(result['complete'])
        self.assertEqual(result['closed_review_set_child_first'], [])

    def test_escaping_base_and_wrong_marker_identity_hold_all(self):
        run = self.create('broken')
        marker = run/'upper/.realme-next-isolated.json'
        marker.write_text(json.dumps(dict(run=str(run), base_run=str(self.root/'source'))))
        self.assertFalse(self.get()['complete'])
        marker.write_text(json.dumps(dict(run=str(self.work/'keep'), base_run=None)))
        self.assertFalse(self.get()['complete'])

    def test_symlink_run_and_symlink_metadata_are_never_followed(self):
        source = self.root/'original-source'; source.mkdir()
        sentinel = source/'preserve'; sentinel.write_text('original')
        (self.work/'alias').symlink_to(source, target_is_directory=True)
        self.assertFalse(self.get()['complete'])
        (self.work/'alias').unlink()
        record = self.records/'keep/result.json'; record.unlink(); record.symlink_to(sentinel)
        self.assertFalse(self.get()['complete'])
        self.assertEqual(sentinel.read_text(), 'original')

    def test_incomplete_visibility_or_unknown_live_cache_holds_measurement(self):
        self.create('old')
        for mounts in [dict(self.empty, complete=False, issues=[{'pid':1,'error':'PermissionError'}]),
                       dict(self.empty, references={'unknown':[{'pid':10,'namespace':'mnt:[1]'}]})]:
            with self.subTest(mounts=mounts), mock.patch.object(cache.subprocess, 'run') as run:
                result = self.get(mounts=mounts, measure=True)
                self.assertFalse(result['complete'])
                self.assertEqual(result['closed_review_set_child_first'], [])
                run.assert_not_called()

    def test_measurement_only_visits_review_batch_with_no_follow_or_cross_fs(self):
        self.create('old')
        with mock.patch.object(cache.subprocess, 'run', return_value=subprocess.CompletedProcess(
                [], 0, stdout='8192\t'+str(self.work/'old')+'\n', stderr='')) as run:
            result = self.get(measure=True)
        self.assertEqual(result['measured_review_bytes'], 8192)
        self.assertEqual(run.call_args.args[0], ['du','-s','-x','-B1','-P','--',str(self.work/'old')])

    def test_mount_views_are_not_deduplicated_and_escaped_paths_are_decoded(self):
        proc = self.root/'proc'; proc.mkdir()
        spaced_work = self.root/'work with space'
        escaped = str(spaced_work).replace(' ', '\\040')
        for pid, name in [('10','keep'), ('20','other')]:
            (proc/pid/'ns').mkdir(parents=True)
            (proc/pid/'ns/mnt').symlink_to('mnt:[same-namespace]')
            (proc/pid/'mountinfo').write_text('1 0 0:1 / /build/lineage rw - overlay overlay rw,upperdir='+escaped+'/'+name+'/upper\n')
        result = cache.scan_mounts(spaced_work, proc)
        self.assertTrue(result['complete'])
        self.assertEqual(set(result['references']), {'keep','other'})
        self.assertEqual(result['namespaces_seen'], 1)

    def test_permission_error_is_not_treated_as_absent_process(self):
        proc = self.root/'proc'; (proc/'10').mkdir(parents=True)
        with mock.patch.object(cache.os, 'readlink', side_effect=PermissionError('no access')):
            result = cache.scan_mounts(self.work, proc)
        self.assertFalse(result['complete'])
        self.assertEqual(result['issues'][0]['error'], 'PermissionError')

    def test_report_refuses_public_output_and_overwrite(self):
        with self.assertRaises(ValueError):cache.write_report(cache.REPO/'docs/accidental.json', {})
        destination = self.root/'report.json'
        cache.write_report(destination, {'first':True})
        with self.assertRaises(FileExistsError):cache.write_report(destination, {'second':True})
        self.assertEqual(json.loads(destination.read_text()), {'first':True})


if __name__ == '__main__':
    unittest.main()
