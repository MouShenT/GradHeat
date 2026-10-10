"""Data-only view. Evidence remains in the internal repository and MySQL."""
import hashlib,json,re
from pathlib import Path
from .repository import resolve_degree,source_identity,read_json
from .corroboration import Corroborator,observations,apply_public
from .information_match import fact_parts
from .history_alignment import align_history
from .field_lineage import load_exclusions,excluded

def integer(value):
    text=str(value if value is not None else '').strip()
    return int(text) if re.fullmatch(r'\d+',text) else None


def cutoff_number(value):
    parts=fact_parts({},'cutoff_text',value)
    return integer(parts[0][1]) if parts and parts[0][0]=='retest_cutoff' else None


def interview_ratio(retest, admits):
    # Compound counts such as '316+2专项' or '6+29调剂' are deliberately unknown.
    a,b=integer(retest),integer(admits)
    return round(a/b,4) if a is not None and b and a>=b else None


def clean_text(value):
    if value is None:return None
    text=str(value)
    # Free text is never a vehicle for a source link or a local artifact path.
    text=re.sub(r'https?://\S+|[A-Za-z]:[\\/][^\s；]+','',text)
    return text.strip() or None


def identifier(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True).encode()).hexdigest()[:24]


def build_public(repo):
    groups={}
    for row in repo.programmes.values():groups.setdefault(source_identity(row),[]).append(row)
    programmes=[]
    for identity,rows in groups.items():
        row=rows[0];plans=list(dict.fromkeys(clean_text(x.get('planned_major_raw')) for x in rows if x.get('planned_major_raw')))
        plans=[x for x in plans if x]
        matched={x.get('eligible_11408') for x in rows}
        subjects={tuple(x.get('subjects') or []) for x in rows}
        degree,_=resolve_degree(row)
        programmes.append(dict(id=identifier(identity),unit=row['unit'],group=repo.units[row['unit']]['group'],
            year=row['cohort'],department=clean_text(row.get('department')),major_code=row.get('major_code'),major_name=clean_text(row.get('major_name')),
            degree_type=degree,mode=row.get('mode'),route=row.get('route'),campus=clean_text(row.get('campus')),subjects=list(next(iter(subjects))) if len(subjects)==1 else [],
            eligible_11408=True if matched=={True} else False if matched=={False} else None,
            plan_text='；'.join(plans) or None,plan_variants=plans,ordinary_quota=None,
            plan_status='人数待补' if not plans else '多版人数待核' if len(plans)>1 else '计划口径待核',
            publication_stage=clean_text(row.get('publication_stage')),directions=[clean_text(x) for x in row.get('directions',[])],
            scope=clean_text(row.get('comparison_pool_scope'))))
    history=[]
    dossiers_path=repo.root/'.research/unit-dossiers-20261001/dossiers.json'
    for dossier in read_json(dossiers_path) if dossiers_path.is_file() else []:
        for year,rows in dossier.get('secondary',{}).items():
            for row in rows:
                if not row.get('aligned'):continue
                fields=row['fields'];name=fields.get('专业名称')
                if not name:continue
                item=dict(unit=dossier['unit'],year=int(year),department=clean_text(row.get('department')),
                    major_name=clean_text(name),exam_text=clean_text(fields.get('初试科目')),
                    cutoff=cutoff_number(fields.get('分数线')),cutoff_text=clean_text(fields.get('分数线')),
                    retest_count=integer(fields.get('复试人数')),retest_text=clean_text(fields.get('复试人数')),
                    admit_count=integer(fields.get('拟录取人数',fields.get('录取人数'))),admit_text=clean_text(fields.get('拟录取人数',fields.get('录取人数'))),
                    interview_admit_ratio=interview_ratio(fields.get('复试人数'),fields.get('拟录取人数',fields.get('录取人数'))),
                    admitted_score_text=clean_text(fields.get('拟录取分数')),interview_score_text=clean_text(fields.get('进复试总分均分')),
                    status='待核',scope='该表行统计范围；普通/专项、一志愿/调剂及学习方式须分别确认')
                item['id']=identifier(item);history.append(item)
    lines=[]
    tablepath=repo.root/'.research/unit-dossiers-20261001/official-table-facts.json'
    for row in read_json(tablepath) if tablepath.is_file() else []:
        score=None
        for header,value in zip(row.get('headers',[]),row.get('values',[])):
            if header in ('总分','复试分数线'):score=integer(value)
        if score is None:continue
        item=dict(unit=row['unit'],year=row.get('year'),label=clean_text(row.get('label')),cutoff=score,status='范围待核')
        item['id']=identifier(item);lines.append(item)
    lists=[]
    for row in repo.data.get('history_candidates',[]):
        lists.append(dict(id=identifier([row.get('unit'),row.get('year'),row.get('pool'),row.get('n'),row.get('minimum'),row.get('maximum')]),
            unit=row['unit'],year=row['year'],scope=clean_text(row.get('pool')),population=row.get('population'),exam_text=clean_text(row.get('exam_text')),n=row.get('n'),minimum=row.get('minimum'),maximum=row.get('maximum'),mean=row.get('mean'),median=row.get('median'),
            status='名单分组待核',note='名单提取人数与初试分数；专业范围及完整性待核，不视为全专业录取统计'))
    external_path=repo.root/'.research/github-sources/candidates.json'
    extra=read_json(external_path) if external_path.is_file() else []
    comparisons_path=repo.root/'.research/github-sources/comparison.json'
    conflicts=set()
    if comparisons_path.is_file():
        for row in read_json(comparisons_path).get('rows',[]):
            if any(f['state']=='value-conflict' for f in row.get('fields',[])):conflicts.add(row['candidate_id'])
    # Candidate repositories supplement history; unknown-year catalogues never
    # silently add 2027 plans. Conflicting scopes stay in the internal queue.
    exclusions=load_exclusions(repo.root)
    for row in extra:
        if excluded(row,'*',exclusions):continue
        if row['kind']=='history' and row.get('scope_status')=='pending':
            item=dict(unit=row['unit'],year=row['year'],department=clean_text(row.get('department')),major_name=clean_text(row.get('major_name')),exam_text=clean_text(row.get('exam_text')),
                cutoff=cutoff_number(row.get('cutoff_text')),cutoff_text=clean_text(row.get('cutoff_text')),retest_count=integer(row.get('retest_text')),retest_text=clean_text(row.get('retest_text')),
                admit_count=integer(row.get('admit_text')),admit_text=clean_text(row.get('admit_text')),interview_admit_ratio=interview_ratio(row.get('retest_text'),row.get('admit_text')),
                admitted_score_text=clean_text(row.get('admitted_score_text')),interview_score_text=None,
                status='数值冲突待核' if row['id'] in conflicts else '待核',scope='院系与专业候选统计；人数及年度考试口径待核')
            item['id']=identifier(item)
            if not any(x['id']==item['id'] for x in history):history.append(item)
        elif row['kind']=='distribution':
            lists.append(dict(id=identifier(row['id']),unit=row['unit'],year=row['year'],scope=clean_text(row.get('scope')),population=row.get('population'),exam_text=clean_text(row.get('exam_text')),n=row.get('n'),minimum=row.get('minimum'),maximum=row.get('maximum'),mean=row.get('mean'),median=row.get('median'),
                status='录取分组待核' if row.get('population')=='enrolled' else '复试分组待核',note='录取者初试分数统计' if row.get('population')=='enrolled' else '该分布并非最终录取者分布'))
    units=[dict(name=u['name'],group=u['group']) for u in repo.units.values()]
    seen={u['name'] for u in units}
    for row in history+lists:
        if row['unit'] not in seen:
            seen.add(row['unit']);units.append(dict(name=row['unit'],group='其他招生单位'))
    payload=dict(target_year=2027,data_as_of=repo.data['as_of'],units=units,
        programmes=programmes,history=history,cutoff_rows=lines,admission_groups=lists,
        ratio_definition='复录比＝同年度、同统计范围的复试人数÷拟录取人数；待核人数计算的比值也保持待核。',
        counts=dict(units=len(units),programmes=len(programmes),matched_programmes=sum(x['eligible_11408'] is True for x in programmes),history_rows=len(history)))
    payload['historical_alignment']=align_history(programmes,history)
    return apply_public(payload,Corroborator(observations(repo)))
