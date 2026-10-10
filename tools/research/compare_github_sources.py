"""Parse downloaded data and compare exact scope/year; never execute repositories."""
import hashlib,json,re,sys
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'.research/github-sources'
sys.path.insert(0,str(ROOT/'crawler'))
sys.path.insert(0,str(ROOT/'workbench'))
from gradheat.material_store import archive,encode,migrate
from gradheat.vm_db import connect_vm
from gradheat_workbench.admissions import integer,interview_ratio

def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def sha_file(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
def norm(value):return re.sub(r'\s+','',str(value or '')).replace('（','(').replace('）',')')
def family(url,default):
    host=urlsplit(url or '').hostname or ''
    if host.endswith('noobdream.com'):return 'noobdream'
    if host.endswith('codebrick.tech'):return 'codebrick'
    if host.endswith('chsi.com.cn'):return 'chsi-directory-repost'
    return default


def collect(downloads):
    candidates=[];files=set()
    def add(report,path,kind,row,ordinal,year=None):
        files.add(path);sha=sha_file(path)
        body=dict(row,repository=report['repo'],commit=report['commit'],artifact_sha256=sha,artifact=str(path),locator=ordinal,kind=kind,year=year if year is not None else row.get('year'),status='external-unverified')
        body['id']=hashlib.sha256(encode(body).encode()).hexdigest();candidates.append(body)
    for report in downloads['repositories']:
        root=Path(report['path']);repo=report['repo']
        if repo=='Laz8Noy/kaoyan408-share':
            path=root/'06-院校数据库/data/score_matrix.json';x=read(path)
            for si,school in enumerate(x['schools']):
                for ui,row in enumerate(school.get('units',[])):
                    for year,line in row.get('lines',{}).items():
                        if line is None and int(year)!=2026:continue
                        current=int(year)==2026
                        item=dict(unit=school['name'],department=row.get('college'),major_name=row.get('direction'),exam_text=row.get('subj'),
                            cutoff_text=str(line) if line is not None else str(row.get('line2026') or ''),
                            plan_text=row.get('planRaw') if current else None,
                            retest_text=row.get('retestRaw') if current else None,admit_text=row.get('admitRaw') if current else None,
                            admitted_score_text=('均分 '+str(row.get('avgRaw') or '—')+'；范围 '+str(row.get('minRaw') or '—')+'–'+str(row.get('maxRaw') or '—')) if current else None,
                            approximate_fields=row.get('_approx',[]),source_url=row.get('kqUrl'),source_family=family(row.get('kqUrl'),'Laz8Noy/kaoyan408-share'),raw=row)
                        add(report,path,'aggregate-summary',item,f'schools[{si}].units[{ui}].lines.{year}',int(year))
            for path in sorted((root/'06-院校数据库/data/schools').glob('*.json')):
                school=read(path)
                for ui,row in enumerate(school.get('units',[])):
                    declared=row.get('subjectClass');secondary=row.get('nnSubjects','')
                    exam='11408' if secondary in ('11408','英一数一408') else '22408' if secondary in ('22408','英二数二408') else declared
                    mismatch=bool(secondary and declared in ('11408','22408','非408') and exam!=declared)
                    for year,line in row.get('linesByYear',{}).items():
                        if line is None and int(year)!=2026:continue
                        current=int(year)==2026
                        item=dict(unit=school['name'],department=row.get('nnCollege') or row.get('college'),major_name=row.get('nnProg') or row.get('direction'),exam_text=exam if current else None,
                            cutoff_text=str(line) if line is not None else str(row.get('line2026') or ''),
                            plan_text=row.get('plan2026') if current else None,retest_text=row.get('retestCnt') if current else None,admit_text=row.get('admitCnt') if current else None,
                            admitted_score_text=('均分 '+str(row.get('admitAvg') or '—')+'；范围 '+str(row.get('admitMin') or '—')+'–'+str(row.get('admitMax') or '—')) if current else None,
                            source_url=row.get('nnUrl') or row.get('kaoqingUrl'),source_family=family(row.get('nnUrl') or row.get('kaoqingUrl'),'Laz8Noy/kaoyan408-share'),
                            scope_status='scope-conflict' if mismatch else 'major-unresolved' if not row.get('nnProg') else 'pending',raw=row)
                        add(report,path,'history',item,f'units[{ui}].linesByYear.{year}',int(year))
            path=root/'06-院校数据库/data/yz408_catalog.json'
            for n,row in enumerate(read(path)['items']):
                add(report,path,'catalogue',dict(unit=row.get('s'),department=row.get('c'),major_code=row.get('mc'),major_name=row.get('mn'),subjects=row.get('sub'),
                    plan_text=row.get('plan'),enrollment2026=row.get('e26'),enrollment2027=None,source_family='chsi-directory-repost',year_status='未取得目录招生年度；不按同步时间认定为2027',raw=row),f'items[{n}]')
            for path in sorted((root/'10-录取分数统计/data/schools').glob('*.json')):
                school=read(path)
                for pi,programme in enumerate(school.get('programs',[])):
                    for yi,row in enumerate(programme.get('stats',{}).get('years',[])):
                        total=next((s for s in row.get('subjects',[]) if s.get('key')=='total'),{})
                        item=dict(unit=school['name'],scope=programme['programName'],exam_text=row.get('exam408Type'),population=row.get('distPopulation'),n=total.get('count'),
                            minimum=total.get('min'),maximum=total.get('max'),mean=total.get('mean'),median=total.get('median'),cutoff=row.get('retestLineTotal'),
                            source_url=row.get('sourceUrl'),source_family='codebrick',count_semantics='retestCount为该库分类人数，不作为进复试人数使用',raw=row)
                        add(report,path,'distribution',item,f'programs[{pi}].stats.years[{yi}]',row.get('year'))
            path=root/'10-录取分数统计/data/catalog_2027.json'
            for si,school in enumerate(read(path).get('schools',[])):
                for pi,row in enumerate(school.get('programs',[])):
                    add(report,path,'exam-change',dict(unit=school['schoolName'],scope=row.get('scope'),exam_text=row.get('exam408Type'),source_url=row.get('sourceUrl'),raw=row),f'schools[{si}].programs[{pi}]',2027)
        elif repo=='zhwen2703-hash/kaoyan-recommendation-platform':
            path=root/'data/408-offerings.json'
            for n,row in enumerate(read(path)['items']):
                add(report,path,'catalogue',dict(unit=row.get('schoolName'),department=row.get('collegeName'),major_code=row.get('majorCode'),major_name=row.get('majorName'),
                    subjects=[s.get('code') for s in row.get('subjects',[])],plan_text=row.get('plannedEnrollment'),enrollment2026=row.get('enrollment2026'),enrollment2027=row.get('enrollment2027'),
                    source_url=row.get('sourceUrl'),source_family='chsi-directory-repost',year_status='同步时间不是招生年度；没有明确年度的plan不并入2027',raw=row),f'items[{n}]',row.get('year'))
            path=root/'data/admission-units.json'
            for n,row in enumerate(read(path)['units']):
                add(report,path,'unit-directory',dict(unit=row['name'],raw=row),f'units[{n}]')
        elif repo=='ccdgr/cs-assistant':
            path=root/'backend/internal/model/schools.json'
            x=read(path)
            for n,row in enumerate(x if isinstance(x,list) else x.get('schools',[])):
                add(report,path,'unit-directory',dict(unit=row.get('name'),raw=row),f'schools[{n}]')
    return candidates,files


def compare(candidates):
    dossiers=read(ROOT/'.research/unit-dossiers-20261001/dossiers.json');local={}
    for d in dossiers:
        for year,rows in d['secondary'].items():
            for row in rows:
                if not row.get('aligned'):continue
                key=(d['unit'],int(year),norm(row.get('department')),norm(row['fields'].get('专业名称')))
                local.setdefault(key,[]).append(row)
    results=[]
    for row in candidates:
        if row['kind']!='history':continue
        key=(row['unit'],row['year'],norm(row.get('department')),norm(row.get('major_name')))
        matches=local.get(key,[])
        if not matches:
            results.append(dict(candidate_id=row['id'],unit=row['unit'],year=row['year'],state='scope-unmatched'));continue
        for other in matches:
            comparisons=[]
            for a,b in [('cutoff_text','分数线'),('retest_text','复试人数'),('admit_text','拟录取人数')]:
                left,right=integer(row.get(a)),integer(other['fields'].get(b))
                if left is not None and right is not None:
                    same_family=row['source_family']==family(other.get('source_url'),'unknown')
                    comparisons.append(dict(field=a,external=left,existing=right,state='value-conflict' if left!=right else 'same-value-same-origin' if same_family else 'same-value-independence-unconfirmed'))
            results.append(dict(candidate_id=row['id'],unit=row['unit'],year=row['year'],state='scope-matched',fields=comparisons,
                existing_artifact_sha256=other.get('source_sha256'),existing_url=other.get('source_url')))
    # Catalogues remain in their actual/unknown year. Subject agreement is a
    # discovery check, never a 2027 eligibility/plan upgrade.
    catalogue_checks=[]
    base=[p for d in dossiers for p in d.get('catalogue',[])]
    for row in candidates:
        if row['kind']!='catalogue':continue
        matches=[p for p in base if p.get('unit')==row['unit'] and p.get('major_code')==row.get('major_code') and re.sub(r'^\d+\s*','',str(p.get('department') or ''))==str(row.get('department') or '')]
        catalogue_checks.append(dict(candidate_id=row['id'],unit=row['unit'],state='scope-candidate' if matches else 'scope-unmatched',
            eligible_subject_combination=row.get('subjects')==['101','201','301','408'],year_state='confirmed' if row.get('year') else 'unknown',not_promoted=True))
    states=Counter(x['state'] for row in results for x in row.get('fields',[]))
    left={}
    for row in candidates:
        if row['kind']=='catalogue' and row['repository']=='Laz8Noy/kaoyan408-share':
            left.setdefault((row['unit'],norm(row.get('department')),row.get('major_code')),[]).append(row)
    pairs=[]
    for row in candidates:
        if row['kind']!='catalogue' or row['repository']!='zhwen2703-hash/kaoyan-recommendation-platform':continue
        for prior in left.get((row['unit'],norm(row.get('department')),row.get('major_code')),[]):
            a,b=integer(prior.get('enrollment2026')),integer(row.get('enrollment2026'))
            pairs.append(dict(unit=row['unit'],department=row.get('department'),major_code=row.get('major_code'),left_candidate=prior['id'],right_candidate=row['id'],
                subject_state='same-subjects-same-origin' if prior.get('subjects')==row.get('subjects') else 'subject-conflict',
                count2026_state='not-comparable' if a is None or b is None else 'same-count-same-origin' if a==b else 'count-conflict',left_2026=a,right_2026=b,
                year2027_state='not-promoted',scope='仓库标注2026目录人数；未复核名额口径，不当作实际录取人数'))
    return dict(history_rows=len(results),matched_scope=sum(x['state']=='scope-matched' for x in results),field_comparisons=dict(states),
        rows=results,catalogue_checks=catalogue_checks,repository_catalogue_pairs=pairs,repository_pair_states=dict(Counter(p['count2026_state'] for p in pairs)),
        limitation='同数值与同源转载不算独立验证；年度未知的计划不替代2027官方目录。')


def migrate_external(con):
    path=ROOT/'crawler/sql/004_external_sources.sql';checksum=sha_file(path)
    with con.cursor() as cur:
        cur.execute('SELECT checksum FROM research_schema_migration WHERE migration_id=%s',(path.name,));old=cur.fetchone()
        if old:
            if old[0]!=checksum:raise ValueError('External migration checksum changed')
            return
        for sql in path.read_text(encoding='utf-8').split(';'):
            if sql.strip():cur.execute(sql)
        cur.execute('INSERT INTO research_schema_migration(migration_id,checksum) VALUES(%s,%s)',(path.name,checksum))
    con.commit()


def run():
    downloads=read(OUT/'latest.json');candidates,files=collect(downloads);comparison=compare(candidates)
    raw=[p for p in (OUT/'raw').iterdir() if p.suffix in ('.zip','.json')]
    paths=list(dict.fromkeys(raw+sorted(files)))
    with connect_vm(OUT) as con:
        migrate(con,ROOT);migrate_external(con)
        with con.cursor() as cur:
            cur.execute("SELECT GET_LOCK('gradheat_material_archive',60)")
            if cur.fetchone()[0]!=1:raise RuntimeError('Material archive busy')
        try:materials=archive(con,[(p,'repository-original') for p in paths],ROOT)
        finally:
            with con.cursor() as cur:cur.execute("SELECT RELEASE_LOCK('gradheat_material_archive')")
        try:
            with con.cursor() as cur:
                cur.executemany('INSERT IGNORE INTO external_repository_snapshot(repo,commit_sha,archive_sha256,manifest_json) VALUES(%s,%s,%s,%s)',
                    [(x['repo'],x['commit'],x['sha256'],encode(x)) for x in downloads['repositories']])
                cur.executemany('INSERT IGNORE INTO external_candidate(candidate_id,repo,commit_sha,kind,unit_name,cohort,department,artifact_sha256,payload_json) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                    [(x['id'],x['repository'],x['commit'],x['kind'],x.get('unit'),x.get('year'),x.get('department'),x['artifact_sha256'],encode(x)) for x in candidates])
                cid=hashlib.sha256(encode(comparison).encode()).hexdigest()
                cur.execute('INSERT IGNORE INTO external_comparison(comparison_id,payload_json) VALUES(%s,%s)',(cid,encode(comparison)))
            con.commit()
        except Exception:con.rollback();raise
    # All versions remain in MySQL. These files point at current repo snapshots.
    for name,value in [('candidates.json',candidates),('comparison.json',comparison)]:
        temp=OUT/(name+'.tmp');temp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(OUT/name)
    report={'repositories':len(downloads['repositories']),'candidates':len(candidates),'kinds':dict(Counter(x['kind'] for x in candidates)),
        'materials':materials,'crosscheck':{k:v for k,v in comparison.items() if k not in ('rows','catalogue_checks','repository_catalogue_pairs')}}
    (OUT/'import-status.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(encode(report),flush=True)
    return report

if __name__=='__main__':run()
