import asyncio
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/research'))
from social_evidence import count, document, encode, exposed_metrics, note_items, public_response, reviewed_observations, select_related, validate_search, video_items, PlatformVerificationRequired
import collect_social_sources
from collect_social_sources import safe_social_url, units_for_day
from mediacrawler_worker import capture_requests, close_owned_page, is_xhs_verification_error
from open_social_login import select_browser_port, debugger_endpoint
from gradheat.vm_connection import ssh_connection
sys.path.insert(0, str(ROOT / 'python_service'))
from gradheat_core.information_match import identity


class SocialCollectionTests(unittest.TestCase):
    def test_cdp_endpoint_uses_exact_local_path_without_proxy(self):
        endpoint='ws://127.0.0.1:9222/devtools/browser/synthetic'
        opener=MagicMock()
        opener.open.return_value.__enter__.return_value.read.return_value=json.dumps({'Browser':'Chrome/synthetic','webSocketDebuggerUrl':endpoint}).encode()
        with patch('open_social_login.urllib.request.build_opener',return_value=opener):
            self.assertEqual(debugger_endpoint(9222),endpoint)
        self.assertEqual(opener.open.call_args.args[0],'http://127.0.0.1:9222/json/version')

    def test_cdp_endpoint_rejects_remote_or_wrong_port_websocket(self):
        opener=MagicMock()
        for endpoint in ('ws://other.example:9222/devtools/browser/synthetic','ws://127.0.0.1:9223/devtools/browser/synthetic'):
            opener.open.return_value.__enter__.return_value.read.return_value=json.dumps({'Browser':'Chrome/synthetic','webSocketDebuggerUrl':endpoint}).encode()
            with patch('open_social_login.urllib.request.build_opener',return_value=opener),self.assertRaises(ValueError):
                debugger_endpoint(9222)

    def test_xhs_generic_captcha_error_is_detected_without_storing_tokens(self):
        error=Exception('CAPTCHA appeared, request failed, Verifyuuid: private-test-token')
        self.assertTrue(is_xhs_verification_error(error))
        self.assertFalse(is_xhs_verification_error(Exception('Note not found')))
        class Wrapped(Exception):
            class Attempt:
                def exception(self):return error
            last_attempt=Attempt()
        self.assertTrue(is_xhs_verification_error(Wrapped()))

    def test_relevance_uses_whole_page_and_excludes_unrelated_recruitment(self):
        rows=[dict(title='中国人民大学附属中学招聘教师'),dict(title='人大应用统计考研'),dict(title='<b>中国人民大学</b>计算机硕士2026拟录取名单'),dict(title='408考研院校分析')]
        selected=select_related(rows,dict(unit='中国人民大学',keyword='中国人民大学 2027 计算机 考研',limit=2),lambda x:x['title'])
        self.assertEqual(selected,rows[2:])
        self.assertEqual(select_related(rows[:2],dict(keyword='中国人民大学 计算机 考研',limit=2),lambda x:x['title']),[])

    def test_stale_full_run_marker_does_not_block_daily_collection(self):
        with tempfile.TemporaryDirectory() as temp,patch.object(collect_social_sources,'ROOT',Path(temp)):
            marker=Path(temp)/'.research/social/full-run-active.json';marker.parent.mkdir(parents=True)
            marker.write_text('{}')
            with collect_social_sources.collector_lock(Path(temp),'full-run'):
                self.assertTrue(collect_social_sources.full_collection_active())
                self.assertTrue(marker.exists())
            self.assertFalse(collect_social_sources.full_collection_active())
            self.assertFalse(marker.exists())

    def test_final_page_and_duplicates(self):
        response = dict(has_more=False, items=[{'id': '1'}, {'id': '1'},
            {'id': 'hot', 'model_type': 'hot_query'}, {'id': '2'}])
        self.assertEqual([r['id'] for r in note_items(response, 2)], ['1', '2'])

    def test_tokens_removed_official_query_kept(self):
        raw = dict(cookie='private', xsec_token='secret', author=dict(id='person', name='机构'),
            text='https://www.xiaohongshu.com/explore/1?xsec_token=secret&xsec_source=pc_search',
            official='https://example.edu.cn/show?keyId=12')
        safe = public_response(raw)
        self.assertNotIn('secret', encode(safe))
        self.assertNotIn('person', encode(safe))
        self.assertNotIn('cookie', safe)
        self.assertIn('keyId=12', safe['official'])

    def test_unknown_counts_stay_unknown(self):
        self.assertIsNone(count(None))
        self.assertIsNone(count('1万+'))
        self.assertEqual(count('0'), 0)
        self.assertEqual(count('1,234'), 1234)

    def test_zhihu_counts_match_the_content_not_other_results(self):
        raw = dict(data=[dict(object=dict(type='article', id=9, voteup_count=999)),
            dict(object=dict(type='answer', id=1, voteup_count=888)),
            dict(object=dict(type='article', id=1, voteup_count=0))])
        self.assertEqual(exposed_metrics(raw, '1', 'article'), dict(voteup_count=0, comment_count=None))
        self.assertIsNone(exposed_metrics(raw, 'missing', 'article'))

    def test_rounded_xhs_count_keeps_its_public_display(self):
        doc = document('xhs', dict(note_id='1', interact_info={'liked_count':'1万+'}))
        self.assertIsNone(doc['metrics']['liked_count'])
        self.assertEqual(doc['metrics_display']['liked_count'], '1万+')

    def test_video_search_errors_are_not_empty_samples(self):
        with self.assertRaises(ValueError):validate_search('dy', dict(status_code=1, data=[]))
        with self.assertRaises(ValueError):validate_search('bili', dict(message='login required'))
        validate_search('dy', dict(status_code=0, data=[]))
        validate_search('bili', dict(result=[]))
        with self.assertRaises(PlatformVerificationRequired):
            validate_search('dy', dict(status_code=0, data=[],
                search_nil_info=dict(search_nil_type='verify_check')))

    def test_douyin_mixed_cards_deduplicate_before_budget(self):
        raw = dict(status_code=0, data=[dict(aweme_mix_info=dict(mix_items=[])),
            dict(aweme_info=dict(aweme_id='1')), dict(aweme_info=dict(aweme_id='1')),
            dict(aweme_mix_info=dict(mix_items=[dict(aweme_id='2')]))])
        self.assertEqual([r['aweme_id'] for r in video_items('dy', raw, 2)], ['1', '2'])

    def test_video_description_is_not_a_transcript_and_unknown_counts_are_not_zero(self):
        doc = document('dy', public_response(dict(aweme_id='1', desc='2027考研408',
            author=dict(uid='private-person'), statistics=dict(digg_count=0, play_count=0))))
        self.assertEqual(doc['content_level'], 'video-description')
        self.assertEqual(doc['transcript_state'], 'not-collected')
        self.assertEqual(doc['metrics']['digg_count'], 0)
        self.assertIsNone(doc['metrics']['play_count'])
        self.assertEqual(doc['metrics_display']['play_count'], 0)
        self.assertNotIn('private-person', encode(doc))
        bili = document('bili', public_response(dict(View=dict(bvid='BV1example', desc='专业目录',
            owner=dict(mid=10), stat=dict(view=45, like=0)))))
        self.assertEqual(bili['metrics']['view'], 45)
        self.assertIsNone(bili['metrics']['reply'])
        self.assertEqual(bili['url'], 'https://www.bilibili.com/video/BV1example')

    def test_signed_navigation_values_are_not_archived(self):
        raw = dict(sec_uid='secret-person', uifid='secret-session',
            url='https://www.douyin.com/video/1?msToken=secret-session&a_bogus=secret-sign')
        safe = public_response(raw)
        self.assertNotIn('secret-', encode(safe))
        self.assertIn('sec_uid_hash', safe)

    def test_capture_skips_profile_and_validates_search(self):
        class Client:
            response = {}
            async def request(self, method, url):return self.response
        client = Client()
        responses = []
        capture_requests(client, responses, 'bili')
        client.response = dict(isLogin=True, email='private')
        asyncio.run(client.request('GET', 'https://api.bilibili.com/x/web-interface/nav'))
        self.assertEqual(responses, [])
        client.response = dict(result=[])
        asyncio.run(client.request('GET', 'https://api.bilibili.com/x/web-interface/wbi/search/type'))
        self.assertEqual(responses, [dict(result=[])])
        client.response = dict(message='wrong shape')
        with self.assertRaises(ValueError):
            asyncio.run(client.request('GET', 'https://api.bilibili.com/x/web-interface/wbi/search/type'))

    def test_vm_ip_change_keeps_strict_trusted_key_check(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'contracts').mkdir()
            (root / 'contracts/runtime-connections.json').write_text(encode(dict(
                vm_host='192.168.43.131', vm_user='ms', host_key_alias='192.168.43.150')), encoding='utf-8')
            ssh, target = ssh_connection(root)
            self.assertIn('StrictHostKeyChecking=yes', ssh)
            self.assertIn('HostKeyAlias=192.168.43.150', ssh)
            self.assertEqual(target, 'ms@192.168.43.131')

    def test_resume_keeps_frozen_manifest_and_reports_retry(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(collect_social_sources, 'ROOT', Path(temp)):
            root = Path(temp)
            folder = root / '.research/social/runs/test-run'
            folder.mkdir(parents=True)
            original = folder / 'doc.json'
            original.write_text(encode(dict(text='2026复试线')), encoding='utf-8')
            manifest = dict(run_id='test-run', state='collected', snapshots=[dict(
                source_artifact=str(original), source_sha256=hashlib.sha256(original.read_bytes()).hexdigest())], candidates=[])
            path = folder / 'manifest.json'
            path.write_text(encode(manifest), encoding='utf-8')
            frozen = path.read_bytes()
            with patch.object(collect_social_sources, 'ingest', side_effect=TimeoutError):
                result = collect_social_sources.resume(path)
            self.assertEqual(result['database_state'], 'needs-retry')
            self.assertEqual(path.read_bytes(), frozen)
            with patch.object(collect_social_sources, 'ingest', return_value={'readback':'verified'}) as ingest:
                result = collect_social_sources.resume(path)
            ingest.assert_called_once_with(manifest, folder)
            self.assertEqual(result['database_state'], 'committed')
            original.write_text('{}', encoding='utf-8')
            with self.assertRaises(ValueError):collect_social_sources.resume(path)

    def test_login_launcher_chooses_free_port_without_stopping_occupant(self):
        import socket
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            listener.listen()
            port = listener.getsockname()[1]
            with patch('open_social_login.browser_health', return_value=False):
                self.assertGreater(select_browser_port(port), port)
            self.assertEqual(listener.getsockname()[1], port)

    def test_legacy_xhs_includes_videos_and_old_content(self):
        doc = document('xhs', dict(note_id='1', type='video', time=1700000000000,
            desc='2025考研', image_list='https://image.example/1.jpg', creator_hash='author'), full=True)
        self.assertEqual(doc['content_type'], 'video')
        self.assertTrue(doc['published_at'].startswith('2023'))
        self.assertEqual(doc['image_urls'], ['https://image.example/1.jpg'])
        self.assertEqual(doc['author_hash'], 'author')

    def test_close_only_own_page(self):
        class Page:
            closed = False
            def is_closed(self):return self.closed
            async def close(self):self.closed = True
        page = Page()
        asyncio.run(close_owned_page(page))
        self.assertTrue(page.closed)

    def test_redirect_allowlist_and_rotation(self):
        self.assertFalse(safe_social_url('https://www.zhihu.com/signin'))
        self.assertFalse(safe_social_url('http://127.0.0.1/'))
        self.assertTrue(safe_social_url('https://zhuanlan.zhihu.com/p/123'))
        units = ['a', 'b', 'c', 'd']
        self.assertNotEqual(units_for_day(units, '2026-10-05', 2), units_for_day(units, '2026-10-06', 2))

    def test_professional_branch_alias_and_academic_distinction(self):
        row = dict(unit='北京邮电大学', year=2026, department='计算机学院')
        a = identity(dict(row, major_name='电子信息-计算机方向'), 'history')
        b = identity(dict(row, major_name='计算机技术（专硕）'), 'history')
        self.assertEqual((a['major'], a['degree']), (b['major'], b['degree']))
        academic = identity(dict(row, major_name='计算机科学与技术（学硕）'), 'history')
        self.assertNotEqual(a['major'], academic['major'])

    def test_review_gate_and_original_tampering(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            folder = root / '.research/social'
            folder.mkdir(parents=True)
            artifact = folder / 'doc.json'
            artifact.write_text(encode(dict(text='2027软件工程考101+201+301+408')), encoding='utf-8')
            row = dict(review_state='evidence-checked', lineage_state='resolved',
                source_artifact=str(artifact), source_sha256=hashlib.sha256(artifact.read_bytes()).hexdigest(),
                quote='2027软件工程考101+201+301+408', fields={'subjects': ['101', '201', '301', '408']},
                field_evidence={'subjects': '101+201+301+408'}, year=2027, unit='某大学', major_name='软件工程', origin_id='institution:A')
            claims = folder / 'claims-reviewed.json'
            claims.write_text(encode([dict(row, lineage_state='unknown')]), encoding='utf-8')
            self.assertEqual(reviewed_observations(root), [])
            claims.write_text(encode([row]), encoding='utf-8')
            self.assertEqual(len(reviewed_observations(root)), 1)
            artifact.write_text('{}', encoding='utf-8')
            with self.assertRaises(ValueError):reviewed_observations(root)


if __name__ == '__main__':unittest.main()
