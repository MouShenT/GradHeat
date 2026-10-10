"""School attribution and deterministic decision indices, independent of IO.

Indices are relative decision aids, not empirically calibrated probabilities.
Missing evidence never becomes an observed zero or an invented score threshold.
"""
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
import re
import unicodedata

from pydantic import Field, model_validator
from .models import InputModel

VERSION = 'school-heat-victory-v1'
ALIASES = {
    '北京邮电大学': ['北邮', 'BUPT'], '南京邮电大学': ['南邮', 'NJUPT'],
    '杭州电子科技大学': ['杭电', 'HDU'], '重庆邮电大学': ['重邮', 'CQUPT'],
    '西安电子科技大学': ['西电', 'XDU'], '电子科技大学': ['成电', 'UESTC'],
    '北京航空航天大学': ['北航', 'BUAA'], '北京理工大学': ['北理工'],
    '华中师范大学': ['华师大武汉', '华中师大', 'CCNU'],
    '华东师范大学': ['华东师大', 'ECNU'], '华南师范大学': ['华南师大'],
    '华中科技大学': ['华科', '华中大', 'HUST'], '武汉大学': ['武大', 'WHU'],
    '浙江大学': ['浙大', 'ZJU'], '上海交通大学': ['上交', '上海交大', 'SJTU'],
    '西安交通大学': ['西交', '西安交大', 'XJTU'], '北京交通大学': ['北交', '北京交大'],
    '南京大学': ['南大', 'NJU'], '南开大学': ['南开', 'NKU'],
    '清华大学': ['清华', 'THU'], '北京大学': ['北大', 'PKU'],
    '复旦大学': ['复旦', 'FDU'], '东南大学': ['东南', 'SEU'],
    '厦门大学': ['厦大', 'XMU'], '山东大学': ['山大', 'SDU'],
    '四川大学': ['川大', 'SCU'], '重庆大学': ['重大', 'CQU'],
    '中南大学': ['中南', 'CSU'], '湖南大学': ['湖大', 'HNU'],
    '中山大学': ['中大', 'SYSU'], '华南理工大学': ['华工', 'SCUT'],
    '合肥工业大学': ['合工大', 'HFUT'], '南京理工大学': ['南理工'],
    '南京航空航天大学': ['南航', 'NUAA'], '中国科学技术大学': ['中科大', 'USTC'],
    '中国科学院大学': ['国科大', 'UCAS'], '西北工业大学': ['西工大', 'NPU'],
    '哈尔滨工业大学': ['哈工大', 'HIT'], '哈尔滨工程大学': ['哈工程'],
    '东北大学': ['东北大', 'NEU'], '吉林大学': ['吉大', 'JLU'],
    '大连理工大学': ['大工', '大连理工'], '天津大学': ['天大', 'TJU'],
    '郑州大学': ['郑大', 'ZZU'], '福州大学': ['福大'], '深圳大学': ['深大', 'SZU'],
    '上海大学': ['上大', 'SHU'], '苏州大学': ['苏大'], '宁波大学': ['宁大'],
}
UCAS_COLLEGES = set(('数学科学学院,物理科学学院,化学科学学院,地球与行星科学学院,资源与环境学院,生命科学学院,计算机科学与技术学院,经济与管理学院,人文学院,外语系,工程科学学院,材料科学与光电技术学院,电子电气与通信工程学院,中丹学院,公共政策与管理学院,医学院,天文与空间科学学院,集成电路学院,人工智能学院,核科学与技术学院,纳米科学与工程学院,马克思主义学院,应急管理科学与工程学院,密码学院,现代产业学院,人居科学学院,玉泉书院').split(','))
ADMISSIONS = re.compile(r'考研|硕士|研究生|择校|上岸|复试|录取|408|11408|统考|跨考|报考')
UNRELATED = re.compile(r'高考|专升本|本科招生|校园游|校园参观|研究生招聘')


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def number(value):
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None


