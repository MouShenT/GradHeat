"""User preference intervals; no forecast or cross-year admissions inference."""

from . import ANALYSIS_VERSION
from .models import ComparisonInput, DIMENSIONS
from .repository import ResearchRepository, resolve_degree


def interval_scores(cards: list[dict], weights: dict[str, float]):
    total = sum(weights.values())
    normalized = {d: weights[d] / total for d in DIMENSIONS}
    intervals = {}
    for card in cards:
        if card["hard_constraint_status"] == "blocked":
            continue
        low = high = known = 0.0
        missing = []
        for dimension, weight in normalized.items():
            rating = card["ratings"].get(dimension)
            if rating is None:
                high += weight * 10
                if weight > 0:
                    missing.append(dimension)
            else:
                low += weight * rating["low"]
                high += weight * rating["high"]
                known += weight
        intervals[card["id"]] = {
            "low": low, "high": high, "specified_weight": known, "unknown_dimensions": missing
        }
    # Compare unrounded values. All results are conditional on user inputs.
    potential = [i for i, s in intervals.items()
                 if s["high"] + 1e-10 >= max((o["low"] for j, o in intervals.items() if j != i), default=0)]
    certain = [i for i, s in intervals.items()
               if s["low"] + 1e-10 >= max((o["high"] for j, o in intervals.items() if j != i), default=0)]
    for s in intervals.values():
        for key in ["low", "high", "specified_weight"]:
            s[key] = round(s[key], 4)
    return {"normalized_weights": normalized, "intervals": intervals,
            "potential_best": potential, "certain_best": certain}


def evaluate(repo: ResearchRepository, request: ComparisonInput):
    cards = []
    for candidate in request.candidates:
        detail = repo.detail(candidate.programme_id)
        p = detail["programme"]
        reasons, pending = [], []
        if p.get("cohort") != request.profile.target_year:
            reasons.append("资料年度不符合目标")
        if p.get("eligible_11408") is False:
            reasons.append("现有目录不匹配101/201/301/408")
        elif p.get("eligible_11408") is not True:
            pending.append("初试科目待核")
        if not p.get("mode"):
            pending.append("学习方式待核")
        elif p.get("mode") not in request.profile.modes:
            reasons.append("学习方式不符合个人筛选条件")
        degree, degree_basis = resolve_degree(p)
        if not degree:
            pending.append("学位类型待核")
        elif degree not in request.profile.degrees:
            reasons.append("学位类型不符合个人筛选条件")
        if candidate.personal_eligibility == "self_reported_fail":
            reasons.append("用户填报：个人报考资格不满足")
        elif candidate.personal_eligibility == "unknown":
            pending.append("个人报考资格待核")
        status = "blocked" if reasons else "pending" if pending else "self_reported_pass"
        cards.append({
            "id": candidate.programme_id, "label": f"{p['unit']} · {p.get('department') or '院系未标'} · {p.get('major_code') or '代码未标'} {p.get('major_name') or '专业未标'}",
            "hard_constraint_status": status, "blocked_reasons": reasons, "qualification_pending": pending,
            "personal_eligibility": candidate.personal_eligibility,
            "degree_type": degree, "degree_type_basis": degree_basis,
            "application_readiness": "pending", "ordinary_quota": None, "ranking_pool": None,
            "readiness_pending": ["普通统考净名额未验收", "2027实际排序范围与复试规则未验收"],
            "ratings": {d: r.model_dump() for d, r in candidate.ratings.items()}, "notes": candidate.notes,
            "facts": detail,
        })
    baseline = interval_scores(cards, request.weights)
    scenarios = []
    for d in DIMENSIONS:
        weight = request.weights[d]
        if weight == 0:
            continue
        for factor in (0.5, 1.5):
            changed = dict(request.weights)
            changed[d] *= factor
            scenarios.append({"dimension": d, "factor": factor, **interval_scores(cards, changed)})
    winner_sets = [set(s["certain_best"]) for s in [baseline, *scenarios]]
    stable = sorted(set.intersection(*winner_sets)) if winner_sets else []
    return {
        "state": "draft", "analysis_version": ANALYSIS_VERSION, "source": repo.meta(),
        "input": request.model_dump(), "cards": cards, "baseline": baseline,
        "sensitivity": scenarios, "stable_certain_best": stable,
        "interpretation": "仅比较用户输入的偏好；可能最优/确定最优均限于本次候选集合与给定权重，资格仍需核验。",
        "assumptions": [
            "五项评分均为用户主观适配度，0到10，越高越适合；费用项高分表示更可承受。",
            "用户未评分的维度使用[0,10]，不填中值；评分区间不代表概率或统计置信区间。",
            "偏好可作加权相加，维度区间可独立变化；这些是本工作台的比较假设。",
            "敏感性逐项将非零权重乘0.5或1.5，再归一化；它不是全部权重组合的穷尽检验。",
            "历史资料仅提供同单位上下文，不自动对齐专业，不跨年移植规则，不转换为录取概率。",
            "来源分组不是独立竞争池；同专业多版计划不求和，推免与专项不自行相减。",
        ],
        "forecast": None, "heat_signal": None, "approved_release": False,
    }
