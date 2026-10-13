import asyncio,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tools/research'))
from social_evidence import zhihu_search_document
import zhihu_browser_search as browser_search
import collect_social_sources as social


class SearchRecoveryTests(unittest.TestCase):
    def test_raw_post_body_survives_missing_detail_and_does_not_invent_zero_metrics(self):
        content=dict(content_id='123',content_type='answer',title='合成<em>问题</em>',content_text='短摘要',content_url='https://www.zhihu.com/question/1/answer/123',voteup_count=0,comment_count=0)
        raw=dict(data=[dict(object=dict(id=123,type='answer',content='<h2>甲大学</h2><p>复试机试说明</p>',voteup_count=7,created_time=1700000000))])
        doc=zhihu_search_document(content,raw)
        self.assertIn('甲大学',doc['text']);self.assertIn('复试机试',doc['text'])
        self.assertEqual(doc['metrics'],dict(voteup_count=7,comment_count=None))
        self.assertEqual(doc['content_level'],'excerpt')
        self.assertEqual(doc['collection_route'],'zhihu-search-response')
        self.assertEqual(doc['title'],'合成问题')

    def test_ai_summary_is_not_discussion_and_foreign_post_cannot_supply_body(self):
        self.assertIsNone(zhihu_search_document(dict(content_type='ai_summary'),dict(data=[])))
        content=dict(content_id='123',content_type='article',title='合成标题',content_text='已公开摘要')
        raw=dict(data=[dict(object=dict(id=999,type='article',content='<p>其他帖子正文</p>',voteup_count=100))])
        doc=zhihu_search_document(content,raw)
        self.assertEqual(doc['text'],'已公开摘要');self.assertIsNone(doc['metrics']['voteup_count'])

    def test_search_route_filters_foreign_requests_and_generated_summaries(self):
        self.assertIsNone(browser_search.search_request('https://www.zhihu.com/api/v4/search_v3?q=foreign','synthetic'))
        self.assertIsNone(browser_search.search_request('https://evil.example/api/v4/search_v3?q=synthetic','synthetic'))
        raw=dict(data=[dict(object=dict(id='ai',type='ai_zhida',content='generated')),
                       dict(object=dict(id=123,type='article',title='合成择校',content='<p>公开正文</p>',voteup_count=3))])
        docs=browser_search.search_documents(raw,dict(keyword='synthetic',generic_search=True,limit=20))
        self.assertEqual(len(docs),1);self.assertEqual(docs[0]['content_id'],'123')

    def test_detail_restriction_survives_connection_failure_and_search_success(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(social,'ROOT',Path(directory)):
            social.set_platform_health('zhihu','needs-human','platform-access-refused','platform-detail')
            self.assertFalse(social.platform_paused('zhihu',social.platform_health()['zhihu']))
            social.set_platform_health('zhihu','transient-error','browser-connection-timeout')
            social.set_platform_health('zhihu','accessible')
            health=social.platform_health()['zhihu']
            self.assertEqual(health['state'],'partial-access');self.assertIn('platform-detail',health['restrictions'])
            social.set_platform_health('zhihu','needs-human','platform-access-refused','platform-search')
            self.assertTrue(social.platform_paused('zhihu',social.platform_health()['zhihu']))


class OwnedPageTests(unittest.IsolatedAsyncioTestCase):
    async def test_success_and_refusal_close_only_created_target(self):
        for status in (200,403):
            calls=[]
            class FakeConnection:
                async def call(self,method,params=None,root=False):
                    calls.append((method,params,root))
                    if method=='Target.createTarget':return dict(targetId='ours')
                    if method=='Target.attachToTarget':return dict(sessionId='owned-session')
                    if method=='Network.getResponseBody':return dict(body=json.dumps(dict(data=[dict(object=dict(id=123,type='article',title='合成文章',content='<p>公开正文</p>'))])),base64Encoded=False)
                    return {}
                async def event(self):return events.pop(0)
            events=[dict(method='Network.responseReceived',params=dict(requestId='ours-response',response=dict(url='https://www.zhihu.com/api/v4/search_v3?q=synthetic&offset=0&limit=20',status=status))),dict(method='Network.loadingFinished',params=dict(requestId='ours-response'))]
            result=dict(observed_requests=[],public_responses=[],documents=[])
            await browser_search.observe_search(FakeConnection(),dict(keyword='synthetic',generic_search=True,limit=20),result)
            self.assertEqual(result['state'],'collected' if status==200 else 'needs-human')
            self.assertEqual(calls[-1],('Target.closeTarget',dict(targetId='ours'),True))
            self.assertFalse(any(method in ('Target.getTargets','Target.setAutoAttach','Browser.close','Network.getCookies') for method,_,_ in calls))
