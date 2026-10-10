import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch,Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from gradheat_python.collection_plan import prepare,prepare_input,read_plan,write_json,checkpoint,load_state
from gradheat_python.collection_fetch import allowed_url,fetch,official
from gradheat_python.collection_search import github_search,official_search
from gradheat_python import collection_cli as cli

ROOT=Path(__file__).resolve().parents[2]
KEYWORDS=json.loads((ROOT/'config/collection-keywords.json').read_text(encoding='utf-8'))
POLICY=json.loads((ROOT/'config/collection-policy.json').read_text(encoding='utf-8'))


class AutonomousCollectionTests(unittest.TestCase):
    def query_plan(self,root,tasks):
        (root/'config').mkdir(exist_ok=True)
        write_json(root/'config/collection-policy.json',POLICY)
        write_json(root/'config/collection-keywords.json',KEYWORDS)
        return prepare_input(root,{'schema_version':1,'tasks':tasks},as_of='2026-10-10')
    def plan(self,root):
        return prepare(root,[{'name':'合成大学','domains':['example.edu'],'urls':['https://example.edu/admissions']}],KEYWORDS,POLICY,as_of='2026-10-10')

    def test_frozen_plan_expands_queries_and_rejects_changed_input(self):
        with tempfile.TemporaryDirectory() as d:
            folder,plan=self.plan(Path(d))
            self.assertEqual(len(plan['jobs']),38)
            self.assertEqual({j['sort'] for j in plan['jobs'] if j.get('platform')=='dy'},{'general'})
            self.assertIn('2027',next(j['keyword'] for j in plan['jobs'] if j['type']=='social'))
            self.assertEqual(read_plan(folder)['plan_sha'],plan['plan_sha'])
            plan['jobs'][0]['unit']='变更输入';write_json(folder/'plan.json',plan)
            with self.assertRaises(ValueError):read_plan(folder)

    def test_private_or_session_source_cannot_be_requested(self):
        with patch('gradheat_python.collection_fetch.socket.getaddrinfo',return_value=[(None,None,None,None,('127.0.0.1',80))]):
            with self.assertRaises(ValueError):allowed_url('https://example.edu/data',['example.edu'])
        for url in ['https://user:pw@example.edu/data','https://example.edu/data?token=private','https://other.edu/data']:
            with self.assertRaises(ValueError):allowed_url(url,['example.edu'],resolve=False)

    def test_cached_original_does_not_refetch_and_tamper_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d);url='https://example.edu/doc'
            raw=folder/'document.txt';raw.write_bytes(b'synthetic public material')
            item={'url':url,'state':'fetched','raw_path':str(raw),'sha256':hashlib.sha256(raw.read_bytes()).hexdigest()}
            write_json(folder/(hashlib.sha256(url.encode()).hexdigest()+'.json'),item)
            with patch('gradheat_python.collection_fetch.allowed_url',return_value=url),patch('gradheat_python.collection_fetch.requests.get') as request:
                self.assertEqual(fetch(url,['example.edu'],folder,{}),item)
                request.assert_not_called()
                raw.write_bytes(b'changed')
                with self.assertRaises(ValueError):fetch(url,['example.edu'],folder,{})

    def test_interrupted_request_marker_never_grants_refetch(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d);url='https://example.edu/doc'
            (folder/(hashlib.sha256(url.encode()).hexdigest()+'.request')).write_text('started')
            with patch('gradheat_python.collection_fetch.allowed_url',return_value=url),patch('gradheat_python.collection_fetch.requests.get') as request:
                self.assertEqual(fetch(url,['example.edu'],folder,{})['state'],'interrupted-request')
                request.assert_not_called()

    def test_failed_official_pages_do_not_become_complete(self):
        with tempfile.TemporaryDirectory() as d,patch('gradheat_python.collection_fetch.fetch',return_value={'url':'https://example.edu','state':'failed'}),patch('gradheat_python.collection_fetch.time.sleep'):
            result=official({'name':'合成大学','domains':['example.edu'],'urls':['https://example.edu']},Path(d),POLICY['official'],KEYWORDS,time.monotonic()+30)
            self.assertFalse(result['scope_complete']);self.assertEqual(result['state'],'partial')

    def test_journal_restores_latest_job_and_detects_corruption(self):
        with tempfile.TemporaryDirectory() as d:
            folder,plan=self.plan(Path(d));state=load_state(folder);job=plan['jobs'][0]['id']
            state['jobs'][job]={'state':'running'};checkpoint(folder,state,job)
            state['jobs'][job]={'state':'committed'};checkpoint(folder,state,job)
            self.assertEqual(load_state(folder)['jobs'][job]['state'],'committed')
            journal=folder/'events.jsonl';journal.write_text(journal.read_text().replace('committed','failed'))
            with self.assertRaises(ValueError):load_state(folder)

    def test_paused_platforms_leave_unattempted_jobs_and_no_browser_calls(self):
        from contextlib import nullcontext
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);folder,plan=self.plan(root)
            with patch.object(cli,'ROOT',root),patch.object(cli.social,'collector_lock',side_effect=lambda *a:nullcontext()),patch('run_daily_update.local_lock',side_effect=lambda:nullcontext()),patch.object(cli.social,'platform_health',return_value={p:{'state':'needs-human'} for p in ('xhs','dy','zhihu','bili')}),patch.object(cli.social,'run') as browser:
                result=cli.run(folder,max_jobs=1,hours=.01,channels=['social'])
            browser.assert_not_called();self.assertEqual(result['never_attempted'],len(plan['jobs']))
            self.assertEqual(result['states'],{'not-requested-platform-blocked':1})

    def test_single_input_preserves_literal_queries_order_and_accepts_retry_json(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            tasks=[{'platform':'知乎','query':'任意 关键字','limit':2},{'platform':'github','query':'kaoyan in:readme','limit':1},{'platform':'official','query':'招生目录'}]
            folder,plan=self.query_plan(root,tasks)
            self.assertEqual([j['type'] for j in plan['jobs']],['social','github','official'])
            self.assertTrue(plan['jobs'][0]['generic_search']);self.assertEqual(plan['jobs'][0]['keyword'],'任意 关键字')
            with patch.object(cli.social,'platform_health',return_value={}):cli.report(folder,plan,load_state(folder))
            retry=json.loads((folder/'incomplete.json').read_text(encoding='utf-8'))
            self.assertEqual(retry['tasks'],tasks)
            self.assertEqual(len(prepare_input(root,retry)[1]['jobs']),3)
            with self.assertRaises(ValueError):prepare_input(root,{'tasks':[{'platform':'xhs','query':'a','cookie':'secret'}]})

    def test_blocked_platform_and_malformed_response_do_not_stop_later_jobs(self):
        from contextlib import nullcontext
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);folder,plan=self.query_plan(root,[{'platform':'xhs','query':'blocked'},{'platform':'official','query':'bad-format'},{'platform':'github','repo':'test/public'}])
            with patch.object(cli,'ROOT',root),patch.object(cli.social,'collector_lock',side_effect=lambda *a:nullcontext()),patch('run_daily_update.local_lock',side_effect=lambda:nullcontext()),patch.object(cli.social,'platform_health',return_value={'xhs':{'state':'needs-human','reason':'verification'}}),patch.object(cli.social,'run') as browser,patch.object(cli,'official_search',side_effect=ValueError('format')),patch.object(cli,'github_search',return_value={'state':'collected','scope_complete':True,'documents':[]}) as github,patch.object(cli,'ingest',return_value={'database_state':'committed'}):
                result=cli.run(folder,hours=.01)
            browser.assert_not_called();github.assert_called_once()
            self.assertTrue(result['finished']);self.assertFalse(result['material_scope_complete'])
            retry=json.loads((folder/'incomplete.json').read_text(encoding='utf-8'))
            self.assertEqual(len(retry['tasks']),2);self.assertFalse(retry['failure_details'][0]['requested'])
            with patch.object(cli.social,'platform_health',return_value={}):
                cli.report(folder,plan,load_state(folder))

    def test_empty_social_content_is_a_gap_not_a_complete_sample(self):
        from contextlib import nullcontext
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);folder,plan=self.query_plan(root,[{'platform':'bili','query':'empty search'}])
            with patch.object(cli,'ROOT',root),patch.object(cli.social,'collector_lock',side_effect=lambda *a:nullcontext()),patch('run_daily_update.local_lock',side_effect=lambda:nullcontext()),patch.object(cli.social,'platform_health',return_value={}),patch.object(cli.social,'run',return_value={'state':'empty-sample','snapshots':0,'sampling_complete':True,'database_state':'committed'}) as browser:
                result=cli.run(folder,hours=.01)
            self.assertFalse(result['material_scope_complete']);self.assertEqual(result['states'],{'empty-sample':1})
            self.assertTrue(browser.call_args.kwargs['generic_search'])

    def test_official_challenge_records_gap_and_continues_other_domain(self):
        with tempfile.TemporaryDirectory() as d,patch('gradheat_python.collection_fetch.time.sleep'):
            unit={'name':'合成官网','domains':['a.edu.cn','b.edu.cn'],'urls':['https://a.edu.cn/one','https://a.edu.cn/two','https://b.edu.cn/three']}
            with patch('gradheat_python.collection_fetch.fetch',side_effect=[{'url':unit['urls'][0],'state':'needs-human'},{'url':unit['urls'][2],'state':'fetched','links':[]}]) as request:
                result=official(unit,Path(d),POLICY['official'],KEYWORDS,time.monotonic()+30)
            self.assertEqual(request.call_count,2);self.assertFalse(result['scope_complete'])
            self.assertEqual([r['state'] for r in result['documents']],['needs-human','not-requested-site-blocked','fetched'])

    def test_official_query_filters_third_party_and_keeps_multiple_official_domains(self):
        with tempfile.TemporaryDirectory() as d:
            job={'target':{'name':'合成官网','domains':[],'urls':[]},'query':'计算机招生','search_limit':8}
            discovery={'status':'healthy','results':[{'url':'https://a.edu.cn/one'},{'url':'https://thirdparty.com/two'},{'url':'https://b.ac.cn/three'}]}
            with patch('gradheat_python.collection_search.official',return_value={'documents':[],'state':'collected','scope_complete':True}) as acquire:
                result=official_search(job,Path(d),POLICY['official'],KEYWORDS,time.monotonic()+30,lambda q:discovery)
            self.assertEqual(acquire.call_args.args[0]['urls'],['https://a.edu.cn/one','https://b.ac.cn/three'])
            self.assertTrue(result['scope_complete'])

    def test_github_search_fixes_repository_selection_and_reuses_receipt(self):
        with tempfile.TemporaryDirectory() as d:
            job={'query':'keyword in:readme','search_limit':1}
            response={'items':[{'full_name':'test/repo','html_url':'https://github.com/test/repo','fork':False}],'incomplete_results':False,'total_count':10}
            with patch('gradheat_python.collection_search.github_api',return_value=response) as api,patch('gradheat_python.collection_search.repository',return_value={'documents':[],'scope_complete':True,'state':'fetched','commit':'a'*40}) as repo:
                result=github_search(job,Path(d),POLICY['github'],time.monotonic()+30)
                again=github_search(job,Path(d),POLICY['github'],time.monotonic()+30)
            self.assertTrue(result['scope_complete']);self.assertEqual(again,result);self.assertEqual(api.call_count,1)
            self.assertEqual(repo.call_args.args[0],'test/repo')

    def test_short_windows_checkpoint_paths_and_generic_selection(self):
        from social_evidence import select_related
        with tempfile.TemporaryDirectory() as d:
            folder,plan=self.query_plan(Path(d),[{'platform':'github','query':'test'}])
            root=Path('D:/aaopenclow-share/Graduate_school_selection')
            path=root/'.research/autonomous-collection'/folder.name/'github'/plan['jobs'][0]['id'][:16]/'repos'/('a'*16)/'raw'/(('a'*64)+'.json.tmp')
            self.assertLess(len(str(path)),260)
        self.assertEqual(select_related([{'title':'其他专业'},{'title':'校园日常'}],{'generic_search':True,'limit':1},lambda i:i['title']),[{'title':'其他专业'}])

    def test_partial_jobs_appear_in_missing_report(self):
        with tempfile.TemporaryDirectory() as d:
            folder,plan=self.plan(Path(d));state=load_state(folder)
            state['jobs'][plan['jobs'][0]['id']]={'state':'partial-committed','result':{'database_state':'committed','scope_complete':False}}
            with patch.object(cli.social,'platform_health',return_value={}):result=cli.report(folder,plan,state)
            gaps=json.loads((folder/'missing.json').read_text())
            self.assertFalse(result['material_scope_complete']);self.assertTrue(any(g['state']=='partial-committed' for g in gaps))

    def test_export_deduplicates_material_and_does_not_include_private_log(self):
        import zipfile
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);folder,plan=self.plan(root);job=plan['jobs'][0];child=folder/'official'/job['id'];child.mkdir(parents=True)
            raw=child/'original.txt';raw.write_bytes(b'synthetic public original');sha=hashlib.sha256(raw.read_bytes()).hexdigest()
            doc={'url':'https://example.edu/admissions','raw_path':str(raw),'sha256':sha,'state':'fetched'}
            write_json(child/'manifest.json',{'documents':[doc,doc],'scope_complete':True})
            (child/'private.log').write_text('synthetic private credential never exported')
            state=load_state(folder);state['jobs'][job['id']]={'state':'committed','folder':str(child),'result':{'database_state':'committed'}};write_json(folder/'state.json',state)
            with patch.object(cli,'ROOT',root),patch.object(cli.social,'platform_health',return_value={}):result=cli.export(folder)
            with zipfile.ZipFile(result['handoff']) as z:
                self.assertEqual(sum(n.startswith('materials/'+sha) for n in z.namelist()),1)
                self.assertFalse(any('private.log' in n for n in z.namelist()))


if __name__=='__main__':unittest.main()
