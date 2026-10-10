"""Two distinct origin chains agree: user-defined confirmation, not official proof."""
import hashlib,json,re
from collections import Counter,defaultdict
from decimal import Decimal,InvalidOperation
from urllib.parse import urlsplit
from .information_match import POLICY,identity,fact_parts,Matcher,same_value
from .field_lineage import load_overrides,load_exclusions,excluded,resolve as resolve_field_lineage

HISTORY_FIELDS=('cutoff_text','retest_text','admit_text','admitted_score_text')
AGREED=('two-source-agreement','three-source-agreement')

def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def norm(value):
    return re.sub(r'\s+','',str(value or '')).translate(str.maketrans({'（':'(', '）':')','：':':','；':';','，':','}))

def canonical(value):
    if isinstance(value,(list,tuple)) and not value:return None
    if value is None or str(value).strip() in ('','—','-','NC','未知'):return None
    text=norm(value)
    try:
        if re.fullmatch(r'\d+(\.\d+)?',text):return format(Decimal(text).normalize(),'f')
    except InvalidOperation:pass
    return text

def origin(row):
    # Copies carrying their upstream provider count as that provider, not a repo.
    if row.get('origin_id'):return str(row['origin_id'])
    family=row.get('source_family')
    raw=row.get('raw') if isinstance(row.get('raw'),dict) else {}
    attribution=str(raw.get('srcLabel') or '')+' '+str(raw.get('src') or '')
    if row.get('repository') and family not in ('noobdream','codebrick','chsi-directory-repost') and re.search(r'N诺|noobdream',attribution,re.I):
        return 'noobdream'
    if family:return str(family)
    host=(urlsplit(row.get('source_url') or '').hostname or '').lower()
    for suffix,name in [('noobdream.com','noobdream'),('codebrick.tech','codebrick'),('chsi.com.cn','chsi-directory-repost')]:
        if host==suffix or host.endswith('.'+suffix):return name
    if host:
        if host.endswith('.edu.cn'):return '.'.join(host.split('.')[-3:])
        return host[4:] if host.startswith('www.') else host
    repo=row.get('repository')
    if repo in ('csseky/cskaoyan','wenliang90/408exam'):return 'github:csseky/cskaoyan'
    return 'github:'+repo if repo else None

def scope(row,kind):
    return identity(row,kind)

def official_catalogue_host(host):
    # Institutes publish on CAS/UCAS domains as well as university domains.
    # Require a domain boundary, so lookalike suffixes are never official.
    return host.endswith('.edu.cn') or any(host==domain or host.endswith('.'+domain)
        for domain in ('chsi.com.cn','cas.cn','ucas.ac.cn'))

