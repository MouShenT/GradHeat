"""GradHeat adapter: reuse installed MediaCrawler clients without editing shared config.

Own one page only; detach the connection, never close the user's context/browser.
This is an explicitly requested MediaCrawler collection job, not a general browser tool.
"""
import argparse
import asyncio
import hashlib
import json
import logging
import os
from pathlib import Path
import sys
from urllib.parse import parse_qsl, quote, urlsplit, urlunsplit
import urllib.request
import secrets
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

from social_evidence import clean_url, count, document, encode, exposed_metrics, note_items, now, public_response, select_related, validate_search, video_items, PlatformVerificationRequired
from open_social_login import debugger_endpoint

ROOT = Path(__file__).resolve().parents[2]


def is_xhs_verification_error(exc):
    # This exact prefix is emitted only by MediaCrawler's HTTP 461/471
    # branch. Inspect it in memory; never retain its verification tokens.
    attempt=getattr(exc,'last_attempt',None)
    cause=attempt.exception() if attempt is not None else exc
    return str(cause).startswith('CAPTCHA appeared, request failed,')


def execute(task):
    try:
        return asyncio.run(asyncio.wait_for(collect(task), timeout=120))
    except TimeoutError:
        output = Path(task['checkpoint'])
        result = json.loads(output.read_text(encoding='utf-8')) if output.exists() else dict(documents=[])
        result.update(state='partial', reason='worker-budget-expired')
        return result


def serve(platform, port):
    """One isolated platform process: cache imports, never share config across platforms."""
    registry = ROOT / '.research/social/worker-runtime' / (platform + '.json')
    registry.parent.mkdir(parents=True,exist_ok=True)
    token = secrets.token_hex(32)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            if self.path!='/collect' or self.headers.get('Authorization')!='Bearer '+token:
                self.send_error(403);return
            try:
                size=int(self.headers.get('Content-Length',0))
                if not 0<size<=65536:raise ValueError('Invalid task size')
                task=json.loads(self.rfile.read(size))
                checkpoint=Path(task['checkpoint']).resolve()
                if not checkpoint.is_relative_to((ROOT/'.research/social/runs').resolve()):raise ValueError('Checkpoint outside collection runs')
                if task['platform']!=platform or not 1<=task['limit']<=20:raise ValueError('Invalid platform/budget')
                if Path(task['collector']).resolve()!=Path('D:/aaopenclow-share/mediacrawler').resolve():raise ValueError('Unknown collector')
                result=execute(task)
                result.update(worker_mode='isolated-platform-process',worker_pid=os.getpid())
                payload=encode(result).encode('utf-8')
                self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
            except Exception as exc:
                payload=encode(dict(state='partial',reason='local-worker-failed',error_type=type(exc).__name__,documents=[])).encode('utf-8')
                self.send_response(500);self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
    class IdleServer(HTTPServer):
        idle=False
        def handle_timeout(self):self.idle=True
    server=IdleServer(('127.0.0.1',port),Handler)
    temporary=registry.with_suffix('.tmp')
    temporary.write_text(encode(dict(platform=platform,port=server.server_port,pid=os.getpid(),token=token)),encoding='utf-8')
    temporary.replace(registry)
    print(encode(dict(worker_ready=platform,port=server.server_port,pid=os.getpid())),flush=True)
    server.timeout=300
    try:
        while True:
            # Exit after five idle minutes. HTTPServer does not close Chrome.
            server.idle=False
            server.handle_request()
            if server.idle or not registry.exists():break
    finally:
        server.server_close()
        if registry.exists() and json.loads(registry.read_text(encoding='utf-8')).get('pid')==os.getpid():registry.unlink()


def pooled_collect(task):
    registry=ROOT/'.research/social/worker-runtime'/(task['platform']+'.json')
    if not registry.exists():return None
    metadata=json.loads(registry.read_text(encoding='utf-8'))
    request=urllib.request.Request(f'http://127.0.0.1:{metadata["port"]}/collect',
        data=encode(task).encode('utf-8'),headers={'Content-Type':'application/json','Authorization':'Bearer '+metadata['token']},method='POST')
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request,timeout=125) as response:return json.load(response)
    except urllib.error.URLError as exc:
        # Refusal means no worker accepted this query. Other failures are not
        # retried: the platform may already have handled the original request.
        reason=getattr(exc,'reason',None)
        if isinstance(reason,ConnectionRefusedError) or getattr(reason,'winerror',None)==10061:return None
        return dict(state='partial',reason='local-worker-response-unavailable',error_type=type(exc).__name__,documents=[])
    except TimeoutError:
        return dict(state='partial',reason='local-worker-response-timeout',error_type='TimeoutError',documents=[])


