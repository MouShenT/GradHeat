"""Source-free descriptive charts and preference discovery; no forecast inputs."""
import hashlib
import json
import math
from pathlib import Path

from pydantic import Field, model_validator
from .admissions_decision import publication_version
from .history_alignment import align_history
from .information_match import department, fact_parts, numeric
from .models import InputModel
from .reviewed_inputs import read_reviewed_json


def finite_number(value):
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None


def parsed_metric(row, field, metric):
    matches = [value for kind, value, _ in fact_parts({'population': 'enrolled'}, field, row.get(field)) if kind == metric]
    return float(matches[0]) if len(matches) == 1 and numeric(matches[0]) is not None else None


def reviewed_rules(root, programme):
    """A small reviewed rule extension: hashes verified, years/scopes retained."""
    package = read_reviewed_json(root,'.research/agent-verification-20261009/background-friendliness-review.json')
    if not package:return []
    if package.get('status') != 'no-positive-friendliness-claim-approved':return []
    result = []
    for fact in package.get('facts', []):
        if fact.get('unit') != programme['unit']:continue
        pool = fact.get('pool', '')
        if '／' not in pool:continue
        scope, qualifier = pool.split('／', 1)
        if scope != '学校章程':
            if department(scope) != department(programme.get('department')):continue
            if qualifier.isdigit() and qualifier != programme.get('major_code'):continue
        evidence = fact.get('source_evidence', [])
        if not evidence:continue
        valid = True
        for item in evidence:
            artifact = Path(item.get('artifact', '')).resolve()
            if (not artifact.is_relative_to(root.resolve()) or not artifact.is_file()
                    or hashlib.sha256(artifact.read_bytes()).hexdigest() != item.get('sha256')):
                valid = False;break
        if not valid:continue
        result.append(dict(year=fact['year'], scope=pool, statements=fact.get('may_show', []),
            historical=fact['year'] != programme['year']))
    return result


def programme_overview(payload, root):
    links = payload.get('historical_alignment') or align_history(payload['programmes'], payload['history'])
    historical = {row['id']: row for row in payload['history']}
    rows = []
    for p in payload['programmes']:
        alignment = links.get(p['id'], {'matched': [], 'ambiguous': []})
        plan = parsed_metric(p, 'plan_text', 'admissions_plan') if len(p.get('plan_variants', [])) <= 1 else None
        history = []
        for hid in alignment['matched']:
            row = historical[hid]
            if row['year'] not in (2025, 2026):continue
            history.append(dict(id=hid, year=row['year'], scope=row.get('scope'), status=row.get('status'),
                exam_text=row.get('exam_text'), cutoff=finite_number(row.get('cutoff')),
                retest_count=finite_number(row.get('retest_count')), admit_count=finite_number(row.get('admit_count')),
                mean=parsed_metric(row, 'admitted_score_text', 'admitted_mean'),
                minimum=parsed_metric(row, 'admitted_score_text', 'admitted_minimum'),
                maximum=parsed_metric(row, 'admitted_score_text', 'admitted_maximum'),
                interview_admit_ratio=finite_number(row.get('interview_admit_ratio')),
                verification=row.get('verification', {})))
        rows.append(dict(id=p['id'], unit=p['unit'], department=p.get('department'), major_name=p.get('major_name'),
            major_code=p.get('major_code'), group=p.get('group'), year=p['year'], plan_text=p.get('plan_text'),
            reported_plan=plan, plan_status=p.get('plan_status'), ordinary_quota=finite_number(p.get('ordinary_quota')),
            history=history, ambiguous_history_count=len(alignment['ambiguous']), related_rules=reviewed_rules(root, p),
            background=dict(restriction='unknown', retest_rule_2027='unknown', admitted_background_sample='insufficient',
                friendliness='unknown', note='同等学力条件不等于双非本科限制；未发现限制不能证明友好。')))
    return dict(data_version=publication_version(payload), data_as_of=payload['data_as_of'], programmes=rows,
        chart_policy='不同专业、方向、人群或不明确的同年多行分别显示，不合并人数；总计划不作为竞争容量。')


class DiscoveryInput(InputModel):
    data_version: str = Field(pattern=r'^[a-f0-9]{64}$')
    majors: list[str] = Field(default_factory=lambda: ['计算机', '软件', '人工智能', '网安'], min_length=1, max_length=4)
    group_weights: dict[str, float] = Field(default_factory=dict)
    major_weight: float = Field(default=7, ge=0, le=10)
    group_weight: float = Field(default=3, ge=0, le=10)
    background_filter: str = Field(default='all', pattern=r'^(all|related-rules|unknown)$')
    mode: str = Field(default='全日制', pattern=r'^(全日制|非全日制|all)$')
    limit: int = Field(default=20, ge=1, le=60)

    @model_validator(mode='after')
    def validate_preferences(self):
        if set(self.majors) - {'计算机', '软件', '人工智能', '网安'}:raise ValueError('未知专业偏好')
        if self.major_weight + self.group_weight <= 0:raise ValueError('至少一项权重大于0')
        if len(self.group_weights)>30 or any(not 0<=w<=10 for w in self.group_weights.values()):raise ValueError('类别权重为0—10')
        return self


def major_category(programme):
    label = (programme.get('major_name') or '')+' '+ ' '.join(programme.get('directions') or [])
    if '软件' in label:return '软件'
    if '人工智能' in label:return '人工智能'
    if any(word in label for word in ('网络空间安全', '网络与信息安全', '信息安全')):return '网安'
    if '计算机' in label:return '计算机'
    return None


def discover(payload, overview, request):
    groups = {p.get('group') for p in payload['programmes'] if p.get('group')}
    if set(request.group_weights) - groups:raise ValueError('类别必须来自当前资料，不接受未经核对的层次标签')
    scores = []
    details = {p['id']: p for p in overview['programmes']}
    for p in payload['programmes']:
        category = major_category(p)
        if p.get('year')!=2027 or p.get('eligible_11408') is not True or category not in request.majors:continue
        if request.mode!='all' and p.get('mode')!=request.mode:continue
        detail = details[p['id']]
        if request.background_filter=='related-rules' and not detail['related_rules']:continue
        # No current evidence certifies friendliness. Unknown is not given a midpoint or bonus.
        if request.background_filter=='unknown' and detail['background']['friendliness']!='unknown':continue
        group_score = request.group_weights.get(p.get('group'), 5.0)
        score = (10*request.major_weight + group_score*request.group_weight)/(request.major_weight+request.group_weight)
        scores.append(dict(id=p['id'], unit=p['unit'], department=p.get('department'), major_name=p.get('major_name'),
            major_code=p.get('major_code'), group=p.get('group'), category=category, preference_score=round(score, 4),
            components=dict(major_match=10, group_preference=group_score), background=detail['background'],
            related_rules=detail['related_rules'], status='个人偏好候选；报考条件与本科背景相关资料待核',
            missing=['2027普通统考净名额'] if p.get('ordinary_quota') is None else []))
    scores.sort(key=lambda p: (-p['preference_score'], p['unit'], p['major_code'] or '', p['id']))
    return dict(data_version=publication_version(payload), ranking=scores[:request.limit], eligible_candidates=len(scores),
        method='professional-and-user-group-preferences-v1', basis='分数只表达用户专业与类别偏好，不要求成绩，也不表示录取难度或概率。',
        group_policy='985、计算机强校、研究所等是现有采集分组；类别权重由你指定，不自动当作实力排序。',
        friendliness_policy='尚无可正向认定双非友好的结构化证据；相关规则单独显示，未知不参与得分。')
