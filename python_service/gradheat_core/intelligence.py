"""School attribution and deterministic decision indices, independent of IO.

Indices are relative decision aids, not empirically calibrated probabilities.
Missing evidence never becomes an observed zero or an invented score threshold.
"""
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
import json
import math
import re
import unicodedata

from pydantic import Field, model_validator
from .models import InputModel

VERSION = 'school-heat-victory-v2'
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
    '北京师范大学': ['北师大','BNU'], '中国人民大学': ['人大','RUC'],
    '北京科技大学': ['北科大','USTB'], '北京工业大学': ['北工大','BJUT'],
    '西北农林科技大学': ['西农','西北农林','NWAFU'], '国防科技大学': ['国防科大','NUDT'],
    '中央民族大学': ['中央民大','MUC'],
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


@lru_cache(maxsize=2048)
def _mention_pattern(token):
    # A full school registry plus aliases exceeds re's shared pattern cache.
    # Cache only names, never post bodies or attribution results.
    pattern = re.escape(unit_key(token)).replace(r'\ ', r'\s*')
    if token.isascii():
        pattern = r'(?<![A-Za-z])' + pattern + r'(?![A-Za-z])'
    return re.compile(pattern, re.I)


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
                for match in _mention_pattern(token).finditer(value):
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
    from .heat_index import heat_index as calculate
    return calculate(docs, signals, as_of)


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
    risk_aversion: float = Field(default=.5, ge=0, le=1)
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
    from .victory import evaluate
    return evaluate(payload, dossiers, request)
