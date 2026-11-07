from pathlib import Path
import sys,tempfile,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app_dependency_audit as audit

class AppDependencyAuditTests(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
    def index(self,name,text):
        p=self.root/name;p.write_text(text,encoding='utf-8');return audit.read_inventory([p])
    def test_inherited_method_removed_and_app_defined_name_excluded(self):
        app=self.index('app','class\tLapp/Own;\tLjava/lang/Object;\t\ncall\tLchild;->run()V\tLapp/Own;->start()V\ncall\tLapp/Own;->run()V\tLapp/Own;->start()V\n')
        before=self.index('before','class\tLchild;\tLparent;\t\nclass\tLparent;\tLjava/lang/Object;\t\nmethod\tLparent;->run()V\nclass\tLapp/Own;\tLjava/lang/Object;\t\nmethod\tLapp/Own;->run()V\n')
        after=self.index('after','class\tLchild;\tLparent;\t\nclass\tLparent;\tLjava/lang/Object;\t\nclass\tLapp/Own;\tLjava/lang/Object;\t\n')
        result=audit.compare(app,before,after)
        self.assertEqual([r['symbol'] for r in result['removed_members_referenced']],['Lchild;->run()V'])
    def test_duplicate_provider_is_unknown_and_cycle_terminates(self):
        one=self.root/'one';two=self.root/'two';one.write_text('class\tLc;\tLd;\t\nclass\tLd;\tLc;\t\n');two.write_text('class\tLc;\tLd;\t\n')
        self.assertIsNone(audit.resolve('Lc;->run()V','call',audit.read_inventory([one,two])))
        self.assertFalse(audit.resolve('Lc;->run()V','call',audit.read_inventory([one])))
    def test_conflicting_hierarchy_refuses_implicit_provider_selection(self):
        one=self.root/'one';two=self.root/'two';one.write_text('class\tLc;\tLd;\t\n');two.write_text('class\tLc;\tLe;\t\n')
        with self.assertRaises(ValueError):audit.read_inventory([one,two])

if __name__=='__main__':unittest.main()
