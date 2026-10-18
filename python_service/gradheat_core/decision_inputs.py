"""Resolve useful school inputs without changing the published source payload."""
import math
import re
import statistics

from .information_match import department, fact_parts, text
from .community_sources import compatible_scores


def numeric(value):
    return float(value) if isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value) else None


def conflicted(row, field):
    verification = row.get('verification', {}).get(field, {})
    return verification.get('state') == 'conflict' or verification.get('official_state') == 'conflict'


def score_summary(row):
    if conflicted(row, 'admitted_score_text'):
        return {}
    return {metric.removeprefix('admitted_'): float(value)
            for metric, value, _ in fact_parts({}, 'admitted_score_text', row.get('admitted_score_text'))
            if metric in {'admitted_mean', 'admitted_minimum', 'admitted_maximum'} and re.fullmatch(r'\d+(?:\.\d+)?', value)
            and 100 <= float(value) <= 500}


def net_quota(programme):
    supplied = numeric(programme.get('ordinary_quota'))
    if supplied is not None and 0 <= supplied <= 5000:
        return supplied, 'published-ordinary-quota', 'major'
    if conflicted(programme, 'plan_text'):
        return None, None, None
    variants = programme.get('plan_variants') or [programme.get('plan_text')]
    parsed = []
    for variant in variants:
        parts = fact_parts({}, 'plan_text', variant)
        if len(parts) != 1:
            return None, None, None
        metric, value, scope = parts[0]
        if metric != 'admissions_plan' or scope.get('exemption') != '不含推免':
            return None, None, None
        if scope.get('plan_extent') not in {'major', 'direction'} or not re.fullmatch(r'\d+', value):
            return None, None, None
        parsed.append((int(value), scope['plan_extent']))
    if not parsed or len(set(parsed)) != 1:
        return None, None, None
    value, extent = parsed[0]
    if extent == 'direction' and len(programme.get('directions', [])) != 1:
        return None, None, None
    if not 0 <= value <= 5000:
        return None, None, None
    return value, 'explicit-excludes-exemption', extent


def matching_facts(programme, dossier):
    """Prefer exact scopes; a renamed department is allowed only in a unique pool."""
    peers = [p for p in dossier.get('programmes', []) if p.get('unit') == programme['unit']
             and p.get('year') == programme.get('year') and p.get('major_code') == programme.get('major_code')
             and p.get('mode') == programme.get('mode')]
    unique_pool = len({department(p.get('department')) for p in peers}) <= 1
    matched = []
    for fact in dossier.get('decision_facts', []):
        if fact.get('unit') != programme['unit'] or fact.get('major_code') != programme.get('major_code'):
            continue
        if fact.get('route') != 'first-choice' or fact.get('special', False):
            continue
        if fact.get('population') == 'reported-aggregate':
            continue
        if fact.get('mode') and fact['mode'] != programme.get('mode'):
            continue
        if fact.get('campus') and text(fact['campus']) != text(programme.get('campus')):
            continue
        left, right = department(programme.get('department')), department(fact.get('department'))
        if right and right != left and not unique_pool and fact.get('department_scope')!='all':
            continue
        if not right and not unique_pool and fact.get('department_scope')!='all':
            continue
        campus_peers = [p for p in peers if not right or department(p.get('department')) == right] or peers
        campuses = {text(p.get('campus')) for p in campus_peers if text(p.get('campus'))}
        if not fact.get('campus') and len(campuses) > 1:
            continue
        matched.append(fact)
    # Each located statement on a page has its own revision chain. A later
    # quota/weights row must not erase the same page's separate cutoff row.
    latest = {}
    for fact in sorted(matched, key=lambda f: f.get('observed_at', '')):
        key = (fact.get('source_url'), fact.get('locator'), fact.get('year'), fact.get('major_code'),
               fact.get('department'), fact.get('mode'), fact.get('population'),
               text(fact.get('campus')), fact.get('cutoff_kind', 'department'))
        latest[key] = fact
    return list(latest.values())


