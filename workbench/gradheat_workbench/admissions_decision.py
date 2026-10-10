"""Personal preference analysis against an immutable, source-free data publication."""
import hashlib

from .decision import interval_scores
from .models import ComparisonInput, DIMENSIONS
from .sessions import canonical
from .history_alignment import align_history

VERSION = 'personal-preferences-v1'


def publication_version(payload):
    return hashlib.sha256(canonical(payload).encode('utf-8')).hexdigest()


def evaluate_public(payload, request: ComparisonInput):
    programmes = {p['id']: p for p in payload['programmes']}
    history = {r['id']: r for r in payload['history']}
    links = payload.get('historical_alignment') or align_history(payload['programmes'], payload['history'])
    cards = []
    for candidate in request.candidates:
        p = programmes[candidate.programme_id]
        reasons, pending = [], []
        if p.get('year') != request.profile.target_year:
            reasons.append('招生年度不符合目标')
        if p.get('eligible_11408') is False:
            reasons.append('考试科目不符合11408')
        elif p.get('eligible_11408') is not True:
            pending.append('考试科目待核')
        for field, allowed, label in [('mode', request.profile.modes, '学习方式'), ('degree_type', request.profile.degrees, '学位类型')]:
            if not p.get(field):
                pending.append(label + '待核')
            elif p[field] not in allowed:
                reasons.append(label + '不符合个人条件')
        if candidate.personal_eligibility == 'self_reported_fail':
            reasons.append('个人报考资格不满足')
        elif candidate.personal_eligibility == 'unknown':
            pending.append('个人报考资格待核')
        card_links = links.get(p['id'], {'matched': [], 'ambiguous': []})
        cards.append(dict(id=p['id'], label=' · '.join(filter(None, [p['unit'], p.get('department'), p.get('major_name'), p.get('major_code')])),
            hard_constraint_status='blocked' if reasons else 'pending' if pending else 'self_reported_pass',
            blocked_reasons=reasons, qualification_pending=pending,
            ratings={d: r.model_dump() for d, r in candidate.ratings.items()}, notes=candidate.notes,
            programme=p, history=[history[i] for i in card_links['matched']],
            ambiguous_history_count=len(card_links['ambiguous'])))
    baseline = interval_scores(cards, request.weights)
    scenarios = []
    for dimension, weight in request.weights.items():
        if weight == 0:
            continue
        for factor in (0.5, 1.5):
            changed = dict(request.weights)
            changed[dimension] *= factor
            scenarios.append(dict(dimension=dimension, factor=factor, **interval_scores(cards, changed)))
    winners = [set(x['certain_best']) for x in [baseline, *scenarios]]
    return dict(analysis_version=VERSION, data_version=publication_version(payload), data_as_of=payload['data_as_of'],
        input=request.model_dump(exclude={'data_version'}), cards=cards, baseline=baseline, sensitivity=scenarios,
        stable_certain_best=sorted(set.intersection(*winners)),
        interpretation='结果比较你填写的适配度。分数越高越符合本次偏好；资格待核项目的结果以资格成立为前提。',
        assumptions=['未填写的维度按0—10保留不确定范围；评分范围不是录取概率。',
            '历史记录按同单位、院系与专业对应；过去的考试科目、名额和复试规则分别保留。',
            '各维度可按权重相加，费用分数越高表示越可承受。',
            '敏感性分别将各非零权重乘0.5和1.5，检验本轮候选的结果是否改变；并非穷尽所有权重。'])


def render_report(result):
    request = result['input']
    lines = [f"# {request['title']}", '', f"目标：2027入学 · 11408；资料截至：{result['data_as_of']}", '', result['interpretation'], '', '## 候选比较', '']
    for card in result['cards']:
        p = card['programme']; score = result['baseline']['intervals'].get(card['id'])
        lines += [f"### {card['label']}", '', f"计划人数：{p.get('plan_text') or '待补'}；普通统考名额：{p.get('ordinary_quota') if p.get('ordinary_quota') is not None else '待核'}",
            f"偏好得分：{score['low']}—{score['high']} / 10" if score else '本次条件不满足，已排除',
            f"资格及条件：{'；'.join(card['blocked_reasons'] + card['qualification_pending']) or '用户自报满足'}", '']
        for d, label in DIMENSIONS.items():
            r = card['ratings'].get(d)
            lines.append(f"- {label}：{r['low']}—{r['high']}；依据：{r['basis'] or '未填写'}" if r else f'- {label}：未知（0—10）')
        lines += ['', f"备注：{card['notes'] or '未填写'}", '', '对应历史记录：', '']
        for h in sorted(card['history'], key=lambda x: x['year'], reverse=True):
            lines.append(f"- {h['year']} {h.get('major_name')}（{h.get('exam_text') or '科目待核'}）：复试线 {h.get('cutoff_text') or '—'}；复试 {h.get('retest_text') or '—'}；拟录取 {h.get('admit_text') or '—'}；录取分数 {h.get('admitted_score_text') or '—'}")
        if not card['history']:
            lines.append('- 暂无明确对应的记录。')
        lines.append('')
    labels = {c['id']: c['label'] for c in result['cards']}
    describe = lambda ids: '；'.join(labels[i] for i in ids) or '目前不能确定'
    lines += ['## 权重变化', '', f"本轮权重测试下均为确定最优：{describe(result['stable_certain_best'])}", '']
    for s in result['sensitivity']:
        lines.append(f"- {DIMENSIONS[s['dimension']]}权重×{s['factor']}：可能最优 {describe(s['potential_best'])}；确定最优 {describe(s['certain_best'])}")
    lines += ['', '## 比较说明', ''] + ['- ' + s for s in result['assumptions']] + ['']
    return '\n'.join(lines)
