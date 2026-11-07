from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from elf_symbols import dynamic_symbols


class SymbolTests(unittest.TestCase):
    def test_actual_android_bionic_ifunc_is_not_lost_to_multiword_type(self):
        rows=dynamic_symbols('  1030: 00000000000dc3ec   100 <OS specific>: 10 GLOBAL DEFAULT   15 memcpy@@LIBC')
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['name'],'memcpy@@LIBC')
        self.assertEqual(rows[0]['binding'],'GLOBAL')
        self.assertEqual(rows[0]['section'],'15')

    def test_undefined_versioned_and_weak_imports_preserve_identity(self):
        rows=dynamic_symbols('''  12: 0000000000000000 0 FUNC GLOBAL DEFAULT UND memcpy@LIBC (2)
  13: 0000000000000000 0 NOTYPE WEAK DEFAULT UND __cxa_finalize
''')
        self.assertEqual([row['name'] for row in rows],['memcpy@LIBC','__cxa_finalize'])
        self.assertEqual([row['binding'] for row in rows],['GLOBAL','WEAK'])
        self.assertTrue(all(row['section']=='UND' for row in rows))

    def test_header_and_unnamed_zero_entry_do_not_invent_symbols(self):
        self.assertEqual(dynamic_symbols('''   Num:    Value          Size Type    Bind   Vis      Ndx Name
     0: 0000000000000000     0 NOTYPE  LOCAL  DEFAULT  UND
'''),[])

    def test_visibility_and_named_ifunc_type_are_preserved(self):
        rows=dynamic_symbols(''' 5: 0000000000000120 12 IFUNC GLOBAL PROTECTED 3 resolver
 6: 0000000000000200 4 OBJECT LOCAL HIDDEN 4 private_data
''')
        self.assertEqual(rows[0]['type'],'IFUNC')
        self.assertEqual(rows[0]['visibility'],'PROTECTED')
        self.assertEqual(rows[1]['binding'],'LOCAL')
        self.assertEqual(rows[1]['visibility'],'HIDDEN')


if __name__=='__main__':unittest.main()