def resolve_inputs(programme, dossier, history):
    facts = [f for f in matching_facts(programme, dossier) if programme['year']-3 <= f['year'] <= programme['year']]
    recent = [h for h in history if isinstance(h.get('year'), int) and programme['year']-3 <= h['year'] < programme['year']]
    scored = [f for f in facts if programme['year']-3 <= f['year'] < programme['year'] and f['values'].get('cutoff') is not None]
    official = [f for f in scored if f.get('cutoff_kind') != 'school-minimum']
    school_minima = [f for f in scored if f.get('cutoff_kind') == 'school-minimum']
    community=[r for r in compatible_scores(programme,dossier) if programme['year']-3<=r['year']<programme['year']]
    thresholds = []
    for year in sorted({h['year'] for h in recent} | {f['year'] for f in scored} | {r['year'] for r in community}, reverse=True):
        rows = [f for f in official if f['year'] == year]
        if rows:
            values = sorted(set(f['values']['cutoff'] for f in rows))
            basis, confidence = 'official-department', .95
        else:
            rows = [h for h in recent if h['year'] == year and not conflicted(h, 'cutoff_text')]
            values = sorted(set(h['cutoff'] for h in rows if numeric(h.get('cutoff')) is not None and 200 <= h['cutoff'] <= 480))
            basis = 'aligned-history'
            confidence = .8 if any(h.get('verification', {}).get('cutoff_text', {}).get('state') == 'two-source-agreement' for h in rows) else .65
            if not values:
                sources=[r for r in community if r['year']==year]
                values=sorted({r['cutoff'] for r in sources})
                basis,confidence='community-school-table',.6
            if not values:
                values=sorted({f['values']['cutoff'] for f in school_minima if f['year']==year})
                basis,confidence='official-school-minimum',.55
        if values and max(values)-min(values) <= 25:
            thresholds.append(dict(year=year, value=statistics.median(values), confidence=confidence,
                                   basis=basis, spread=max(values)-min(values)))
    # A newer university minimum must not displace an actual departmental
    # threshold from another aligned year. It is a fallback reference only.
    actual_thresholds=[t for t in thresholds if t['basis']!='official-school-minimum']
    latest = (actual_thresholds or thresholds)[0] if thresholds else None
    quota, quota_basis, extent = net_quota(programme)
    current = [f for f in facts if f['year'] == programme['year'] and f.get('population') == 'ordinary' and f['values'].get('ordinary_quota') is not None]
    current_values = {f['values']['ordinary_quota'] for f in current}
    if len(current_values) == 1:
        quota, quota_basis, extent = current_values.pop(), 'official-current-ordinary-quota', 'major'
    elif len(current_values) > 1:
        quota, quota_basis, extent = None, None, None
    historical_capacity = None
    historical_year = None
    for year in sorted({h['year'] for h in recent} | {f['year'] for f in facts if f['year'] < programme['year']}, reverse=True):
        values = {f['values']['ordinary_quota'] for f in facts if f['year'] == year and f.get('population') == 'ordinary' and f['values'].get('ordinary_quota') is not None}
        basis = 'historical-ordinary-quota'
        if not values:
            values = {h['admit_count'] for h in recent if h['year'] == year and numeric(h.get('admit_count')) is not None
                      and 0 < h['admit_count'] <= 5000 and not conflicted(h, 'admit_text')}
            basis = 'historical-admit-count'
        if len(values) == 1:
            historical_capacity = values.pop(); historical_year = year; break
    capacity = quota if quota is not None else historical_capacity
    capacity_basis = quota_basis if quota is not None else basis if historical_capacity is not None else None
    summaries = [(h['year'], score_summary(h)) for h in recent]
    summaries += [(f['year'], {key.removeprefix('admitted_'): value for key,value in f['values'].items()
                               if key in {'admitted_mean', 'admitted_minimum', 'admitted_maximum'}}) for f in facts if f['year'] < programme['year']]
    summaries = [(year, values) for year,values in summaries if values]
    score_stats = {}
    if summaries:
        year = max(y for y,_ in summaries)
        for key in ('mean', 'minimum', 'maximum'):
            values = {s[key] for y,s in summaries if y == year and key in s}
            if values and max(values)-min(values) <= 25:
                score_stats[key] = round(statistics.median(values), 2)
        score_stats['year'] = year
        if any(f['year']==year and f.get('population')=='observed-sample' and f['values'].get('admitted_mean') is not None for f in facts):
            score_stats['population']='observed-sample'
    limits = {}; limits_year = None
    if latest and latest['basis']=='community-school-table':
        sources=[r for r in community if r['year']==latest['year']]
        for subject in ('politics','english','mathematics','computer'):
            values={r['score_limits'][subject] for r in sources if subject in r['score_limits']}
            if len(values)==1:limits[subject]=values.pop();limits_year=latest['year']
    for f in sorted(facts, key=lambda x: (x['year'],x.get('cutoff_kind')!='school-minimum')):
        if f['values'].get('score_limits') and (limits_year is None or f['year']>=limits_year):
            if limits_year != f['year']: limits = {}
            limits.update(f['values']['score_limits']); limits_year = f['year']
    if not limits and latest:
        for row in recent:
            if row['year'] != latest['year'] or conflicted(row, 'cutoff_text'): continue
            bits = re.fullmatch(r'\d{3}[、,，/](\d{2})[、,，/](\d{2,3})', str(row.get('cutoff_text') or '').replace(' ', ''))
            if bits:
                limits = dict(politics=int(bits[1]), english=int(bits[1]), mathematics=int(bits[2]), computer=int(bits[2]))
                limits_year = latest['year']
    ratio_values = [h['interview_admit_ratio'] for h in recent if latest and h['year']==latest['year']
                    and numeric(h.get('interview_admit_ratio')) is not None and 1 <= h['interview_admit_ratio'] <= 5]
    for f in facts:
        if latest and f['year'] == latest['year']:
            v = f['values']
            if v.get('interview_count') is not None and v.get('ordinary_quota', 0)>0:
                ratio_values.append(v['interview_count']/v['ordinary_quota'])
    weights = {}; restrictions = {}; restriction_years = {}; weights_year = None
    for f in sorted(facts, key=lambda x: x['year']):
        for field in ('initial_weight', 'interview_weight', 'machine_test_weight'):
            if field in f['values']:
                if weights_year != f['year']: weights = {}
                weights[field] = f['values'][field]; weights_year = f['year']
        for field in ('cross_major_allowed', 'equivalent_education_allowed', 'previous_graduate_allowed'):
            if field in f['values']:
                restrictions[field] = f['values'][field]; restriction_years[field] = f['year']
    missing=[]
    if not latest: missing.append('aligned-score-threshold')
    if quota is None: missing.append('ordinary-quota')
    def same_subjects(value):
        normalized = text(value)
        return normalized == '11408' or all(code in normalized for code in ('101','201','301','408'))
    changes = [h for h in recent if latest and h['year'] == latest['year'] and h.get('exam_text') and not same_subjects(h['exam_text'])]
    spread = statistics.pstdev(t['value'] for t in thresholds) if len(thresholds)>1 else 0
    uncertainty = 10 + min(15, spread) + (8 if changes else 0) + (8 if latest and latest['confidence'] < .7 else 0) + (5 if score_stats.get('population')=='observed-sample' else 0)
    pool = [programme['unit'], department(programme.get('department')), programme.get('major_code'), programme.get('mode'), programme.get('campus')]
    if extent == 'direction': pool.append('|'.join(programme.get('directions', [])))
    return dict(threshold=latest['value'] if latest else None, threshold_year=latest['year'] if latest else None,
                threshold_basis=latest['basis'] if latest else None, threshold_confidence=latest['confidence'] if latest else 0,
                threshold_history=thresholds, score_uncertainty=round(uncertainty,2), subject_change=bool(changes),
                score_limits=limits, score_limits_year=limits_year, admitted_scores=score_stats, ordinary_quota=quota, quota_basis=quota_basis,
                capacity_proxy=capacity, capacity_basis=capacity_basis, capacity_year=programme['year'] if quota is not None else historical_year,
                competition_pool='::'.join(str(x or '') for x in pool),
                interview_admit_ratio=round(statistics.median(ratio_values),4) if ratio_values else None,
                retest_weights=weights, retest_weights_year=weights_year, restrictions=restrictions, restriction_years=restriction_years, missing=missing)


def enrich_history(row):
    return dict(row, admitted_scores=score_summary(row))
