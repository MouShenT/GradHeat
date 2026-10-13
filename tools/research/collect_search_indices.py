"""Observed Baidu user-search indices via the optional, pinned Qdata SDK.

Cookies are read from a private browser export; never passed on a command line.
Only indexed graduate-admissions keywords are used, never result counts or bare
institution names. A refusal stops collection and preserves the remaining queue.
"""
import argparse
import ast
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys
import time
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'python_service'))
from gradheat_python import bootstrap
from gradheat_core.intelligence import ALIASES, UCAS_COLLEGES, canonical, number, unique_units, unit_key

SDK_COMMIT = 'fe251d22a9938ee9f0bd667ad153cd9f1da20fef'
REFERENCE_SCALE = 1000  # Fixed heuristic scale for Baidu overall daily index.


def cookies_from_export(path):
    envelope = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    rows = envelope.get('data', envelope) if isinstance(envelope, dict) else envelope
    rows = rows.get('cookies', []) if isinstance(rows, dict) else rows
    cookies = {c['name']:c['value'] for c in rows
        if c.get('domain','').lstrip('.') in ('baidu.com','index.baidu.com') and c.get('path','/') == '/'}
    if not cookies.get('BDUSS'): raise ValueError('Baidu login is required')
    return '; '.join(f'{k}={v}' for k,v in cookies.items())


def build_queries(units, parent_units=None):
    result = []
    for unit in unique_units(units):
        term = ('中国科学院大学'+unit if unit in UCAS_COLLEGES else '中国科学院'+unit
            if (parent_units or {}).get(unit)=='中国科学院大学' and not unit.startswith('中国科学院') else unit)
        terms = [term+'研究生院', term+'考研', term+'计算机考研']
        terms.extend(a+'考研' for a in ALIASES.get(unit, []) if not a.isascii())
        for keyword in dict.fromkeys(terms): result.append(dict(unit=unit,keyword=keyword))
    return result


def parse_indices(encrypted, key, decrypt, observed_at):
    """Validate provider dates/series before averaging; missing is never padded 0."""
    rows = []
    for item in encrypted['data']['userIndexes']:
        word = item['word']
        if isinstance(word,str):
            try: word = json.loads(word)
            except json.JSONDecodeError: word = ast.literal_eval(word)
        names = [w['name'] for w in word]
        if len(names) != 1: raise ValueError('Combined terms are not individual keyword indices')
        daily = {}; windows = set()
        for kind in ('all','pc','wise'):
            segment = item[kind]
            start, end = date.fromisoformat(segment['startDate']), date.fromisoformat(segment['endDate'])
            if start > end: raise ValueError('Invalid provider date range')
            values = decrypt(key,segment['data']) if segment.get('data') else []
            expected=(end-start).days+1
            if not values:
                windows.add((start,end))
                daily[kind]=[dict(date=(start+timedelta(days=o)).isoformat(),value=None) for o in range(expected)]
                continue
            if len(values) != expected: raise ValueError('Incomplete provider time series')
            parsed = []
            for offset,value in enumerate(values):
                if str(value).strip() == '':
                    parsed.append(dict(date=(start+timedelta(days=offset)).isoformat(),value=None));continue
                n = float(value)
                if number(n) is None or n < 0: raise ValueError('Invalid index value')
                parsed.append(dict(date=(start+timedelta(days=offset)).isoformat(),value=n))
            windows.add((start,end));daily[kind]=parsed
        if len(windows) != 1: raise ValueError('Device windows differ')
        start,end=windows.pop()
        known=[p['value'] for p in daily['all'] if p['value'] is not None]
        coverage=len(known)/len(daily['all'])
        rows.append(dict(keyword=names[0],window_start=start.isoformat(),window_end=end.isoformat(),
            value=sum(known)/len(known) if known and coverage>=.7 else None,
            coverage=coverage,daily=daily,observed_at=observed_at))
    return rows


