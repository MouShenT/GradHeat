"""Public social evidence, with source lineage separate from popularity."""
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

POLICY = 'social-evidence-v1'
SECRET_KEYS = {'cookie', 'cookies', 'authorization', 'headers', 'xsec_token',
    'xsec_source', 'access_token', 'refresh_token', 'zd_token', 'websocketdebuggerurl',
    'uifid', 'uifid_temp', 'verifyfp', 'fp', 'mstoken', 'a_bogus', 'csrf_token'}
SECRET_QUERY = SECRET_KEYS | {'sign', 'signature', 'token', 'request_click_id', 'w_rid'}


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(encode(value).encode()).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def clean_url(value):
    p = urlsplit(str(value))
    if p.scheme not in ('http', 'https') or not p.hostname:
        return ''
    query = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
        if k.lower() not in SECRET_QUERY and not k.lower().startswith('utm_')]
    return urlunsplit((p.scheme, p.netloc, p.path, urlencode(query), ''))


def clean_text(value):
    # Remove expiring navigation tokens while retaining official query parameters.
    return re.sub(r'https?://[^\s<>"\)]+', lambda m: clean_url(m.group()), str(value or ''))


def public_response(value):
    if isinstance(value, dict):
        result = {}
        for k, v in value.items():
            key = k.lower()
            if key in SECRET_KEYS or key.startswith('x-zse') or key.startswith('x-zst'):
                continue
            if key in {'author', 'user', 'user_info', 'owner'} and isinstance(v, dict):
                v = dict(v)
                if v.get('id'):
                    v['id_hash'] = hashlib.sha256(str(v.pop('id')).encode()).hexdigest()
            if key in {'user_id', 'uid', 'sec_uid', 'mid', 'url_token', 'avatar', 'avatar_url', 'avatar_url_template', 'email', 'phone'}:
                if key in {'user_id', 'uid', 'sec_uid', 'mid', 'url_token'} and v:
                    result[key + '_hash'] = hashlib.sha256(str(v).encode()).hexdigest()
                continue
            result[k] = public_response(v)
        return result
    if isinstance(value, list):
        return [public_response(v) for v in value]
    if isinstance(value, str):
        return clean_text(value)
    return value


def count(value):
    if value is None or isinstance(value, bool):
        return None
    raw = str(value).strip().replace(',', '')
    # Rounded "1万+" is not an exact count.
    return int(raw) if re.fullmatch(r'\d+', raw) else None


def published(value):
    if not value:
        return None
    if isinstance(value, (int, float)):
        seconds = value / 1000 if value > 10**11 else value
        return datetime.fromtimestamp(seconds, timezone.utc).isoformat()
    return str(value)


def exposed_metrics(response, content_id, content_type):
    """Read only counters present on the matching search result, never model defaults."""
    if isinstance(response, dict):
        if str(response.get('id') or '') == str(content_id) and response.get('type') == content_type:
            return {k: count(response.get(k)) for k in ('voteup_count', 'comment_count')}
        for value in response.values():
            if isinstance(value, (dict, list)):
                found = exposed_metrics(value, content_id, content_type)
                if found is not None:return found
    elif isinstance(response, list):
        for item in response:
            found = exposed_metrics(item, content_id, content_type)
            if found is not None:return found
    return None


def note_items(response, limit):
    """Process even the final page (has_more=False); deduplicate before budgeting."""
    seen = set()
    for item in response.get('items', []):
        nid = item.get('id')
        if not nid or nid in seen or item.get('model_type') in ('rec_query', 'hot_query'):
            continue
        seen.add(nid)
        yield item
        if len(seen) >= limit:
            break


def select_related(items, task, title):
    """Rank public first-page cards only; relevance is not a truth/11408 verdict."""
    import html
    if task.get('generic_search'):
        # Literal user queries retain the platform's result order. Admissions
        # relevance/eligibility is assessed later, never a hidden acquisition filter.
        return items[:task['limit']]
    unit = task.get('unit') or task['keyword'].split(' ')[0]
    ranked = []
    for index, item in enumerate(items):
        label = html.unescape(re.sub(r'<[^>]+>', '', str(title(item) or '')))
        computing = bool(re.search(r'计算机|408|软件|网络空间|人工智能|网安|电子信息|智能科学|数据科学', label))
        if re.search(r'教师.*招聘|招聘.*教师|本科招生|高考|博士|公务员|事业单位', label):
            continue
        if not computing and re.search(r'MBA|MPA|MPAcc|工商管理|会计|应用统计|法硕|法律硕士', label, re.I):
            continue
        score = 3*computing + 2*bool(re.search(r'考研|硕士|统考|招生|复试|录取|择校', label)) + 2*(unit in label)
        if score >= 4:
            ranked.append((score,index,item))
    ranked.sort(key=lambda row:(-row[0],row[1]))
    return [row[2] for row in ranked[:task['limit']]]


