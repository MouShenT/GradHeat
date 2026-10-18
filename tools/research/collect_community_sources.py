"""Collect an explicit, bounded set of public school guides and score documents."""
import argparse,hashlib,json,re,sys,time
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import urljoin,urlsplit
import requests
from bs4 import BeautifulSoup

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'python_service'));sys.path.insert(0,str(ROOT/'crawler'))
from gradheat_python import bootstrap
from gradheat_core.community_sources import score_rows
from gradheat_core.intelligence import canonical,digest
from run_daily_update import local_lock


def public_url(url):
    parsed=urlsplit(url)
    if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Explicit public URL required')
    return url


def codebrick_admission_samples(raw,unit):
    """Retain public list summaries without treating them as official cutoffs.

    The site's ``retestLineTotal`` is a list minimum, and an enrolled-only
    sample can report zero elimination. Neither is an admissions threshold or
    proof of an ordinary, complete competition pool.
    """
    payload=json.loads(raw.decode('utf-8-sig'))
    data=payload.get('data')
    if payload.get('code')!=0 or not isinstance(data,dict) or data.get('schoolName')!=unit or not data.get('programName') or not isinstance(data.get('years'),list):
        raise ValueError('Public admission summary identity or schema mismatch')
    samples=[];seen=set()
    for year in data['years']:
        if not isinstance(year,dict) or type(year.get('year')) is not int or not 2000<=year['year']<=2100 or year['year'] in seen:
            raise ValueError('Invalid or duplicate admission summary year')
        seen.add(year['year'])
        samples.append(dict(unit=unit,program_name=data['programName'],year=year['year'],
            site_school_id=data.get('schoolId'),site_admit_type=data.get('admitType'),exam_text=year.get('exam408Type'),
            mode=None,population=None,route=None,special=None,source_kind='community-database',
            linked_source_url=year.get('sourceUrl'),site_claimed_source_level=year.get('sourceLevel'),
            record_count=year.get('recordCount'),admitted_sample_count=year.get('enrolledCount'),
            unadmitted_retest_sample_count=year.get('retestCount'),single_subject_fail_count=year.get('singleFailCount'),
            retest_pool_sample_count=year.get('poolCount'),known_admitted_count=year.get('knownAdmitCount'),
            distribution_population=year.get('distPopulation'),subject_statistics=year.get('subjects',[]),
            observed_retest_list_minimum=year.get('retestLineTotal'),admitted_total_minimum=year.get('admitMinTotal'),
            official_cutoff=None,elimination_rate=None,ordinary_quota=None,
            site_reported_elimination_rate=year.get('retestEliminationRate'),
            site_inferred_retest_weight=year.get('retestWeight'),warnings=year.get('warnings',[]),
            verification_state='extracted-needs-scope-review'))
    return samples


def codebrick_stats_url(url):
    parsed=urlsplit(url)
    return parsed.hostname in ('codebrick.tech','www.codebrick.tech') and bool(re.fullmatch(r'/api/school/admit/\d+/stats',parsed.path))


