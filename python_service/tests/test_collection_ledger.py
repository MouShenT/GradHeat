from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'crawler'),str(ROOT/'tools/research'),str(ROOT/'python_service')]
from run_daily_update import store_collection_ledger


class CollectionLedgerTests(unittest.TestCase):
    def test_large_ledger_retains_failure_states_and_commits_after_all_batches(self):
        rows=[dict(unit='候选大学',url='https://u.edu.cn/'+str(i),status='http-error') for i in range(205)]
        rows[0].update(raw_path='retained.pdf',sha256='a'*64,status='file-saved')
        events=[]
        class Cursor:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def execute(self,query,args):events.append(('run',args))
            def executemany(self,query,args):events.append(('observations',args))
        class Connection:
            def cursor(self):return Cursor()
            def commit(self):events.append(('commit',None))
        store_collection_ledger(Connection(),'frozen-batch','checked-time',{},rows)
        batches=[args for kind,args in events if kind=='observations']
        saved=[row for batch in batches for row in batch]
        self.assertEqual([len(batch) for batch in batches],[100,100,5])
        self.assertEqual(len({row[0] for row in saved}),205)
        self.assertEqual(saved[0][4:6],('a'*64,'file-saved'))
        self.assertTrue(all(row[4] is None and row[5]=='http-error' for row in saved[1:]))
        self.assertEqual(events[-1],('commit',None))


if __name__=='__main__':unittest.main()