def observations(repo):
    out=[];hashes={};lineage_reviews=load_overrides(repo.root);exclusions=load_exclusions(repo.root)
    def add(row,kind,fields,official=False):
        key=scope(row,kind);provider=origin(row)
        if key is None or provider is None:return
        for field,value in fields.items():
            if excluded(row,field,exclusions):continue
            raw=value
            value=canonical(value)
            if value is None:continue
            lineage=resolve_field_lineage(row,field,raw,lineage_reviews,canonical)
            item=dict(scope=key,scope_id=digest(key),field=field,value=value,origin_id=lineage['origin_id'] if lineage else provider,
                raw_value=raw,
                official=bool(official),artifact=row.get('source_artifact') or row.get('artifact'),
                artifact_sha256=row.get('source_sha256') or row.get('artifact_sha256'),
                source_url=lineage['source_url'] if lineage else row.get('source_url'),locator=row.get('locator'),source_record_id=row.get('id'))
            if lineage:
                item.update(origin_resolution=lineage['reason'],lineage_quote=lineage['quote'],
                    lineage_review_artifact=lineage['review_artifact'],
                    lineage_review_sha256=lineage['review_sha256'],lineage_reviewed_at=lineage['reviewed_at'])
                if lineage.get('review_evidence_artifact'):
                    item.update(lineage_evidence_artifact=lineage['review_evidence_artifact'],
                        lineage_evidence_sha256=lineage['review_evidence_sha256'])
            if item['artifact'] and not item['artifact_sha256']:
                from pathlib import Path
                path=Path(item['artifact'])
                if path.is_file():
                    if path not in hashes:
                        with path.open('rb') as stream:hashes[path]=hashlib.file_digest(stream,'sha256').hexdigest()
                    item['artifact_sha256']=hashes[path]
            item['id']=digest(item);out.append(item)
    for p in repo.programmes.values():
        host=urlsplit(p.get('source_url') or '').hostname or ''
        add(p,'programme',{'plan_text':p.get('planned_major_raw'),'subjects':p.get('subjects')},official_catalogue_host(host.lower()))
    def read(path,default):
        return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default
    for d in read(repo.root/'.research/unit-dossiers-20261001/dossiers.json',[]):
        for year,rows in d.get('secondary',{}).items():
            for r in rows:
                if not r.get('aligned'):continue
                f=r['fields'];row=dict(r,unit=d['unit'],year=int(year),major_name=f.get('专业名称'))
                add(row,'history',dict(zip(HISTORY_FIELDS,[f.get('分数线'),f.get('复试人数'),f.get('拟录取人数',f.get('录取人数')),f.get('拟录取分数')]))|{'exam_text':f.get('初试科目')})
    for r in read(repo.root/'.research/github-sources/candidates.json',[]):
        if r['kind']=='history' and r.get('scope_status')=='pending':add(r,'history',{f:r.get(f) for f in HISTORY_FIELDS+('exam_text','plan_text')})
        elif r['kind']=='catalogue':
            add(r,'programme',{'plan_text':r.get('plan_text'),'subjects':r.get('subjects')})
            # Explicit historical quotas are usable as historical plans. The synchronisation
            # date does not supply a year for the current catalogue or its exam subjects.
            for year in (2026,2027):
                quota=r.get('enrollment'+str(year))
                if quota is not None:
                    raw=r.get('raw') or {}
                    add(dict(r,year=year,mode=raw.get('studyMode'),degree_type=raw.get('degreeType')),'programme',{'plan_text':str(quota)})
        elif r['kind']=='distribution':add(r,'distribution',{f:r.get(f) for f in ('n','minimum','maximum','mean','median','cutoff')})
    for r in repo.data.get('history_candidates',[]):
        add(dict(r,scope=r.get('pool')),'distribution',{f:r.get(f) for f in ('n','minimum','maximum','mean','median')})
    for r in read(repo.root/'.research/unit-dossiers-20261001/official-table-facts.json',[]):
        score=next((v for h,v in zip(r.get('headers',[]),r.get('values',[])) if h in ('总分','复试分数线')),None)
        add(r,'line',{'cutoff':score},True)
    # Curated institution/repository additions carry their own origin and scope.
    for r in read(repo.root/'.research/source-consensus/additional-observations.json',[]):
        if not r.get('origin_id') or not r.get('source_url'):raise ValueError('Additional observation needs origin and original URL')
        if not r.get('source_artifact'):raise ValueError('Additional observation needs a saved original')
        if r.get('scope_status')=='scope-conflict':continue
        add(r,r['record_kind'],r['fields'],r.get('official',False))
    # Public social evidence enters the same semantic matcher only after scope,
    # exact quotation, original hash and upstream origin have been checked.
    import sys
    from pathlib import Path
    helper = str(repo.root / 'tools/research')
    if helper not in sys.path:sys.path.insert(0,helper)
    from social_evidence import reviewed_observations
    for r in reviewed_observations(repo.root):
        add(r,r['record_kind'],r['fields'],r.get('official',False))
    return list({x['id']:x for x in out}.values())

class Corroborator:
    def __init__(self,rows):
        self.rows=rows;self.policy=POLICY;self.matcher=Matcher(rows)

    def decision(self,row,kind,field,value):
        return self._decision(scope(row,kind),field,value)

    def _decision(self,key,field,value):
        parts=[];evidence=set();all_origins=set();competing=set()
        for metric,number,qualifiers in fact_parts(key or {},field,value):
            candidates,resolved,ambiguous=self.matcher.candidates(dict(key,**qualifiers),metric) if key else ([],None,[])
            origins=defaultdict(list)
            for r in candidates:
                origins[r['origin_id']].append(r['fact_value']);evidence.add(r['id'])
                if not same_value(metric,r['fact_value'],number):competing.add(r['fact_value'])
            agreeing=sorted(o for o,values in origins.items() if all(same_value(metric,v,number) for v in values))
            official=[r for r in candidates if r['official']]
            official_state='conflict' if any(not same_value(metric,r['fact_value'],number) for r in official) else 'matched' if official else 'not-found-in-library'
            state='conflict' if official_state=='conflict' else 'three-source-agreement' if len(agreeing)>=3 else 'two-source-agreement' if len(agreeing)>=2 else 'pending'
            parts.append(dict(metric=metric,value=number,state=state,agreeing_sources=len(agreeing),official_state=official_state,
                resolved_scope=resolved,ambiguous_facets=ambiguous,agreeing_origins=agreeing))
            all_origins.update(agreeing)
        states=[p['state'] for p in parts]
        state='conflict' if 'conflict' in states else 'three-source-agreement' if states and all(s=='three-source-agreement' for s in states) else 'two-source-agreement' if states and all(s in AGREED for s in states) else 'partial-agreement' if any(s in AGREED for s in states) else 'pending'
        official_state='conflict' if any(p['official_state']=='conflict' for p in parts) else 'matched' if parts and all(p['official_state']=='matched' for p in parts) else 'not-found-in-library'
        public=dict(state=state,agreeing_sources=min((p['agreeing_sources'] for p in parts),default=0),official_state=official_state,
            matching='同招生事项识别',parts=[{k:p[k] for k in ('metric','state','agreeing_sources','official_state')} for p in parts])
        internal=dict(policy=POLICY,scope=key,scope_id=digest(key),field=field,value=canonical(value),
            state=state,agreeing_sources=public['agreeing_sources'],official_state=official_state,parts=parts,
            agreeing_origins=sorted(all_origins),observation_ids=sorted(evidence),competing_values=sorted(competing))
        internal['id']=digest(internal)
        return public,internal

    def decisions(self):
        found={}
        for r in self.rows:
            _,item=self._decision(r['scope'],r['field'],r.get('raw_value',r['value']))
            found[item['id']]=item
        return list(found.values())

    def information_agreements(self,decisions):
        buckets=defaultdict(list);facets=('unit','year','department','major','major_code','degree','mode','route','campus','special','directions','plan_extent','exemption')
        parts=[(d,p) for d in decisions for p in d['parts'] if p['state'] in AGREED]
        # Start with precise means so one rounded value cannot bridge conflicting precise values.
        def precision(item):
            p=item[1]
            return -Decimal(p['value']).as_tuple().exponent if p['metric'].endswith('_mean') and re.fullmatch(r'\d+(?:\.\d+)?',p['value']) else 0
        for decision,part in sorted(parts,key=precision,reverse=True):
            item=dict(scope={f:part['resolved_scope'].get(f) for f in facets},metric=part['metric'],value=part['value'])
            bucket=buckets[digest(dict(scope=item['scope'],metric=item['metric']))]
            matches=[x for x in bucket if same_value(item['metric'],x['value'],item['value'])]
            target=matches[0] if len(matches)==1 else next((x for x in bucket if x['value']==item['value']),None)
            if target is None:
                target=dict(item,id=digest(item),agreeing_origins=part['agreeing_origins'],decision_ids=[]);bucket.append(target)
            if len(part['agreeing_origins'])>len(target['agreeing_origins']):target['agreeing_origins']=part['agreeing_origins']
            target['decision_ids'].append(decision['id'])
        return sorted([x for bucket in buckets.values() for x in bucket],key=lambda x:x['id'])

