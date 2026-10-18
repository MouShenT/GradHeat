import hashlib,json,sys,tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools/research'))
import collect_parallel_sources as parallel
import expand_school_basics as basics
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock


class ParallelTests(unittest.TestCase):
    def test_recovery_retains_unknown_request_and_never_fetches(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);folder=root/'.research/batch';folder.mkdir(parents=True)
            task=dict(unit='甲校',url='https://a.example.edu/1')
            source=dict(schema_version=1,as_of='2026-10-17',websites=[task])
            (folder/'input.json').write_text(json.dumps(source),encoding='utf-8')
            (folder/'retrieval.json').write_text(json.dumps({parallel.digest(task):dict(state='running')}))
            with patch.object(parallel,'ROOT',root),patch.object(parallel,'retrieve') as fetch,patch.object(parallel.social,'run') as social:
                self.assertEqual(parallel.recover(source,folder),[])
                fetch.assert_not_called();social.assert_not_called()
            state=json.loads((folder/'retrieval.json').read_text())[parallel.digest(task)]
            self.assertEqual(state['state'],'needs-review');self.assertEqual(state['recovery'],'no-refetch')

    def test_recovery_checks_frozen_website_bytes_before_storage(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);folder=root/'.research/batch';folder.mkdir(parents=True)
            task=dict(unit='甲校',url='https://a.example.edu/1')
            source=dict(schema_version=1,as_of='2026-10-17',websites=[task]);key=parallel.digest(task)
            (folder/'input.json').write_text(json.dumps(source),encoding='utf-8')
            (folder/'retrieval.json').write_text(json.dumps({key:dict(state='running')}))
            child=folder/'websites'/key[:16];child.mkdir(parents=True);raw=child/'original.html';raw.write_bytes(b'synthetic')
            (child/'manifest.json').write_text(json.dumps([dict(task,state='retained',source_artifact=str(raw),source_sha256=hashlib.sha256(raw.read_bytes()).hexdigest())]))
            with patch.object(parallel,'ROOT',root),patch.object(parallel,'retrieve') as fetch:
                self.assertEqual(len(parallel.recover(source,folder)),1);fetch.assert_not_called()
                raw.write_bytes(b'changed')
                with self.assertRaises(ValueError):parallel.recover(source,folder)

    def test_pdf_extraction_is_serial_while_requests_overlap(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);barrier=threading.Barrier(2);mutex=threading.Lock();active=0;peak=0
            def response(*args,**kwargs):
                barrier.wait(timeout=3)
                return Mock(url=args[0],iter_content=lambda size:iter([b'%PDF synthetic input']))
            class Document:
                def __enter__(self):
                    nonlocal active,peak
                    with mutex:active+=1;peak=max(peak,active)
                    threading.Event().wait(.03)
                    return self
                def __exit__(self,*args):
                    nonlocal active
                    with mutex:active-=1
                def __len__(self):return 1
                def __iter__(self):return iter([Mock(get_text=lambda:'synthetic PDF text')])
            with patch.object(basics,'ROOT',root),patch.object(basics.requests,'get',side_effect=response),patch('pymupdf.open',side_effect=lambda path:Document()),patch.object(basics.time,'sleep',return_value=None):
                with ThreadPoolExecutor(max_workers=2) as pool:
                    pending=[pool.submit(basics.retrieve,[dict(unit='甲校',url=f'https://school{i}.example.edu/a.pdf')],root/'.research'/str(i)) for i in range(2)]
                    self.assertTrue(all(f.result()[0]['state']=='retained' for f in pending))
            self.assertEqual(peak,1)

    def test_unexpected_retriever_failure_preserves_other_tasks_and_freezes_gap(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);folder=root/'.research/batch';calls=[]
            def retrieve(rows,output):
                row=rows[0];calls.append(row['url'])
                if 'broken.example.edu' in row['url']:
                    error=ValueError('Real originals must stay in .research')
                    error.boundary_context={'checked_root':'synthetic-first-root','path_type':'WindowsPath'}
                    raise error
                output.mkdir(parents=True,exist_ok=True)
                path=output/'original.html';path.write_bytes(b'synthetic source')
                item=dict(row,state='retained',source_artifact=str(path),source_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
                (output/'manifest.json').write_text(json.dumps([item]),encoding='utf-8')
                return [item]
            source=dict(schema_version=1,as_of='2026-10-14',websites=[dict(unit='甲校',url='https://broken.example.edu/1'),dict(unit='乙校',url='https://working.example.edu/1')])
            with patch.object(parallel,'ROOT',root),patch.object(parallel,'retrieve',side_effect=retrieve),patch.object(parallel.time,'sleep',return_value=None):
                outcomes=parallel.collect(source,folder)
                self.assertEqual({r['result']['state'] for r in outcomes},{'retained','needs-review'})
                resumed=parallel.collect(source,folder)
                self.assertEqual(len(calls),2)
                self.assertEqual({r['result']['state'] for r in resumed},{'retained','needs-review'})
                failed=next(r for r in resumed if r['result']['state']=='needs-review')
                self.assertFalse(Path(failed['result']['requested_output']).exists())
                self.assertFalse(failed['result']['requested'])
                self.assertEqual(failed['result']['boundary_check']['checked_root'],'synthetic-first-root')

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
