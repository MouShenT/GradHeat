"""Personal decision scores with a common market and explicit uncertainty."""
import math
import re

from .decision_inputs import numeric, resolve_inputs
from .history_alignment import align_history
from .market_game import equilibrium, MODEL

VERSION='school-heat-victory-v2'


def logistic(score, target, scale):
    return 100/(1+math.exp(-max(-50,min(50,(score-target)/scale))))


def market(payload, dossiers, inputs):
    pools={}; conflicts=set()
    for p in payload['programmes']:
        if p['id'] not in inputs: continue
        item=inputs[p['id']];capacity=item['capacity_proxy']
        school=dossiers.get(p['unit'],{});heat=numeric(school.get('heat',{}).get('heat_value'))
        if capacity is None or capacity<=0 or heat is None: continue
        key=item['competition_pool']
        if key in pools and pools[key]['capacity']!=capacity:
            conflicts.add(key);continue
        tier=school.get('tier') or p.get('group')
        pools[key]=dict(id=key,capacity=capacity,attraction=2.5*heat/100+{'985':.45,'211':.3,'研究所':.15}.get(tier,0))
    options=[o for key,o in sorted(pools.items()) if key not in conflicts]
    return {factor:equilibrium(options,demand_factor=factor) for factor in (.75,1.,1.25)}


