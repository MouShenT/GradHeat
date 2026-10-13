import hashlib,json,sys,tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools/research'))
import collect_parallel_sources as parallel


class ParallelTests(unittest.TestCase):
    def test_websites_overlap_across_hosts_but_not_on_one_host_and_resume_reuses_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);folder=root/'.research/batch'
            barrier=threading.Barrier(2);mutex=threading.Lock();active={};peak=0;calls=[]
            def retrieve(rows,output):
                nonlocal peak
                row=rows[0];host=parallel.urlsplit(row['url']).hostname
                output.mkdir(parents=True,exist_ok=True)
                with mutex:
                    self.assertEqual(active.get(host,0),0)
                    active[host]=1;peak=max(peak,sum(active.values()));calls.append(row['url'])
                if len(calls)<=2:barrier.wait(timeout=3)
                time.sleep(.02)
                path=output/'original.html';path.write_bytes(b'<html>synthetic school document</html>')
                item=dict(row,state='retained',source_artifact=str(path),source_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
                (output/'manifest.json').write_text(json.dumps([item]),encoding='utf-8')
                with mutex:active[host]=0
                return [item]
            source=dict(schema_version=1,as_of='2026-10-13',websites=[dict(unit='甲校',url='https://a.example.edu/1'),dict(unit='乙校',url='https://b.example.edu/1'),dict(unit='甲校',url='https://a.example.edu/2')])
            with patch.object(parallel,'ROOT',root),patch.object(parallel,'retrieve',side_effect=retrieve),patch.object(parallel.time,'sleep',side_effect=lambda seconds: threading.Event().wait(.01)):
                self.assertEqual(len(parallel.collect(source,folder)),3)
                parallel.collect(source,folder)
                self.assertEqual(len(calls),3)
            self.assertGreaterEqual(peak,2)
            path=next(folder.rglob('original.html'));path.write_bytes(b'changed')
            with patch.object(parallel,'ROOT',root):
                with self.assertRaises(ValueError):parallel.collect(source,folder)

    def test_platforms_overlap_and_database_writer_stays_on_caller_thread(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);folder=root/'.research/batch';barrier=threading.Barrier(2);worker_ids=set();main=threading.get_ident()
            def run(**kwargs):
                self.assertFalse(kwargs['vm']);worker_ids.add(threading.get_ident());barrier.wait(timeout=3)
                return dict(folder=str(root/kwargs['run_id_override']),snapshots=2)
            def resume(path):
                self.assertEqual(threading.get_ident(),main)
                return dict(snapshots=2,database_state='committed')
            source=dict(schema_version=1,as_of='2026-10-13',social=[dict(platform=p,query='合成择校讨论') for p in ('bili','zhihu')])
            with patch.object(parallel,'ROOT',root),patch.object(parallel.social,'ROOT',root),patch.object(parallel.social,'platform_health',return_value={}),patch.object(parallel.social,'run',side_effect=run):
                outcomes=parallel.collect(source,folder)
            with patch.object(parallel.social,'committed_result',return_value=None),patch.object(parallel.social,'resume',side_effect=resume):
                receipts=parallel.store(outcomes,folder)
            self.assertEqual(len(worker_ids),2);self.assertEqual(len(receipts),2)