def date_value(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
    except (ValueError, TypeError):
        return None


def unit_key(value):
    return unicodedata.normalize('NFKC', value.strip())


def unique_units(names):
    by_key = {}
    for name in names: by_key.setdefault(unit_key(name), name.strip())
    return list(by_key.values())


def identify(doc, units):
    """Full names win over substring aliases (e.g. 西电 vs 成电); ambiguous 华师 omitted.

    A broad query does not assign every returned post to every school. It is used
    only as a fallback for a single-school query when body mentions no school.
    """
    text = unicodedata.normalize('NFKC', re.sub('<[^>]*>', ' ', str(doc.get('title') or '') + '\n' + str(doc.get('text') or '')))
    query = unicodedata.normalize('NFKC', str(doc.get('query') or ''))
    if text and not ADMISSIONS.search(text + ' ' + query):
        return []
    if UNRELATED.search(text) and not re.search(r'考研|408|11408|复试', text):
        return []
    names = unique_units(units)
    def matches(value):
        hits, covered = [], []
        for name in sorted(names, key=len, reverse=True):
            tokens = ['中国科学院大学 '+name, '国科大 '+name] if name in UCAS_COLLEGES else [name] + ALIASES.get(name, [])
            for token in tokens:
                pattern = re.escape(unit_key(token)).replace(r'\ ',r'\s*')
                if token.isascii():
                    pattern = r'(?<![A-Za-z])' + pattern + r'(?![A-Za-z])'
                for match in re.finditer(pattern, value, re.I):
                    if any(a <= match.start() and match.end() <= b for a, b in covered):
                        continue
                    hits.append(name); covered.append(match.span())
        return list(dict.fromkeys(hits))
    found = matches(text)
    if found:
        return [dict(unit=name, weight=1 / len(found), basis='content-mention') for name in found]
    query_hits = matches(query)
    return [dict(unit=query_hits[0], weight=1, basis='single-school-query')] if len(query_hits) == 1 else []


def plausible_claims(doc, links):
    """Retain useful public claims with bounded numeric values and explicit scope.

    School-local excerpts are required for multi-school posts. Never manufacture
    a year, department, quota population, or complete subject combination.
    """
    result = []
    text = str(doc.get('title') or '') + '\n' + str(doc.get('text') or '')
    for sentence in re.split(r'[\n。；;]', text):
        if len(sentence) > 1800 or not sentence.strip():
            continue
        mentioned = identify(dict(text=sentence, query='考研'), [x['unit'] for x in links])
        targets = mentioned or (links if len(links) == 1 else [])
        years = re.findall(r'20(?:2[4-9]|30)', sentence)
        year = int(years[-1]) if years else None
        for link in targets:
            for field, pattern, low, high in [
                ('cutoff', r'(?:复试线|分数线|院线|复试分数)[^\d]{0,8}(\d{3})(?!\d)', 200, 480),
                ('admitted_minimum', r'(?:录取最低分|最低录取分|最低上岸分)[^\d]{0,8}(\d{3})(?!\d)', 200, 500),
                ('ordinary_quota', r'(?:普通统考(?:名额)?|统考(?:招生)?名额)[^\d]{0,8}(\d{1,4})(?!\d)', 1, 2000),
            ]:
                match = re.search(pattern, sentence)
                if match and low <= int(match[1]) <= high:
                    result.append(dict(unit=link['unit'], year=year, field=field, value=int(match[1]),
                        scope=sentence.strip()[:800], source_url=doc.get('url'), source_id=doc.get('id'),
                        origin=doc.get('origin_url') or doc.get('author_hash') or doc.get('url') or doc.get('source_sha256'),
                        confidence=0.45, state='plausible-single-source'))
            if re.search(r'双非|跨考|同等学力|本科', sentence) and re.search(r'复试|报考|上岸|录取|限制|接受', sentence):
                result.append(dict(unit=link['unit'], year=year, field='background_note', value=sentence.strip()[:800],
                    scope=sentence.strip()[:800], source_url=doc.get('url'), source_id=doc.get('id'),
                    origin=doc.get('origin_url') or doc.get('author_hash') or doc.get('url') or doc.get('source_sha256'),
                    confidence=0.35, state='experience-or-rule'))
    return result


def heat_index(docs, signals, as_of):
    """Log-capped engagements and 90-day decay, deduplicated by platform/content.

    Search signals must be observed user search indices/volumes with a provider,
    keyword, comparable window and reference scale. Result counts are excluded.
    """
    now = date_value(as_of) or datetime.now(timezone.utc)
    latest = {}
    for doc in sorted(docs, key=lambda x: x.get('observed_at') or ''):
        latest[(doc.get('platform'), doc.get('content_id') or doc.get('id'))] = doc
    platform_mass = defaultdict(float)
    mapping = {'xhs': [('liked_count', 1), ('comment_count', 2), ('collected_count', 2)],
        'zhihu': [('voteup_count', 1), ('comment_count', 2)],
        'dy': [('digg_count', 1), ('comment_count', 2), ('collect_count', 2)],
        'bili': [('like', 1), ('reply', 2), ('favorite', 2), ('view', .04)]}
    for doc in latest.values():
        platform = doc.get('platform')
        if platform not in mapping:
            continue
        published = date_value(doc.get('published_at'))
        # Unknown publication time is discounted, not silently treated as new.
        recency = .5 if published is None else math.exp(-max(0, (now-published).total_seconds()/86400)/90)
        metrics = doc.get('metrics') or {}
        interaction = sum(w * math.log1p(max(0, number(metrics.get(k)) or 0)) for k, w in mapping[platform])
        platform_mass[platform] += max(0, min(1, doc.get('attribution_weight', 1))) * recency * (1 + min(12, interaction)/4)
    social_scores = {p: 100 * (1 - math.exp(-mass/35)) for p, mass in platform_mass.items()}
    social = sum(social_scores.values()) / len(social_scores) if social_scores else None
    comparable = {}
    for signal in sorted(signals, key=lambda x: x.get('observed_at') or ''):
        if signal.get('kind') not in ('search-index', 'search-volume'):
            continue
        value, scale = number(signal.get('value')), number(signal.get('reference_scale'))
        if value is None or scale is None or value < 0 or scale <= 0 or not signal.get('provider') or not signal.get('source_url'):
            continue
        end = date_value(signal.get('window_end'))
        if end is None or not 0 <= (now-end).total_seconds()/86400 <= 90:
            continue
        key = (signal['provider'], signal.get('keyword'), signal.get('window_start'), signal.get('window_end'), signal.get('region', '全国'))
        comparable[key] = 100 * (1 - math.exp(-value/scale))
    search = sum(comparable.values())/len(comparable) if comparable else None
    score = .65 * social + .35 * search if social is not None and search is not None else social if social is not None else search
    return dict(heat_value=round(score, 1) if score is not None else None,
        basis='discussion-and-search' if social is not None and search is not None else 'discussion-only' if social is not None else 'search-only' if search is not None else 'unavailable',
        discussion_value=round(social, 1) if social is not None else None, search_value=round(search, 1) if search is not None else None,
        unique_contents=len(latest), available_platforms=sorted(social_scores), search_observations=len(comparable),
        missing=['user-search-data'] if search is None else [], model=VERSION, as_of=as_of)


class PersonalProfile(InputModel):
    score: float | None = Field(default=None, ge=0, le=500)
    politics: float | None = Field(default=None, ge=0, le=100)
    english: float | None = Field(default=None, ge=0, le=100)
    mathematics: float | None = Field(default=None, ge=0, le=150)
    computer: float | None = Field(default=None, ge=0, le=150)
    undergraduate_school: str = Field(default='', max_length=160)
    undergraduate_major: str = Field(default='', max_length=160)
    cross_major: bool = False
    previous_graduate: bool = False
    equivalent_education: bool = False
    research_experience: float | None = Field(default=None, ge=0, le=10)
    programming: float | None = Field(default=None, ge=0, le=10)
    preferred_tiers: list[str] = Field(default_factory=list, max_length=8)
    preferred_units: list[str] = Field(default_factory=list, max_length=200)
    mode: str = Field(default='全日制', pattern=r'^(全日制|非全日制|all)$')

    @model_validator(mode='after')
    def consistent_scores(self):
        values = [self.politics, self.english, self.mathematics, self.computer]
        known = sum(x for x in values if x is not None)
        if self.score is not None and (known > self.score + .01 or all(x is not None for x in values) and abs(known-self.score) > .01):
            raise ValueError('单科分数与总分不一致')
        if self.score is None and all(x is not None for x in values):
            self.score = known
        return self


class VictoryInput(InputModel):
    data_version: str = Field(pattern=r'^[a-f0-9]{64}$')
    profile: PersonalProfile
    programme_ids: list[str] = Field(default_factory=list, max_length=100)
    limit: int = Field(default=100, ge=1, le=200)


def victory_indices(payload, dossiers, request):
    if request.profile.score is None:
        return dict(ranking=[], needs_profile=True, missing=['score'], model=VERSION,
            note='填写预计初试分数后计算胜利指数。')
    profile = request.profile
    historic = {h['id']: h for h in payload.get('history', [])}
    alignment = payload.get('historical_alignment') or {}
    results = []
    for p in payload['programmes']:
        if p.get('eligible_11408') is not True or p.get('year') != 2027:
            continue
        if request.programme_ids and p['id'] not in request.programme_ids:
            continue
        if profile.preferred_units and p['unit'] not in profile.preferred_units:
            continue
        if profile.mode != 'all' and p.get('mode') != profile.mode:
            continue
        school = dossiers.get(p['unit'], {})
        heat = school.get('heat', {})
        rows = [historic[h] for h in alignment.get(p['id'], {}).get('matched', []) if h in historic]
        rows = [h for h in rows if 2024 <= h.get('year', 0) <= 2026]
        # Latest aligned cohort only. Multiple conflicting pools stay missing.
        if rows:
            year = max(h['year'] for h in rows); rows = [h for h in rows if h['year'] == year]
        thresholds = [number(h.get('cutoff')) for h in rows]
        thresholds = sorted(set(x for x in thresholds if x is not None and 200 <= x <= 480))
        threshold = thresholds[0] if len(thresholds) == 1 else None
        missing = []
        threshold_basis = 'aligned-history' if threshold is not None else None
        # Plausible social claims may enter at a reduced weight only with a
        # matching major code/department and explicit recent year.
        if threshold is None:
            claims = [c for c in school.get('claims', []) if c.get('field') == 'cutoff' and c.get('year') in (2025, 2026)
                and (p.get('major_code') and p['major_code'] in c.get('scope', '') or p.get('department') and p['department'] in c.get('scope', ''))]
            if claims:
                latest = max(c['year'] for c in claims)
                values = sorted(set(c['value'] for c in claims if c['year'] == latest))
                if len(values) == 1:
                    threshold, threshold_basis = values[0], 'school-claim-estimate'
        if threshold is None:
            missing.append('aligned-score-threshold')
        components = {}
        if threshold is not None:
            components['score'] = (60 if threshold_basis == 'aligned-history' else 35,
                100 / (1 + math.exp(-max(-50, min(50, (profile.score-threshold-15)/22)))))
        tier = school.get('tier') or p.get('group')
        if profile.preferred_tiers:
            components['tier'] = (18, 100 if tier in profile.preferred_tiers else 30)
        background = []
        if profile.programming is not None: background.append(profile.programming * 10)
        if profile.research_experience is not None: background.append(profile.research_experience * 10)
        notes = [c for c in school.get('claims',[]) if c.get('field')=='background_note'
            and (p.get('major_code') and p['major_code'] in c.get('scope','') or p.get('department') and p['department'] in c.get('scope',''))]
        background_evidence = []
        for claim in notes:
            text = claim['value']
            # Experience posts only add a small weighted fit signal. A bare
            # undergraduate school name never changes score by its reputation.
            if profile.cross_major and re.search(r'跨考.{0,12}(?:上岸|录取|接受|可报)',text):
                background_evidence.append((70,claim.get('confidence',.35)))
            if dossiers.get(profile.undergraduate_school,{}).get('tier') == '普通院校' and '双非' in text and re.search(r'双非.{0,12}(?:上岸|录取)',text):
                background_evidence.append((60,claim.get('confidence',.35)))
        if background_evidence:
            background.append(sum(v*w for v,w in background_evidence)/sum(w for _,w in background_evidence))
        # Undergraduate tier, cross-major and graduate year do not earn invented
        # bonuses/penalties. A rule or relevant experience must justify an effect.
        if background: components['background'] = (12, sum(background)/len(background))
        quota = number(p.get('ordinary_quota'))
        historical_counts = sorted(set(number(h.get('admit_count')) for h in rows if number(h.get('admit_count')) is not None and 0 < h['admit_count'] <= 2000))
        capacity_proxy = quota if quota is not None and quota > 0 else historical_counts[0] if len(historical_counts)==1 else None
        if quota is not None and quota > 0:
            components['quota'] = (10, 100*(1-math.exp(-quota/40)))
        else: missing.append('ordinary-quota')
        heat_value = number(heat.get('heat_value'))
        if heat_value is None: missing.append('heat')
        # A threshold is required: preferences alone cannot be called victory.
        base = sum(w*v for w,v in components.values())/sum(w for w,v in components.values()) if components and threshold is not None else None
        results.append(dict(id=p['id'], unit=p['unit'], major_name=p.get('major_name'), major_code=p.get('major_code'),
            department=p.get('department'), tier=tier, heat_value=heat_value, base_index=base,
            threshold=threshold, threshold_basis=threshold_basis, ordinary_quota=quota,
            capacity_proxy=capacity_proxy, capacity_basis='ordinary-quota' if quota is not None and quota>0 else 'historical-admit-count' if capacity_proxy else None,
            missing=missing, evidence_weight=.85 if threshold_basis == 'aligned-history' else .45 if threshold is not None else 0,
            components={k:round(v,2) for k,(_,v) in components.items()}, victory_index=None))
    # Damped logit response to congestion: attractiveness is heat; capacity is
    # observed ordinary seats when available. Unknown capacity has no fabricated
    # seat count and receives only the direct heat penalty.
    known = [r for r in results if r['capacity_proxy'] and r['heat_value'] is not None]
    shares = [1/len(known)] * len(known) if known else []
    converged = not known
    capacity = sum(r['capacity_proxy'] for r in known)
    for _ in range(250):
        utilities = [r['heat_value']/30 - 1.2*s/(r['capacity_proxy']/capacity) for r,s in zip(known,shares)]
        peak = max(utilities) if utilities else 0
        exps = [math.exp(v-peak) for v in utilities]; total = sum(exps)
        updated = [.85*s+.15*v/total for s,v in zip(shares,exps)] if total else []
        if max((abs(a-b) for a,b in zip(updated,shares)),default=0) < 1e-7:
            shares = updated; converged = True; break
        shares = updated
    crowd = {r['id']: s/(r['capacity_proxy']/capacity) for r,s in zip(known,shares)} if known else {}
    for r in results:
        if r['base_index'] is not None:
            penalty = 0 if r['heat_value'] is None else 12*r['heat_value']/100
            if r['id'] in crowd: penalty += 6*(1-math.exp(-max(0,crowd[r['id']]-1)))
            r['victory_index'] = round(max(0, min(100, r['base_index']-penalty)), 1)
        r.pop('base_index')
    # One row per school, best programme in the profile-filtered set.
    schools = {}
    for r in results:
        prior = schools.get(r['unit'])
        if prior is None or (r['victory_index'] if r['victory_index'] is not None else -1) > (prior['victory_index'] if prior['victory_index'] is not None else -1):
            schools[r['unit']] = r
    ranked = sorted(schools.values(), key=lambda r: (r['victory_index'] is None, -(r['victory_index'] or 0), r['unit']))
    return dict(ranking=ranked[:request.limit], programmes=results, needs_profile=False, model=VERSION,
        data_version=request.data_version, game_converged=converged, game_options=len(known), kind='decision-index',
        note='胜利指数为0—100的择校参考分，结合分数、偏好、背景、名额和热度；不代表录取概率。',
        missing_background_rules=bool(profile.cross_major or profile.equivalent_education or profile.undergraduate_school))
