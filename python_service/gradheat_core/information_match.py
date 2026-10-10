"""Match admissions statements by entity and meaning, retaining scope distinctions."""
import json
import re
import unicodedata
from decimal import Decimal, ROUND_HALF_UP

POLICY = 'admissions-information-v3-two-sources'


def text(value):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', str(value or ''))).replace('；', ';').replace('：', ':')


def department(value):
    return re.sub(r'^\(?\d{2,4}\)?', '', text(value))


def identity(row, kind):
    year = row.get('year', row.get('cohort'))
    label = text(row.get('major_name') or row.get('label') or row.get('scope'))
    if not year or not row.get('unit') or not label:
        return None
    code = text(row.get('major_code'))
    match = re.search(r'(?<!\d)(\d{4}[A-Z0-9]{2})(?!\d)', label)
    if not code and match:
        code = match.group(1)
    dept = department(row.get('department'))
    degree = text(row.get('degree_type'))
    if degree in ('xs', '学术学位') or re.search(r'学硕|学术学位', label):
        degree = 'academic'
    elif degree in ('zy', 'zyxw', '专业学位') or re.search(r'专硕|专业学位', label):
        degree = 'professional'
    else:
        degree = ''
    mode = text(row.get('mode'))
    if '非全日制' in label:
        mode = '非全日制'
    elif '全日制' in label and not mode:
        mode = '全日制'
    # Only reviewed, explicit direction keys narrow a merged-cell catalogue
    # observation; legacy missing-direction rows keep their existing identity.
    directions = sorted(set(text(v) for v in row.get('consensus_directions', []) if text(v)))
    # A structured official table label carries several facts, not a major name.
    name_match = re.search(r'(?:报考专业|专业名称|学科专业|专业/方向名称|专业代码及名称|全日制专业学位|非全日制专业学位|专业):([^;]+)', label)
    if name_match:
        name = name_match.group(1)
        d = re.search(r'(?:报考研究方向名称|研究方向名称|研究方向信息|研究方向):([^;]+)', label)
        if d and d.group(1) not in ('--', '不区分研究方向', '不区分方向'):
            directions = [re.sub(r'^\d{2}', '', d.group(1))]
        dept_match = re.search(r'(?:院系|院系所|院系名称|学院名称|学院代码及名称):([^;]+)', label)
        if not dept and dept_match:
            dept = department(dept_match.group(1))
    else:
        name = label
        if kind == 'distribution':
            # "学院(学硕 专业)", "学院 专业(学硕)" and codes are equivalent layouts.
            bracket = re.search(r'\((?:学硕|专硕|学术学位|专业学位|\d{4}[A-Z0-9]{2})([^)]*[^,])\)$', name)
            if bracket and bracket.group(1) and not re.fullmatch(r'[,、]*(?:全日制|非全日制)?', bracket.group(1)):
                prefix = name[:bracket.start()]
                if prefix and not dept:
                    dept = department(prefix)
                name = name[bracket.start() + 1:-1]
            else:
                stripped = re.sub(r'\((?:专业学位|学术学位)\)', '', name)
                prefix = re.match(r'^(.+?(?:学院|学部|研究院|研究所|校区|书院|系))(\([^)]*(?:校区|学院)[^)]*\))?', stripped)
                if prefix:
                    if not dept:
                        dept = department(prefix.group(0))
                    name = stripped[prefix.end():]
    name = re.sub(r'\d{4}[A-Z0-9]{2}', '', name)
    name = re.sub(r'\((?:学硕|专硕|学术学位|专业学位|全日制|非全日制)[^)]*\)', '', name)
    name = re.sub(r'^(?:学硕|专硕|学术学位|专业学位)', '', name)
    name = re.sub(r'[-·,、]?(?:非全日制|全日制)$', '', name).strip('()-,、·')
    branches = ('计算机技术', '计算机科学与技术', '软件工程', '人工智能', '网络与信息安全', '网络空间安全', '大数据技术与工程', '大数据工程')
    if name.startswith('电子信息'):
        leaf = name[len('电子信息'):].strip('-·()/')
        leaf = {'计算机方向': '计算机技术', '软件方向': '软件工程'}.get(leaf, leaf)
        if leaf in branches:
            name = leaf
            degree = degree or 'professional'
    special = text(row.get('special_scope'))
    if not special:
        special = next((x for x in ('退役大学生士兵', '退役士兵', '少数民族骨干', '少干', '单独考试') if x in label or x in text(row.get('route'))), '')
    if not name:
        return None
    return dict(unit=text(row['unit']), year=int(year), department=dept, major=name, major_code=code,
        degree=degree, mode=mode, route=text(row.get('route')), campus=text(row.get('campus')),
        special=special, directions=directions, population=text(row.get('population')))


def numeric(value):
    raw = text(value)
    if re.fullmatch(r'\d+(?:\.\d+)?', raw):
        return format(Decimal(raw).normalize(), 'f')
    return None


