from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'crawler'))
from gradheat.material_store import missing_references


class MaterialReferenceTests(unittest.TestCase):
    def test_large_reference_set_keeps_missing_paths_and_uses_bounded_lookups(self):
        rows=[('file-'+str(i),format(i,'064x')) for i in range(600)]
        missing={rows[0][1],rows[-1][1]}

        class Cursor:
            queries=[]
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def execute(self,query,args=None):
                self.queries.append((query,args))
                if args is None:self.result=rows
                else:self.result=[(sha,) for sha in args if sha not in missing]
            def fetchall(self):return self.result

        cursor=Cursor()
        class Connection:
            def cursor(self):return cursor

        self.assertEqual(missing_references(Connection()),[rows[0],rows[-1]])
        batches=[args for _,args in cursor.queries if args]
        self.assertEqual([len(args) for args in batches],[512,88])
        self.assertFalse(any('JOIN' in query for query,_ in cursor.queries))


if __name__=='__main__':unittest.main()
