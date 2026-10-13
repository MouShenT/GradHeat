"""Parse public community tables while retaining their plan and exam scope."""
import re
from urllib.parse import urlsplit


def score_rows(markdown):
    plan=None;headers=None;rows=[]
    for lineno,line in enumerate(markdown.replace('\r','').splitlines(),1):
        heading=re.match(r'^##\s+(.+)',line)
        if heading:
            plan=heading[1].strip();headers=None;continue
        if not line.strip().startswith('|'):continue
        cells=[c.strip() for c in line.strip().strip('|').split('|')]
        if all(re.fullmatch(r':?-+:?',c) for c in cells):continue
        if '年份' in cells and ('总分线' in cells or '分数线' in cells):headers=cells;continue
        if not headers or len(cells)!=len(headers) or not plan:continue
        data=dict(zip(headers,cells));year=data.get('年份');cutoff=data.get('总分线') or data.get('分数线')
        if not year or not year.isdigit() or not 2024<=int(year)<=2035 or not re.fullmatch(r'\d{3}(?:\.\d+)?',cutoff or '') or not 200<=float(cutoff)<=500:continue
        limits={}
        for label,key,maximum in [('政治','politics',100),('英语','english',100),('数学','mathematics',150),('专业课','computer',150)]:
            value=data.get(label,'')
            if re.fullmatch(r'\d+(?:\.\d+)?',value) and 0<=float(value)<=maximum:limits[key]=float(value)
        rows.append(dict(year=int(year),degree_type=data.get('类型'),major_name=data.get('专业'),exam_text=data.get('专业课代码'),
                         cutoff=float(cutoff),score_limits=limits,plan=plan,special=plan!='普通计划',locator=f'line {lineno}'))
    return rows


def source_family(url):
    host=(urlsplit(url).hostname or '').lower()
    return 'cskaoyan.cn' if host=='cskaoyan.cn' or host.endswith('.cskaoyan.cn') else host


def compatible_scores(programme,dossier):
    """A generic degree line stays generic; no invented historical major code."""
    code=str(programme.get('major_code') or '')
    degree=programme.get('degree_type')
    if degree in ('academic','学术学位','xs'):degree='学硕'
    elif degree in ('professional','专业学位','zy','zyxw'):degree='专硕'
    elif re.fullmatch(r'(?:085|086|145)\d{3}',code):degree='专硕'
    elif re.fullmatch(r'(?:081|082|083|084|140)\d{3}',code):degree='学硕'
    else:degree=None
    result=[]
    for source in dossier.get('community_sources',[]):
        if source.get('unit')!=programme['unit'] or source.get('scope')!='institution':continue
        if source.get('campus') and source['campus']!=programme.get('campus'):continue
        for row in source.get('scores',[]):
            if row['special'] or row.get('exam_text')!='11408' or row.get('degree_type')!=degree:continue
            name=row.get('major_name')
            if name not in ('-',None,'') and name!=programme.get('major_name'):continue
            result.append(dict(row,source_url=source['score_url'],source_family=source_family(source['site_url'])))
    return result