def fact_parts(scope, field, value):
    """Decompose statements; never confuse a minimum observed score with a cutoff."""
    raw = text(value)
    if value is None or raw in ('', '—', '-', 'NC', '未知'):
        return []
    prefix = 'admitted' if scope.get('population') == 'enrolled' else 'retest' if scope.get('population') == 'retest_pool' else 'sample'
    if field in ('cutoff', 'cutoff_text'):
        minimum = re.fullmatch(r'最低分[:：]?(\d+(?:\.\d+)?)', raw)
        if minimum:
            return [('retest_minimum', numeric(minimum.group(1)), {})]
        total = re.fullmatch(r'(\d{3}(?:\.\d+)?)(?:[、,/;]\d{2,3})*', raw)
        return [('retest_cutoff', numeric(total.group(1)) if total else raw, {})]
    if field == 'admitted_score_text':
        summary = re.fullmatch(r'(?:均分|平均分)?(\d+(?:\.\d+)?)(?:;?范围)?[【\[(]?(\d+(?:\.\d+)?)[—–-](\d+(?:\.\d+)?)[】\])]?', raw)
        if summary:
            return [(f'admitted_{metric}', text(number) if metric=='mean' else numeric(number), {}) for metric, number in zip(('mean', 'minimum', 'maximum'), summary.groups())]
        mean = re.fullmatch(r'(?:均分|平均分)(\d+(?:\.\d+)?)', raw)
        if mean:
            return [('admitted_mean', text(mean.group(1)), {})]
        return [('admitted_score_text', raw, {})]
    if field in ('n', 'minimum', 'maximum', 'mean', 'median'):
        return [(f'{prefix}_{"count" if field == "n" else field}', raw if field=='mean' else numeric(value) or raw, {})]
    if field in ('admit_text', 'retest_text'):
        number = re.fullmatch(r'(?:拟录取|录取|进复试|复试)?(?:人数)?[:：]?(\d+)(?:人)?', raw)
        return [('admitted_count' if field == 'admit_text' else 'retest_count', numeric(number.group(1)) if number else raw, {})]
    if field in ('subjects', 'exam_text'):
        combos = {'11408': ['101', '201', '301', '408'], '22408': ['101', '204', '302', '408'],
            '12408': ['101', '201', '302', '408'], '21408': ['101', '204', '301', '408']}
        codes = list(value) if isinstance(value, list) else combos.get(raw) or re.findall(r'(?<!\d)(?:101|201|204|301|302|408)(?!\d)', raw)
        return [('exam_subjects', json.dumps(codes, separators=(',', ':')) if len(codes) == 4 else raw, {})]
    if field == 'plan_text':
        plan = re.fullmatch(r'(?:(专业|学科|研究方向|方向|学院|院系|统考|拟招|招生计划)[:：]?)?(\d+)(?:人)?(?:[,;]?\(?(不含推免|含推免)\)?)?', raw)
        if plan:
            level, number, exemption = plan.groups()
            level = 'direction' if level in ('方向', '研究方向') else 'department' if level in ('学院', '院系') else 'major' if level in ('专业', '学科') else ''
            return [('admissions_plan', numeric(number), dict(plan_extent=level, exemption=exemption or ''))]
        return [('admissions_plan', raw, {})]
    return [(field, numeric(value) or raw, {})]


def same_value(metric, left, right):
    if left == right:
        return True
    # Means with different stated precision can describe the same rounded result.
    if metric.endswith('_mean') and numeric(left) and numeric(right):
        a, b = Decimal(left), Decimal(right)
        precision = max(a.as_tuple().exponent, b.as_tuple().exponent)
        quantum = Decimal(1).scaleb(precision)
        return a.quantize(quantum, rounding=ROUND_HALF_UP) == b.quantize(quantum, rounding=ROUND_HALF_UP)
    return False


FACETS = ('major_code', 'department', 'degree', 'mode', 'route', 'campus', 'plan_extent', 'exemption')


def compatible(a, b):
    if a['unit'] != b['unit'] or a['year'] != b['year']:
        return False
    if a.get('major_code') and b.get('major_code'):
        if a['major_code'] != b['major_code']:
            return False
    elif a['major'] != b['major']:
        return False
    if a.get('special', '') != b.get('special', '') or a.get('directions', []) != b.get('directions', []):
        return False
    return all(not a.get(f) or not b.get(f) or a[f] == b[f] for f in FACETS)


class Matcher:
    def __init__(self, rows):
        self.groups = {}
        self.cache = {}
        for row in rows:
            key = row['scope']
            for metric, value, qualifiers in fact_parts(key, row['field'], row.get('raw_value', row['value'])):
                scope = dict(key, **qualifiers)
                fact = dict(row, metric=metric, fact_value=value, fact_scope=scope)
                self.groups.setdefault((key['unit'], key['year'], metric), []).append(fact)

    def context(self, key, metric):
        cache_key = (json.dumps(key, sort_keys=True, ensure_ascii=False), metric)
        if cache_key in self.cache:
            return self.cache[cache_key]
        nearby = self.groups.get((key['unit'], key['year'], metric), [])
        peers = [r for r in nearby if compatible(key, r['fact_scope'])]
        resolved = dict(key)
        ambiguous = []
        for facet in FACETS:
            if not resolved.get(facet):
                known = {r['fact_scope'][facet] for r in peers if r['fact_scope'].get(facet)}
                if len(known) == 1:
                    resolved[facet] = next(iter(known))
                elif len(known) > 1:
                    ambiguous.append(facet)
        result = (resolved, ambiguous)
        self.cache[cache_key] = result
        return result

    def candidates(self, key, metric):
        resolved, ambiguous = self.context(key, metric)
        nearby = self.groups.get((key['unit'], key['year'], metric), [])
        found = []
        for row in nearby:
            other, other_ambiguous = self.context(row['fact_scope'], metric)
            if not compatible(resolved, other):
                continue
            # Missing metadata may bridge one unique entity, never choose among two colleges/codes/modes.
            blocked = any(resolved.get(f) != other.get(f) for f in set(ambiguous + other_ambiguous))
            if not blocked:
                found.append(row)
        return found, resolved, ambiguous
