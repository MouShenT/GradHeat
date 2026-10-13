"""Observe normal Zhihu search on one owned Chrome target, preserving user tabs.

Uses MediaCrawler's existing websockets dependency. No cookie export, detail API,
signature generation, browser-wide auto-attach or challenge retries.
"""
import asyncio
import base64
from collections import deque
import json
from urllib.parse import parse_qsl, quote, urlsplit

from open_social_login import debugger_endpoint
from social_evidence import now, public_response, select_related, validate_search, zhihu_search_document


class OwnedTargetConnection:
    def __init__(self, websocket):
        self.websocket = websocket
        self.sequence = 0
        self.events = deque()
        self.session = None

    async def call(self, method, params=None, *, root=False):
        self.sequence += 1
        request = dict(id=self.sequence, method=method, params=params or {})
        if self.session and not root:
            request['sessionId'] = self.session
        await self.websocket.send(json.dumps(request))
        async with asyncio.timeout(8):
            while True:
                message = json.loads(await self.websocket.recv())
                if message.get('id') == request['id']:
                    if 'error' in message:
                        # Protocol messages can contain URLs; retain the type only.
                        raise RuntimeError('Owned Chrome target command failed')
                    return message.get('result', {})
                if message.get('sessionId') == self.session and message.get('method'):
                    self.events.append(message)

    async def event(self):
        while True:
            message = self.events.popleft() if self.events else json.loads(await self.websocket.recv())
            if message.get('sessionId') == self.session and message.get('method'):
                return message


def search_request(url, keyword):
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query))
    if parts.scheme != 'https' or parts.hostname != 'www.zhihu.com' or parts.path != '/api/v4/search_v3' or query.get('q') != keyword:
        return None
    return dict(url='https://www.zhihu.com/api/v4/search_v3', parameter_names=sorted(query),
                sort={'created_time': 'latest', 'upvoted_count': 'popular'}.get(query.get('sort'), 'general' if not query.get('sort') else 'unknown'),
                offset=query.get('offset'), requested_count=query.get('limit'),
                keyword_matches=True, trigger='normal-browser-search-page')


def search_documents(raw, task):
    validate_search('zhihu', raw)
    cards = []
    seen = set()
    for row in raw['data']:
        obj = row.get('object') if isinstance(row, dict) else None
        if not isinstance(obj, dict) or obj.get('type') not in ('answer', 'article') or not obj.get('id'):
            continue
        key = (obj['type'], str(obj['id']))
        if key in seen:
            continue
        seen.add(key)
        question = obj.get('question') or {}
        url = ('https://www.zhihu.com/question/' + str(question['id']) + '/answer/' + key[1]
               if key[0] == 'answer' and question.get('id') else 'https://zhuanlan.zhihu.com/p/' + key[1] if key[0] == 'article' else '')
        if not url:
            continue
        cards.append(dict(content_type=key[0], content_id=key[1], content_url=url,
                          title=obj.get('title') or question.get('name') or question.get('title') or '',
                          content_text=obj.get('excerpt') or '', creator_hash=(obj.get('author') or {}).get('id_hash')))
    selected = select_related(cards, task, lambda card: card['title'])
    return [zhihu_search_document(card, raw) for card in selected]


async def observe_search(cdp, task, result):
    """Attach only the target we create; unrelated targets never initialize."""
    target = None
    try:
        result['failure_phase'] = 'browser-page-create'
        target = (await cdp.call('Target.createTarget', dict(url='about:blank'), root=True))['targetId']
        cdp.session = (await cdp.call('Target.attachToTarget', dict(targetId=target, flatten=True), root=True))['sessionId']
        await cdp.call('Network.enable', dict(maxTotalBufferSize=8_000_000, maxResourceBufferSize=4_000_000))
        result['failure_phase'] = 'platform-navigation'
        navigation = await cdp.call('Page.navigate', dict(url='https://www.zhihu.com/search?type=content&q=' + quote(task['keyword'])))
        if navigation.get('errorText'):
            raise OSError('Search page navigation failed')
        result['failure_phase'] = 'platform-search'
        pending = {}
        async with asyncio.timeout(35):
            while True:
                event = await cdp.event()
                params = event['params']
                if event['method'] == 'Network.responseReceived':
                    response = params['response']
                    metadata = search_request(response['url'], task['keyword'])
                    if metadata is None:
                        continue
                    metadata.update(status=response['status'], content_type=response.get('mimeType'))
                    result['observed_requests'].append(metadata)
                    if response['status'] in (401, 403, 429):
                        result.update(state='needs-human', reason='platform-access-refused', error_type='PlatformAccessError')
                        return result
                    if response['status'] == 200 and metadata['offset'] in ('0', None):
                        pending[params['requestId']] = metadata
                elif event['method'] == 'Network.loadingFinished' and params['requestId'] in pending:
                    body = await cdp.call('Network.getResponseBody', dict(requestId=params['requestId']))
                    content = base64.b64decode(body['body']).decode('utf-8') if body.get('base64Encoded') else body['body']
                    raw = public_response(json.loads(content))
                    result['public_responses'].append(raw)
                    result['documents'] = search_documents(raw, task)
                    result.update(state='collected' if result['documents'] else 'empty-sample', reason=None,
                                  search_items=len(raw['data']), related_cards_selected=len(result['documents']),
                                  actual_sort=pending[params['requestId']]['sort'], has_more=(not raw['paging']['is_end']) if isinstance((raw.get('paging') or {}).get('is_end'),bool) else None)
                    return result
    finally:
        if target:
            try:
                await asyncio.shield(cdp.call('Target.closeTarget', dict(targetId=target), root=True))
            except (Exception, asyncio.CancelledError):
                result['owned_page_cleanup'] = 'needs-review'


async def collect(task):
    result = dict(state='partial', reason='chrome-debugging-unavailable', platform='zhihu',
                  keyword=task['keyword'], observed_at=now(), documents=[], public_responses=[],
                  observed_requests=[], collection_route='zhihu-search-response',
                  connection_scope='owned-target-only', failure_phase='local-debugging-check',
                  pages_requested=1, eligibility_state='requires-exam-scope-check')
    if task.get('page', 1) != 1:
        return dict(result, reason='browser-pagination-not-verified', failure_phase='platform-search')
    try:
        from websockets.asyncio.client import connect
        endpoint = debugger_endpoint(task['cdp_port'])
        result['failure_phase'] = 'browser-connect'
        async with connect(endpoint, proxy=None, open_timeout=8, close_timeout=3, max_size=8_000_000) as websocket:
            await observe_search(OwnedTargetConnection(websocket), task, result)
    except TimeoutError:
        result.update(reason='browser-connection-timeout' if result['failure_phase'] == 'browser-connect' else 'page-or-search-response-timeout', error_type='TimeoutError')
    except Exception as exc:
        result.update(reason='platform-network-unavailable' if isinstance(exc, OSError) else 'platform-response-or-adapter-error', error_type=type(exc).__name__)
    return result