def collect(queries, cookie_path, sdk_path, output, start, end, max_queries=60, delay=15):
    if start > end or (end-start).days > 365 or end >= date.today():
        raise ValueError('Use a historical window ending before today, at most 366 days')
    if not 1 <= max_queries <= 2000 or delay < 10: raise ValueError('Invalid bounded request budget')
    if any(not q.get('unit') or not q.get('keyword') or not any(t in q['keyword'] for t in ('考研','研究生','硕士')) for q in queries):
        raise ValueError('Use explicit school and graduate-admissions keywords')
    if any(not any(unit_key(token) in unit_key(q['keyword']) for token in [q['unit']]+ALIASES.get(q['unit'],[])) for q in queries):
        raise ValueError('Broad search demand cannot be assigned to an unrelated school')
    if any(q['unit'] in UCAS_COLLEGES and not any(t in q['keyword'] for t in ('中国科学院大学','国科大')) for q in queries):
        raise ValueError('A generic college needs its parent university')
    if sdk_path: sys.path.insert(0,str(Path(sdk_path).resolve()))
    from qdata.baidu_index import common
    # Never use SDK format_data: it pads absent values with zero.
    cookie = cookies_from_export(cookie_path)
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    report=dict(provider='baidu-qdata',sdk_commit=SDK_COMMIT,started_at=datetime.now(timezone.utc).isoformat(),
        window_start=start.isoformat(),window_end=end.isoformat(),queried_keywords=[],not_indexed=[],insufficient=[],signals=[],state='running')
    by_keyword={}
    for q in queries: by_keyword.setdefault(q['keyword'],[]).append(q['unit'])
    selected=list(by_keyword)[:max_queries]
    def save():
        (output/'report.json').write_text(canonical(report),encoding='utf-8')
        (output/'signals.json').write_text(canonical(report['signals']),encoding='utf-8')
        completed=set(report['queried_keywords'])
        (output/'pending.json').write_text(canonical([q for q in queries if q['keyword'] not in completed]),encoding='utf-8')
    save()
    try:
        for offset in range(0,len(selected),15):
            if offset: time.sleep(delay)
            check=common.check_keywords_exists(selected[offset:offset+15],cookie)
            missing=check['not_exists_keywords'];report['not_indexed'].extend(missing);report['queried_keywords'].extend(missing)
            found=check['exists_keywords']
            for at in range(0,len(found),5):
                time.sleep(delay)
                chunk=found[at:at+5]
                raw=common.get_encrypt_json(start_date=datetime.combine(start,datetime.min.time()),
                    end_date=datetime.combine(end,datetime.min.time()),keywords=[[k] for k in chunk],type='search',area=0,cookies=cookie)
                key=common.get_key(raw['data']['uniqid'],cookie)
                observed=datetime.now(timezone.utc).isoformat()
                raw_body=canonical(dict(provider='baidu',query_keywords=chunk,observed_at=observed,response=raw))
                (output/('response-'+hashlib.sha256(raw_body.encode()).hexdigest()+'.json')).write_text(raw_body,encoding='utf-8')
                series=parse_indices(raw,key,common.decrypt_func,observed)
                if set(r['keyword'] for r in series) != set(chunk): raise ValueError('Provider keyword set differs')
                blob=canonical(dict(provider='baidu',query_keywords=chunk,observed_at=observed,response=raw,series=series))
                sha=hashlib.sha256(blob.encode()).hexdigest();(output/(sha+'.json')).write_text(blob,encoding='utf-8')
                for row in series:
                    if row['window_start'] != start.isoformat() or row['window_end'] != end.isoformat(): raise ValueError('Provider window differs')
                    if row['value'] is None:
                        report['insufficient'].append(row['keyword']);continue
                    for unit in by_keyword[row['keyword']]:
                        report['signals'].append(dict(unit=unit,kind='search-index',provider='baidu-search',
                            keyword=row['keyword'],value=row['value'],reference_scale=REFERENCE_SCALE,
                            source_url='https://index.baidu.com/v2/main/index.html#/trend/'+quote(row['keyword'])+'?words='+quote(row['keyword']),
                            window_start=row['window_start'],window_end=row['window_end'],observed_at=observed,
                            region='全国',device='PC+移动',scope='graduate-admissions-keyword',coverage=row['coverage'],daily=row['daily']['all'],raw_sha256=sha,
                            source_artifact=str((output/(sha+'.json')).resolve())))
                report['queried_keywords'].extend(chunk);save()
            save()
        report['state']='collected' if report['signals'] else 'no-indexed-keywords'
    except Exception as error:
        report.update(state='needs-human-or-provider-change',error_type=type(error).__name__,error_code=getattr(error,'code',None))
        allowed=('Combined terms are not individual keyword indices','Invalid provider date range','Incomplete provider time series','Missing index value','Invalid index value','Device windows differ','Provider keyword set differs','Provider window differs')
        if type(error) is ValueError and str(error) in allowed: report['validation_error']=str(error)
        # Messages from third-party libraries may contain request credentials.
    finally:
        report['finished_at']=datetime.now(timezone.utc).isoformat();save()
    return dict(state=report['state'],queried=len(report['queried_keywords']),
        not_indexed=len(report['not_indexed']),signals=len(report['signals']),output=str(output.resolve()))


def main():
    p=argparse.ArgumentParser();p.add_argument('--queries',type=Path,required=True)
    p.add_argument('--cookies-file',type=Path,default=ROOT/'.research/school-intelligence/private/baidu-cookies.json')
    p.add_argument('--sdk-path',type=Path,default=ROOT/'.research/opensource/qdata')
    p.add_argument('--output',type=Path,default=ROOT/'.research/school-intelligence/search-index')
    p.add_argument('--start',type=date.fromisoformat,default=date.today()-timedelta(days=30))
    p.add_argument('--end',type=date.fromisoformat,default=date.today()-timedelta(days=1))
    p.add_argument('--max-queries',type=int,default=60);p.add_argument('--delay',type=float,default=15)
    p.add_argument('--wait-for-lock',action='store_true');p.add_argument('--import-dossiers',action='store_true')
    args=p.parse_args()
    def run():
        result=collect(json.loads(args.queries.read_text(encoding='utf-8-sig')),args.cookies_file,args.sdk_path,
            args.output,args.start,args.end,args.max_queries,args.delay)
        if args.import_dossiers and result['signals']:
            from refresh_school_intelligence import rebuild
            result['dossiers']=rebuild(search=args.output/'signals.json')
        print(canonical(result))
    if args.wait_for_lock:
        sys.path.insert(0,str(ROOT/'crawler'))
        from run_daily_update import local_lock
        with local_lock(wait=True): run()
    else: run()


if __name__=='__main__': main()