class PlatformVerificationRequired(ValueError):
    pass


def validate_search(platform, response):
    """A success/error page or an unexpected shape is never an empty sample."""
    if not isinstance(response, dict):
        raise ValueError('Search response is not an object')
    if platform == 'dy':
        nil = response.get('search_nil_info') or {}
        if 'verify_check' in (nil.get('search_nil_type'), nil.get('search_nil_item')):
            raise PlatformVerificationRequired('Douyin search requires human verification')
    if platform == 'dy' and response.get('status_code') != 0:
        raise ValueError('Douyin search business status failed')
    key = {'xhs': 'items', 'zhihu': 'data', 'dy': 'data', 'bili': 'result'}[platform]
    if not isinstance(response.get(key), list):
        raise ValueError('Search response lacks its expected result list')


def video_items(platform, response, limit):
    validate_search(platform, response)
    seen = set()
    rows = response['data' if platform == 'dy' else 'result']
    for row in rows:
        if not isinstance(row, dict):
            continue
        if platform == 'dy':
            item = row.get('aweme_info')
            if not item:
                mix = (row.get('aweme_mix_info') or {}).get('mix_items') or []
                item = mix[0] if mix else None
            key = item.get('aweme_id') if isinstance(item, dict) else None
        else:
            item = row
            key = item.get('bvid') or item.get('aid')
        if not key or str(key) in seen:
            continue
        seen.add(str(key))
        yield item
        if len(seen) >= limit:
            break


def document(platform, raw, *, full=False):
    if platform == 'xhs':
        user = raw.get('user') or {}
        author = raw.get('creator_hash') or raw.get('user_id_hash') or user.get('user_id_hash')
        if not author and user.get('user_id'):
            author = hashlib.sha256(str(user['user_id']).encode()).hexdigest()
        metrics = raw.get('interact_info') or raw
        nid = str(raw.get('note_id') or raw.get('id') or '')
        images = raw.get('image_list') or []
        if isinstance(images, str):images = images.split(',')
        return dict(platform=platform, content_id=nid, content_type=raw.get('type'),
            url=f'https://www.xiaohongshu.com/explore/{nid}', title=raw.get('title', ''),
            text=raw.get('desc', ''), published_at=published(raw.get('time')),
            author_hash=author, metrics={k: count(metrics.get(k)) for k in
                ('liked_count', 'collected_count', 'comment_count', 'share_count')},
            metrics_display={k: metrics.get(k) for k in ('liked_count', 'collected_count', 'comment_count', 'share_count')},
            content_level='full-text' if full else 'excerpt',
            image_urls=[clean_url(i.get('url_default') or i.get('url') or '') if isinstance(i, dict) else clean_url(i) for i in images])
    if platform in ('dy', 'bili'):
        video = raw.get('View') or raw if platform == 'bili' else raw
        owner = video.get('owner' if platform == 'bili' else 'author') or {}
        author = owner.get('mid_hash') or owner.get('uid_hash') or owner.get('id_hash')
        if not author:
            value = owner.get('mid') or owner.get('uid')
            author = hashlib.sha256(str(value).encode()).hexdigest() if value else None
        metrics = video.get('stat' if platform == 'bili' else 'statistics') or {}
        keys = ('view', 'danmaku', 'reply', 'favorite', 'coin', 'share', 'like') if platform == 'bili' else (
            'play_count', 'digg_count', 'comment_count', 'collect_count', 'share_count')
        nid = str(video.get('bvid') or video.get('aid') or '') if platform == 'bili' else str(video.get('aweme_id') or '')
        url = (f'https://www.bilibili.com/video/{nid}' if video.get('bvid') else
            f'https://www.bilibili.com/video/av{nid}') if platform == 'bili' else f'https://www.douyin.com/video/{nid}'
        result = dict(platform=platform, content_id=nid, content_type='video', url=url,
            title=clean_text(video.get('title') or video.get('desc') or ''), text=clean_text(video.get('desc') or ''),
            published_at=published(video.get('pubdate') if platform == 'bili' else video.get('create_time')),
            author_hash=author, metrics={k: count(metrics.get(k)) for k in keys},
            metrics_display={k: metrics.get(k) for k in keys},
            content_level='video-description', image_urls=[], transcript_state='not-collected')
        if platform == 'dy':
            # The search response gives 0 even on a card with thousands of likes.
            # Keep its literal value in metrics_display/raw; do not claim actual plays.
            result['metrics']['play_count'] = None
            result['metrics_availability'] = {'play_count': 'not-confirmed-in-public-search'}
        return result
    if platform != 'zhihu':
        raise ValueError('Unsupported social platform')
    nid = str(raw.get('content_id') or raw.get('id') or '')
    kind = raw.get('content_type') or raw.get('type') or 'article'
    author = raw.get('creator_hash') or (raw.get('author') or {}).get('id')
    return dict(platform=platform, content_id=nid, content_type=kind,
        url=clean_url(raw.get('content_url') or f'https://zhuanlan.zhihu.com/p/{nid}'),
        title=raw.get('title', ''), text=raw.get('content_text') or raw.get('content') or raw.get('desc') or '',
        published_at=published(raw.get('created_time') or raw.get('created')),
        author_hash=hashlib.sha256(str(author).encode()).hexdigest() if author else None,
        metrics={k: count(raw.get(k)) for k in ('voteup_count', 'comment_count')},
        content_level='full-text' if full else 'excerpt', image_urls=[])