def cdp_health(port):
    try:
        return bool(debugger_endpoint(port))
    except Exception:
        return False


def capture_requests(client, responses, platform):
    # Disable decorators' retries. Never archive login/profile/session responses.
    request = getattr(type(client).request, '__wrapped__', type(client).request)
    async def once(*args, **kwargs):
        raw = await request(client, *args, **kwargs)
        url = str(kwargs.get('url') or (args[1] if len(args) > 1 else ''))
        routes = {'xhs': ('/search/notes', '/feed'), 'zhihu': ('/search_v3',),
            'dy': ('/general/search/',), 'bili': ('/search/type', '/view/detail')}
        if isinstance(raw, (dict, list)) and any(route in url for route in routes[platform]):
            responses.append(public_response(raw))
            if '/search/' in url or '/search_v3' in url:
                validate_search(platform, raw)
        return raw
    client.request = once


async def close_owned_page(page):
    if page is not None and not page.is_closed():
        await page.close()


async def collect(task):
    result = dict(state='needs-human', reason='chrome-debugging-unavailable', documents=[],
        platform=task['platform'], keyword=task['keyword'], observed_at=now(),
        detail_budget=task['limit'], search_page_size=15 if task['platform'] == 'dy' else 20, pages_requested=1,
        detail_selection='first-page-relevance-v2', eligibility_state='requires-exam-scope-check')
    if not cdp_health(task['cdp_port']):
        return result
    repo = Path(task['collector']).resolve()
    sys.path.insert(0, str(repo))
    os.chdir(repo)
    import config
    overrides = dict(ENABLE_CDP_MODE=True, CDP_CONNECT_EXISTING=True,
        AUTO_CLOSE_BROWSER=False, ENABLE_IP_PROXY=False, DISABLE_SSL_VERIFY=False,
        ENABLE_GET_COMMENTS=False, ENABLE_GET_SUB_COMMENTS=False, ENABLE_GET_MEDIA=False,
        ENABLE_GET_WORDCLOUD=False, MAX_CONCURRENCY_NUM=1, COOKIES='',
        CRAWLER_MAX_SLEEP_SEC=3, PLATFORM=task['platform'], KEYWORDS=task['keyword'])
    for key, value in overrides.items():
        setattr(config, key, value)
    from tools import utils
    utils.logger.setLevel(logging.CRITICAL)
    from playwright.async_api import async_playwright
    from var import source_keyword_var, crawler_type_var
    source_keyword_var.set(task['keyword'])
    crawler_type_var.set('search')
    page = None
    responses = []
    def checkpoint():
        if task.get('checkpoint'):
            Path(task['checkpoint']).write_text(encode(result), encoding='utf-8')
    async with async_playwright() as p:
        try:
            browser = await p.chromium.connect_over_cdp(debugger_endpoint(task['cdp_port']), timeout=15000)
            if not browser.contexts:
                result['reason'] = 'existing-browser-context-missing'
                return result
            ctx = browser.contexts[0]
            page = await ctx.new_page()
            if task['platform'] == 'xhs':
                from media_platform.xhs.core import XiaoHongShuCrawler
                from media_platform.xhs.field import SearchSortType
                from media_platform.xhs.help import get_search_id
                crawler = XiaoHongShuCrawler()
                await page.goto(crawler.index_url, wait_until='domcontentloaded', timeout=25000)
                crawler.browser_context, crawler.context_page = ctx, page
                client = await crawler.create_xhs_client(None)
                capture_requests(client, responses, 'xhs')
                sort = SearchSortType.LATEST if task['sort'] == 'latest' else SearchSortType.MOST_POPULAR if task['sort'] == 'popular' else SearchSortType.GENERAL
                raw = await client.get_note_by_keyword(task['keyword'], search_id=get_search_id(), page=1, sort=sort)
                validate_search('xhs', raw)
                result['has_more'] = raw.get('has_more')
                result['search_items'] = len(raw.get('items', []))
                selected = select_related(list(note_items(raw, 100)),task,lambda x:(x.get('note_card') or {}).get('display_title') or x.get('title'))
                result['related_cards_selected'] = len(selected)
                for item in selected:
                    await asyncio.sleep(3)
                    detail = await client.get_note_by_id(item['id'], item.get('xsec_source') or 'pc_search', item.get('xsec_token') or '')
                    if detail:
                        result['documents'].append(document('xhs', public_response(detail), full=True))
                        checkpoint()
            elif task['platform'] == 'zhihu':
                from media_platform.zhihu.core import ZhihuCrawler
                from media_platform.zhihu.field import SearchSort
                crawler = ZhihuCrawler()
                url = 'https://www.zhihu.com/search?type=content&q=' + quote(task['keyword'])
                await page.goto(url, wait_until='domcontentloaded', timeout=25000)
                await asyncio.sleep(3)
                crawler.browser_context, crawler.context_page = ctx, page
                client = await crawler.create_zhihu_client(None)
                client.default_headers['referer'] = url
                capture_requests(client, responses, 'zhihu')
                sort = SearchSort.CREATE_TIME if task['sort'] == 'latest' else SearchSort.UPVOTED_COUNT if task['sort'] == 'popular' else SearchSort.DEFAULT
                found = await client.get_note_by_keyword(task['keyword'], page=1, page_size=20, sort=sort)
                search_response = responses[-1] if responses else {}
                result['search_items'] = len(found)
                seen = set()
                selected_cards = select_related(found,task,lambda x:x.title)
                result['related_cards_selected'] = len(selected_cards)
                for content in selected_cards:
                    key = (content.content_type, content.content_id)
                    if key in seen:
                        continue
                    seen.add(key)
                    await asyncio.sleep(3)
                    detail = None
                    if content.content_type == 'article':
                        detail = await client.get_article_info(content.content_id)
                    elif content.content_type == 'answer':
                        detail = await client.get_answer_info(content.question_id, content.content_id)
                    selected = detail or content
                    obj = selected.model_dump()
                    doc = document('zhihu', obj, full=detail is not None)
                    # Pydantic defaults conceal missing counts; derive only from exposed raw JSON.
                    doc['metrics'] = exposed_metrics(search_response, content.content_id, content.content_type) or {k: None for k in ('voteup_count', 'comment_count')}
                    doc['metrics_context'] = 'visible-search-result-at-observation-time'
                    result['documents'].append(doc)
                    checkpoint()
                    if len(result['documents']) >= task['limit']:
                        break
            elif task['platform'] == 'dy':
                from media_platform.douyin.core import DouYinCrawler
                crawler = DouYinCrawler()
                network = asyncio.Queue()
                request_metadata = []
                async def observe_search(response):
                    parts = urlsplit(response.url)
                    if parts.hostname != 'www.douyin.com' or not parts.path.startswith('/aweme/v1/web/general/search/'):
                        return
                    if len(request_metadata) >= 6:
                        return
                    query = dict(parse_qsl(parts.query))
                    metadata = dict(url=urlunsplit((parts.scheme, parts.netloc, parts.path, '', '')),
                        method=response.request.method,parameter_names=sorted(query),status=response.status,
                        content_type=response.headers.get('content-type'),trigger='normal-browser-search-page',
                        keyword_matches=not query.get('keyword') or query['keyword']==task['keyword'])
                    request_metadata.append(metadata)
                    result['observed_requests'] = request_metadata
                    if response.status != 200:
                        return
                    try:
                        raw = await response.json()
                    except Exception:
                        metadata['parse_state'] = 'non-json-response'
                        return
                    metadata.update(parse_state='json',top_level_keys=sorted(raw) if isinstance(raw,dict) else [],
                        data_type=type(raw.get('data')).__name__ if isinstance(raw,dict) else type(raw).__name__)
                    if isinstance(raw,dict):responses.append(public_response(raw))
                    if not isinstance(raw, dict) or not isinstance(raw.get('data'), list):
                        return
                    if query.get('keyword') and query['keyword'] != task['keyword']:
                        return
                    try:
                        filters = json.loads(query.get('filter_selected') or '{}')
                    except ValueError:
                        filters = {}
                    observed_sort = {'0': 'general', '1': 'popular', '2': 'latest'}.get(
                        str(filters.get('sort_type', query.get('sort_type', 0))), 'unknown')
                    metadata.update(requested_count=count(query.get('count')),sort=observed_sort,accepted=True)
                    await network.put(raw)
                page.on('response', observe_search)
                await page.goto('https://www.douyin.com/search/' + quote(task['keyword']),
                    wait_until='domcontentloaded', timeout=25000)
                crawler.browser_context, crawler.context_page = ctx, page
                client = await crawler.create_douyin_client(None)
                result['login_confirmed'] = await client.pong(ctx)
                # Use the browser's real search request, without replaying guessed signatures.
                raw = await asyncio.wait_for(network.get(), timeout=25)
                result['collection_route'] = 'browser-network-observation'
                result['observed_requests'] = request_metadata
                accepted = next(m for m in request_metadata if m.get('accepted'))
                result['actual_sort'] = accepted['sort']
                result['search_page_size'] = accepted['requested_count']
                result['requested_sort'] = task['sort']
                validate_search('dy', raw)
                result['search_items'] = len(raw['data'])
                result['has_more'] = raw.get('has_more')
                selected = select_related(list(video_items('dy',raw,100)),task,lambda x:x.get('desc'))
                result['related_cards_selected'] = len(selected)
                for item in selected:
                    result['documents'].append(document('dy', public_response(item)))
                    checkpoint()
            elif task['platform'] == 'bili':
                from media_platform.bilibili.core import BilibiliCrawler
                from media_platform.bilibili.field import SearchOrderType
                crawler = BilibiliCrawler()
                await page.goto(crawler.index_url, wait_until='domcontentloaded', timeout=25000)
                crawler.browser_context, crawler.context_page = ctx, page
                crawler.user_agent = await page.evaluate('() => navigator.userAgent')
                client = await crawler.create_bilibili_client(None)
                capture_requests(client, responses, 'bili')
                sort = SearchOrderType.LAST_PUBLISH if task['sort'] == 'latest' else SearchOrderType.MOST_CLICK if task['sort'] == 'popular' else SearchOrderType.DEFAULT
                raw = await client.search_video_by_keyword(task['keyword'], page=1, page_size=20, order=sort)
                validate_search('bili', raw)
                result['search_items'] = len(raw['result'])
                selected = select_related(list(video_items('bili',raw,100)),task,lambda x:x.get('title'))
                result['related_cards_selected'] = len(selected)
                for item in selected:
                    await asyncio.sleep(3)
                    detail = await client.get_video_info(aid=item.get('aid'), bvid=item.get('bvid'))
                    if not isinstance(detail, dict) or not isinstance(detail.get('View'), dict):
                        raise ValueError('Bilibili detail lacks video information')
                    result['documents'].append(document('bili', public_response(detail)))
                    checkpoint()
            result['state'] = 'collected' if result['documents'] else 'empty-sample'
            result['reason'] = None if result['documents'] else 'no-related-detail-in-first-page'
        except PlatformVerificationRequired:
            result.update(state='needs-human', reason='platform-verification-required',
                handoff_url=clean_url(page.url) if page else None)
            if page and not task.get('generic_search'):
                await page.bring_to_front()
        except (TimeoutError, asyncio.TimeoutError):
            result.update(state='partial',reason='page-or-search-response-timeout',error_type='TimeoutError')
        except Exception as exc:
            # Do not persist exception strings containing response bodies or session URLs.
            attempt=getattr(exc,'last_attempt',None)
            cause=attempt.exception() if attempt is not None else exc
            if task['platform']=='xhs' and is_xhs_verification_error(exc):
                result.update(state='needs-human',reason='platform-verification-required',
                    handoff_url=clean_url(page.url) if page else None,error_type='PlatformVerificationRequired')
                if page and not task.get('generic_search'):await page.bring_to_front()
            else:
                result.update(state='partial' if result['documents'] else 'needs-human',
                    reason='platform-access-or-login-check', error_type=type(cause).__name__,
                    outer_error_type=type(exc).__name__ if cause is not exc else None)
        finally:
            if task.get('generic_search') or result.get('reason') != 'platform-verification-required':
                await close_owned_page(page)
    result['public_responses'] = responses
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--task', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--serve',choices=['xhs','zhihu','dy','bili'])
    parser.add_argument('--port',type=int,default=0)
    args = parser.parse_args()
    if args.serve:
        serve(args.serve,args.port);return
    if not args.task or not args.output:parser.error('--task and --output are required')
    task = json.loads(args.task.read_text(encoding='utf-8'))
    if task['platform'] not in ('xhs', 'zhihu', 'dy', 'bili') or not 1 <= task['limit'] <= 20:
        raise ValueError('Unsupported platform or sample budget')
    task['checkpoint'] = str(args.output.resolve())
    # Human handoff owns the browser. Wait in the task process, without sending
    # new platform requests or reclassifying the pause as a normal empty search.
    if task.get('generic_search') and (ROOT/'.research/social/human-browser-handoff.json').exists():
        result=dict(state='needs-human',reason='browser-owned-by-human',documents=[])
    else:
        while (ROOT/'.research/social/human-browser-handoff.json').exists():time.sleep(1)
        # Existing pooled workers can have older selectors imported. Generic
        # input tasks use this exact adapter process, never a stale pool.
        result=None if task.get('generic_search') else pooled_collect(task)
        if result is None:result=execute(task)
    if result.get('reason')=='platform-verification-required' or (
            task['platform']=='xhs' and result.get('reason')=='platform-access-or-login-check'
            and result.get('error_type') in ('Exception','PlatformAccessError','IPBlockError')):
        # Existing supervisors may have imported an older adapter. Persist the
        # platform gate here too, including partial details, so they pause.
        from collect_social_sources import set_platform_health
        set_platform_health(task['platform'],'needs-human',result['reason'])
    args.output.write_text(encode(result), encoding='utf-8')


if __name__ == '__main__':
    main()
