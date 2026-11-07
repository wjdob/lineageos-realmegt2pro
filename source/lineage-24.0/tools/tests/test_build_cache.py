import json
from pathlib import Path
import sys,tempfile,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'build'))
from isolated_job import cache_layers


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.allowed=Path(self.tmp.name)/'runs';self.records=Path(self.tmp.name)/'records'

    def create(self,name,state='success',parent=None):
        run=self.allowed/name;(run/'upper').mkdir(parents=True)
        (run/'upper/.realme-next-isolated.json').write_text(json.dumps(dict(run=str(run),base_run=str(parent) if parent else None)))
        record=self.records/name;record.mkdir(parents=True)
        (record/'result.json').write_text(json.dumps(dict(state=state,finished_ns=123 if state!='running' else None)))
        return run

    def test_order_preserves_all_ancestors(self):
        parent=self.create('first');child=self.create('second',parent=parent)
        self.assertEqual(cache_layers(child,self.allowed,self.records),[child/'upper',parent/'upper'])

    def test_failed_requires_explicit_option(self):
        run=self.create('failed','failed')
        with self.assertRaises(ValueError):cache_layers(run,self.allowed,self.records)
        self.assertEqual(cache_layers(run,self.allowed,self.records,True),[run/'upper'])

    def test_running_rejected_even_with_option(self):
        run=self.create('active','running')
        with self.assertRaises(ValueError):cache_layers(run,self.allowed,self.records,True)

    def test_cycle_rejected(self):
        run=self.create('cycle');marker=run/'upper/.realme-next-isolated.json'
        marker.write_text(json.dumps(dict(run=str(run),base_run=str(run))))
        with self.assertRaises(ValueError):cache_layers(run,self.allowed,self.records)

    def test_escape_rejected(self):
        with self.assertRaises(ValueError):cache_layers(self.allowed/'../elsewhere',self.allowed,self.records)