def snapshot(doc, run_id, artifact):
    path = Path(artifact).resolve()
    result = public_response(dict(doc, run_id=run_id, observed_at=doc.get('observed_at') or now(),
        source_artifact=str(path), source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        scope='sample-not-census', policy=POLICY))
    result['id'] = digest(result)
    return result


def candidate_segments(doc, units):
    """Discovery hints only: do not infer a quota, cohort or full 11408 combination."""
    result = []
    for line in re.split(r'\n\s*\n', doc.get('text', '')):
        if not re.search(r'408|拟录取|复试线|复录比|招生计划|录取人数|最低分|均分', line):
            continue
        row = dict(snapshot_id=doc['id'], quote=line[:5000],
            unit_hints=[u for u in units if u in line],
            year_hints=sorted(set(re.findall(r'20(?:2[4-9]|30)', line))),
            major_code_hints=sorted(set(re.findall(r'(?<!\d)(?:08\d{4}|08\d{2}[A-Z]\d)(?!\d)', line))),
            state='candidate', reason='needs-scope-and-lineage-check',
            source_artifact=doc['source_artifact'], source_sha256=doc['source_sha256'])
        row['id'] = digest(row)
        result.append(row)
    return result


def reviewed_observations(root):
    path = root / '.research/social/claims-reviewed.json'
    rows = json.loads(path.read_text(encoding='utf-8')) if path.exists() else []
    out = []
    for row in rows:
        if row.get('review_state') != 'evidence-checked' or row.get('lineage_state') != 'resolved':
            continue
        artifact = Path(row['source_artifact']).resolve()
        if not artifact.is_relative_to(root.resolve()) or not artifact.is_file():
            raise ValueError('Social claim original missing')
        if hashlib.sha256(artifact.read_bytes()).hexdigest() != row['source_sha256']:
            raise ValueError('Social original changed')
        if row.get('evidence_kind') == 'image-transcription':
            transcription = Path(row['transcription_artifact']).resolve()
            if not transcription.is_relative_to(root.resolve()) or not transcription.is_file():
                raise ValueError('Image transcription missing')
            if hashlib.sha256(transcription.read_bytes()).hexdigest() != row['transcription_sha256']:
                raise ValueError('Image transcription changed')
            if row.get('review_method') != 'original-image-visual-check':
                raise ValueError('Image claim lacks original-image check')
            saved = json.loads(transcription.read_text(encoding='utf-8'))
        else:
            saved = json.loads(artifact.read_text(encoding='utf-8'))
        quote = row.get('quote', '')
        if not quote or quote not in saved.get('text', '') or not row.get('origin_id'):
            raise ValueError('Social claim lacks exact evidence or resolved origin')
        if not row.get('year') or not row.get('unit') or not row.get('major_name'):
            raise ValueError('Social claim lacks admissions scope')
        # Every claimed field must have its own quoted evidence and review.
        if set(row['fields']) != set(row.get('field_evidence', {})):
            raise ValueError('Social field evidence missing')
        for evidence in row['field_evidence'].values():
            if not evidence or evidence not in quote:
                raise ValueError('Social field evidence outside quote')
        out.append(row)
    return out