def collect(rows,output,max_pages=5):
    output=Path(output).resolve()
    if not output.is_relative_to((ROOT/'.research').resolve()) or not 1<=max_pages<=8 or not 1<=len(rows)<=30:
        raise ValueError('Bounded school sources and a local private output are required')
    for row in rows:
        if not row.get('unit') or row.get('scope')!='institution':raise ValueError('Reviewed school identity and scope required')
        public_url(row['site_url']);public_url(row['score_url'])
    output.mkdir(parents=True,exist_ok=True);results=[]
    def fetch(url,suffix):
        public_url(url)
        response=requests.get(url,timeout=(8,25),stream=True,headers={'User-Agent':'GradHeat public school research'})
        response.raise_for_status();public_url(response.url);body=bytearray()
        for chunk in response.iter_content(65536):
            body.extend(chunk)
            if len(body)>10_000_000:raise ValueError('Public document exceeds budget')
        raw=bytes(body);sha=hashlib.sha256(raw).hexdigest();path=output/(sha+suffix)
        path.write_bytes(raw);return raw,dict(url=response.url,source_artifact=str(path),source_sha256=sha)
    for row in rows:
        record=dict(row,observed_at=datetime.now(timezone.utc).isoformat(),pages=[],scores=[],gaps=[])
        urls=[row['site_url']];seen=set()
        for index in range(max_pages):
            if index>=len(urls):break
            url=urls[index]
            if url in seen:continue
            seen.add(url)
            try:
                raw,item=fetch(url,'.html');soup=BeautifulSoup(raw,'html.parser')
                content=soup.find('article') or soup.find('main') or soup
                for tag in content(['script','style']):tag.decompose()
                text=content.get_text('\n',strip=True)
                links=[dict(text=a.get_text(' ',strip=True),url=urljoin(url,a['href'])) for a in soup.find_all('a',href=True)]
                for link in links:
                    target=link['url'].split('#')[0];parts=urlsplit(target)
                    if parts.hostname==urlsplit(row['site_url']).hostname and re.search('招生|报考|初试|复试|录取|分数|统计|上岸|guide|admission|score|first|second',link['text']+' '+parts.path,re.I) and target not in urls and not re.search(r'\.(?:pdf|png|jpg|js|css|zip)$',parts.path,re.I):urls.append(target)
                item.update(title=soup.title.get_text(' ',strip=True) if soup.title else '',text=text,
                            tables=[[[c.get_text(' ',strip=True) for c in tr.find_all(['th','td'])] for tr in t.find_all('tr')] for t in content.find_all('table')],
                            source_links=[l for l in links if urlsplit(l['url']).scheme in ('http','https')])
                record['pages'].append(item)
            except Exception as exc:record['gaps'].append(dict(url=url,error_type=type(exc).__name__))
            time.sleep(1)
        try:
            if codebrick_stats_url(row['score_url']):
                raw,item=fetch(row['score_url'],'.json')
                record['admission_samples']=codebrick_admission_samples(raw,row['unit']);record['admission_original']=item
            else:
                raw,item=fetch(row['score_url'],'.md');record['score_original']=item;record['scores']=score_rows(raw.decode('utf-8-sig'))
        except Exception as exc:record['gaps'].append(dict(url=row['score_url'],error_type=type(exc).__name__))
        record['state']='retained' if record['pages'] or record['scores'] or record.get('admission_samples') else 'unavailable-at-check'
        results.append(record);(output/'sources.json').write_text(canonical(results),encoding='utf-8')
        print(canonical(dict(unit=row['unit'],pages=len(record['pages']),score_rows=len(record['scores']),admission_samples=len(record.get('admission_samples',[])),gaps=len(record['gaps']))),flush=True)
    return output/'sources.json'


def import_sources(con,root,rows,units):
    originals={};validated=[]
    for row in rows:
        if row.get('unit') not in units or row.get('scope')!='institution':raise ValueError('Unknown school scope')
        public_url(row['site_url']);public_url(row['score_url'])
        for item in row.get('pages',[])+[row[key] for key in ('score_original','admission_original') if row.get(key)]:
            path=Path(item['source_artifact']).resolve()
            if not path.is_relative_to(root.resolve()) or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=item['source_sha256']:
                raise ValueError('Community original checksum mismatch')
            originals[str(path)]='community-school-guide'
        if row.get('score_original'):
            parsed=score_rows(Path(row['score_original']['source_artifact']).read_text(encoding='utf-8-sig'))
            if parsed!=row.get('scores'):raise ValueError('Score rows differ from retained original')
        if row.get('admission_original'):
            if not codebrick_stats_url(row['score_url']):raise ValueError('Unknown public admission summary endpoint')
            parsed=codebrick_admission_samples(Path(row['admission_original']['source_artifact']).read_bytes(),row['unit'])
            if parsed!=row.get('admission_samples') or row.get('scores'):
                raise ValueError('Admission samples differ from retained original or were promoted to cutoffs')
        elif row.get('admission_samples'):
            raise ValueError('Admission samples require a retained original')
        validated.append(row)
    from gradheat.material_store import archive_serial
    stored=archive_serial(con,list(originals.items()),root,progress=lambda *a,**kw:None)
    with con.cursor() as cur:
        for row in validated:
            body=canonical(row).encode();sha=digest(row)
            cur.execute('INSERT IGNORE INTO school_web_source(snapshot_sha,unit,observed_at,payload_json,canonical_bytes) VALUES(%s,%s,%s,%s,%s)',(sha,row['unit'],row['observed_at'],body.decode(),body))
            cur.execute('SELECT canonical_bytes FROM school_web_source WHERE snapshot_sha=%s',(sha,))
            if bytes(cur.fetchone()[0])!=body:raise ValueError('Community record readback mismatch')
    con.commit()
    return dict(sources=len(validated),pages=sum(len(r['pages']) for r in rows),score_rows=sum(len(r['scores']) for r in rows),admission_samples=sum(len(r.get('admission_samples',[])) for r in rows),originals=stored['files'])


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--input',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--max-pages',type=int,default=5);parser.add_argument('--wait-for-lock',action='store_true');args=parser.parse_args()
    with local_lock(wait=args.wait_for_lock):
        source=collect(json.loads(args.input.read_text(encoding='utf-8-sig')),args.output,args.max_pages)
        from refresh_school_intelligence import rebuild
        print(canonical(rebuild(community=source)),flush=True)


if __name__=='__main__':main()