def evaluate(payload,dossiers,request):
    profile=request.profile
    if profile.score is None:
        return dict(ranking=[],needs_profile=True,missing=['score'],model=VERSION,
                    note='填写预计初试分数后计算胜利指数。')
    history={h['id']:h for h in payload.get('history',[])}
    alignment=payload.get('historical_alignment') or align_history(payload['programmes'],payload.get('history',[]))
    inputs={}
    for p in payload['programmes']:
        if p.get('eligible_11408') is not True or p.get('year')!=payload.get('target_year',2027): continue
        rows=[history[key] for key in alignment.get(p['id'],{}).get('matched',[]) if key in history]
        inputs[p['id']]=resolve_inputs(p,dossiers.get(p['unit'],{}),rows)
        # A recent school-local estimate remains usable when its scope is explicit.
        if inputs[p['id']]['threshold'] is None:
            claims=[c for c in dossiers.get(p['unit'],{}).get('claims',[]) if c.get('field')=='cutoff'
                    and c.get('year') in (p['year']-1,p['year']-2) and numeric(c.get('value')) is not None and 200<=c['value']<=480
                    and (p.get('major_code') and p['major_code'] in c.get('scope','') or p.get('department') and p['department'] in c.get('scope',''))]
            if claims:
                year=max(c['year'] for c in claims);values={c['value'] for c in claims if c['year']==year}
                if len(values)==1:
                    inputs[p['id']].update(threshold=values.pop(),threshold_year=year,threshold_basis='school-claim-estimate',
                                          threshold_confidence=.45,score_uncertainty=30)
                    inputs[p['id']]['missing'].remove('aligned-score-threshold')
    # This population is independent of the user's preferred school list and limit.
    games=market(payload,dossiers,inputs)
    results=[]
    for p in payload['programmes']:
        if p['id'] not in inputs: continue
        if request.programme_ids and p['id'] not in request.programme_ids: continue
        if profile.preferred_units and p['unit'] not in profile.preferred_units: continue
        if profile.mode!='all' and p.get('mode')!=profile.mode: continue
        item=inputs[p['id']];school=dossiers.get(p['unit'],{});heat=numeric(school.get('heat',{}).get('heat_value'))
        tier=school.get('tier') or p.get('group');missing=list(item['missing']);components={}
        if heat is None: missing.append('heat')
        threshold=item['threshold'];target=threshold+12 if threshold is not None else None
        if target is not None and item['admitted_scores'].get('year')==item['threshold_year'] and item['admitted_scores'].get('mean') is not None:
            target=.6*target+.4*max(threshold,item['admitted_scores']['mean'])
        scale=max(16,item['score_uncertainty']*.75)
        score_weight=60 if item['threshold_basis']!='school-claim-estimate' else 35
        if target is not None: components['score']=(score_weight,logistic(profile.score,target,scale))
        if profile.preferred_tiers: components['tier']=(18,100 if tier in profile.preferred_tiers else 30)
        background=[]
        machine=item['retest_weights'].get('machine_test_weight',.5)
        if profile.programming is not None: background.append((max(.2,machine),profile.programming*10))
        if profile.research_experience is not None: background.append((max(.2,1-machine),profile.research_experience*10))
        background_claims=[]
        for claim in school.get('claims',[]):
            scope=claim.get('scope','')
            if claim.get('field')!='background_note' or claim.get('year') not in (p['year'],p['year']-1,p['year']-2): continue
            if not (p.get('major_code') and p['major_code'] in scope or p.get('department') and p['department'] in scope): continue
            relevant=profile.cross_major and '跨考' in scope or profile.equivalent_education and '同等学力' in scope or profile.undergraduate_school and (profile.undergraduate_school in scope or re.search('双非|普通本科',profile.undergraduate_school) and '双非' in scope) or profile.undergraduate_major and profile.undergraduate_major in scope
            if relevant: background_claims.append(claim)
        if background:
            weight=12
            if item['retest_weights'].get('interview_weight') is not None:
                weight=6+18*item['retest_weights']['interview_weight']
            components['background']=(weight,sum(w*v for w,v in background)/sum(w for w,_ in background))
        quota=item['ordinary_quota']
        if quota is not None and quota>0: components['quota']=(10,100*(1-math.exp(-quota/40)))
        pressure=games[1.]['pressure'].get(item['competition_pool'])
        if pressure is None: missing.append('market-capacity-or-heat')
        ratio=item['interview_admit_ratio'];retest_penalty=min(7,4*math.log(ratio)) if ratio and ratio>1 else 0
        subject_below=[subject for subject,limit in item['score_limits'].items()
                       if getattr(profile,subject,None) is not None and getattr(profile,subject)<limit]
        rules=[];current_rules=[]
        for attribute,field in [('cross_major','cross_major_allowed'),('equivalent_education','equivalent_education_allowed'),('previous_graduate','previous_graduate_allowed')]:
            if getattr(profile,attribute) and item['restrictions'].get(field) is False:
                (current_rules if item['restriction_years'].get(field)==p['year'] else rules).append(field)
        shortfalls_current=item['score_limits_year']==p['year']
        independent={c.get('origin') or c.get('source_id'):c for c in background_claims}
        experience=sum(-1 if re.search('不接受|禁止|不允许',c['scope']) else .5 if re.search('接受|友好|录取|上岸',c['scope']) else 0 for c in independent.values())
        experience=max(-3,min(1.5,experience))
        values=[]
        def index(delta,factor):
            if target is None: return None
            sample=dict(components,score=(score_weight,logistic(profile.score+delta,target,scale)))
            base=sum(w*v for w,v in sample.values())/sum(w for w,_ in sample.values())
            hot=8*heat/100 if heat is not None else 0
            crowded=games[factor]['pressure'].get(item['competition_pool'])
            crowd_penalty=10*(1-math.exp(-max(0,crowded-1))) if crowded is not None else 0
            result=max(0,min(100,base-hot-crowd_penalty-retest_penalty+experience))
            # Historical lines/rules are reference risks, never invented 2027 bans.
            if subject_below: result*=.35
            if rules: result*=.5
            if quota==0 or current_rules or subject_below and shortfalls_current: result=0
            return result
        nominal=index(0,1.)
        if nominal is not None:
            uncertainty=item['score_uncertainty']+(6 if quota is None else 0)+(4 if heat is None else 0)
            values=[index(-uncertainty,factor) for factor in games]+[index(uncertainty,factor) for factor in games]+[nominal]
            low,high=min(values),max(values)
            victory=(1-profile.risk_aversion)*nominal+profile.risk_aversion*low
        else: low=high=victory=None
        heat_confidence=numeric(school.get('heat',{}).get('confidence_index'))
        heat_evidence=max(0,min(1,heat_confidence/100)) if heat is not None and heat_confidence is not None else .35 if heat is not None else 0
        confidence=100*(.75*item['threshold_confidence']+.15*(1 if quota is not None else .35 if item['capacity_proxy'] else 0)+.1*heat_evidence) if threshold is not None else 0
        results.append(dict(id=p['id'],unit=p['unit'],major_name=p.get('major_name'),major_code=p.get('major_code'),department=p.get('department'),tier=tier,
            heat_value=heat,victory_index=round(victory,1) if victory is not None else None,
            nominal_index=round(nominal,1) if nominal is not None else None,
            robust_index=round(low,1) if low is not None else None,
            scenario_range=[round(low,1),round(high,1)] if low is not None else None,
            confidence_index=round(confidence,1),score_fit=round(components['score'][1],1) if 'score' in components else None,
            preference_fit=components.get('tier',(0,None))[1],background_fit=components.get('background',(0,None))[1],
            threshold=threshold,threshold_year=item['threshold_year'],threshold_basis=item['threshold_basis'],score_target=round(target,1) if target is not None else None,
            ordinary_quota=quota,quota_basis=item['quota_basis'],capacity_proxy=item['capacity_proxy'],capacity_basis=item['capacity_basis'],capacity_year=item['capacity_year'],
            crowding_pressure=round(pressure,4) if pressure is not None else None,interview_admit_ratio=ratio,
            historical_subject_shortfalls=subject_below if not shortfalls_current else [],historical_rule_risks=rules,subject_change=item['subject_change'],
            current_rule_failures=current_rules,current_subject_shortfalls=subject_below if shortfalls_current else [],
            background_evidence_count=len(independent),known_background_rules=list(item['restrictions']),
            missing=missing,evidence_weight=round(confidence/100,3),components={k:round(v,2) for k,(_,v) in components.items()}))
    schools={}
    for row in results:
        old=schools.get(row['unit'])
        if old is None or (row['victory_index'] if row['victory_index'] is not None else -1)>(old['victory_index'] if old['victory_index'] is not None else -1):
            schools[row['unit']]=row
    ranked=sorted(schools.values(),key=lambda r:(r['victory_index'] is None,-(r['victory_index'] or 0),r['unit']))
    return dict(ranking=ranked[:request.limit],programmes=results,needs_profile=False,model=VERSION,data_version=request.data_version,
                game_converged=all(g['converged'] for g in games.values()),game_options=len(games[1.]['shares']),
                game=dict(model=MODEL,maximum_residual=max(g['residual'] for g in games.values()),
                          demand_factors=list(games),scope='all-eligible-programmes',real_applicants=None),
                kind='decision-index',risk_aversion=profile.risk_aversion,
                note='胜利指数结合分数、偏好、背景、净名额、复试竞争和热度；情景范围反映分数与拥挤变化，不代表录取概率。',
                missing_background_rules=bool((profile.cross_major or profile.equivalent_education or profile.previous_graduate) and not any(r['known_background_rules'] for r in results)))