def apply_public(payload,checker):
    missing={}
    for collection,kind,fields in [('programmes','programme',('plan_text','subjects')),('history','history',HISTORY_FIELDS+('exam_text',)),('cutoff_rows','line',('cutoff',)),('admission_groups','distribution',('n','minimum','maximum','mean','median'))]:
        for row in payload[collection]:
            result={}
            if kind=='programme' and len(row.get('plan_variants',[]))>1:
                scoped=dict(row,comparison_pool_scope=row.get('scope'))
                agreed=[v for v in row['plan_variants'] if checker.decision(scoped,kind,'plan_text',v)[0]['state'] in AGREED]
                if len(agreed)==1:
                    row['plan_text']=agreed[0]
                    key=(row['unit'],row['year']);missing[key]=dict(unit=row['unit'],year=row['year'],note='展示多源一致的计划值；其他不一致版本继续保留在信息库。')
            for field in fields:
                if canonical(row.get(field)) is None:continue
                scoped=dict(row,comparison_pool_scope=row.get('scope')) if kind=='programme' else row
                verdict,_=checker.decision(scoped,kind,field,row[field]);result[field]=verdict
            row['verification']=result
            # The plan status describes the plan; independently matched subjects do not certify seats.
            statuses=[v['state'] for f,v in result.items() if kind!='programme' or f=='plan_text']
            accepted=[s in AGREED for s in statuses]
            if accepted and all(accepted):
                row['plan_status' if kind=='programme' else 'status']='三源一致' if all(s=='three-source-agreement' for s in statuses) else '两源一致'
                if kind=='history':row['scope']='本行统计范围；官方资料对应情况见末尾。'
            elif (any(accepted) or 'partial-agreement' in statuses) and kind!='programme':
                parts=[p for v in result.values() for p in v['parts'] if p['state'] in AGREED]
                row['status']='部分信息三源一致' if parts and all(p['state']=='three-source-agreement' for p in parts) else '部分信息两源一致'
            if any(v['official_state']=='not-found-in-library' for v in result.values()):
                key=(row['unit'],row['year']);note='已入库官方资料中未找到部分对应数值；不代表学校未公布。'
                if key in missing:note=missing[key]['note'] if note in missing[key]['note'] else missing[key]['note']+' '+note
                missing[key]=dict(unit=row['unit'],year=row['year'],note=note)
    payload['official_notes']=sorted(missing.values(),key=lambda x:(x['unit'],x['year']))
    payload['verification_rule']='先识别同一年度、院校、专业和招生事项，再比较数值及含义；至少两个不同来源一致则去掉待验证，分别标注两源或三源一致。同源转载仅计一次，年份或范围冲突不合并。'
    agreements=checker.information_agreements(checker.decisions())
    payload['verification_summary']=dict(policy=POLICY,information=len(agreements),
        two_sources=sum(len(x['agreeing_origins'])==2 for x in agreements),
        three_or_more_sources=sum(len(x['agreeing_origins'])>=3 for x in agreements),
        by_metric=dict(Counter(x['metric'] for x in agreements)))
    return payload
