"""A frozen input plan, independent of model calls and the running Java app."""
from . import bootstrap
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit
from gradheat.material_store import encode
from copy import deepcopy

PLATFORMS = {'official':'official', '官网':'official', 'github':'github',
    'xhs':'xhs', '小红书':'xhs', 'zhihu':'zhihu', '知乎':'zhihu',
    'dy':'dy', '抖音':'dy', 'bili':'bili', 'b站':'bili', 'bilibili':'bili'}


def prepare_input(root, source, *, as_of=None):
    """One public query JSON; no school registry or model required."""
    if source.get('schema_version',1)!=1 or not isinstance(source.get('tasks'),list):
        raise ValueError('Input needs schema_version=1 and a tasks array')
    if set(source)-{'schema_version','tasks','settings','failure_details','previous_batch','note'}:
        raise ValueError('Unknown top-level keys; credentials do not belong in query JSON')
    if not 1<=len(source['tasks'])<=100000:raise ValueError('Input needs 1–100000 tasks')
    policy=json.loads((root/'config/collection-policy.json').read_text(encoding='utf-8'))
    keywords=json.loads((root/'config/collection-keywords.json').read_text(encoding='utf-8'))
    policy=deepcopy(policy)
    for section,values in source.get('settings',{}).items():
        if section not in policy or not isinstance(values,dict):raise ValueError('Unknown settings section')
        for key,value in values.items():
            if key not in policy[section]:raise ValueError('Unknown setting')
            policy[section][key]=value
    validate_policy(policy)
    jobs=[];seen=set();units=[]
    for task in source['tasks']:
        if not isinstance(task,dict):raise ValueError('Each task must be an object')
        if set(task)-{'platform','query','unit','urls','domains','repo','limit','sort'}:
            raise ValueError('Unknown task keys; cookies/tokens are not accepted')
        platform=PLATFORMS.get(str(task.get('platform','')).lower())
        if not platform:raise ValueError('Unsupported platform')
        if 'query' in task and not isinstance(task['query'],str):raise ValueError('query must be text')
        query=str(task.get('query','')).strip()
        if len(query)>500:raise ValueError('Query exceeds 500 characters')
        if not query and not (platform=='official' and task.get('urls')) and not (platform=='github' and task.get('repo')):
            raise ValueError('Task needs query, or explicit official urls / GitHub repo')
        row={'type':platform if platform in ('official','github') else 'social', 'query':query,
            'input_task':{k:deepcopy(v) for k,v in task.items() if k in ('platform','query','unit','urls','domains','repo','limit','sort')}}
        if platform=='official':
            domains=task.get('domains',[]);urls=task.get('urls',[])
            if not isinstance(domains,list) or not isinstance(urls,list):raise ValueError('domains and urls must be arrays')
            unit=compact_units([{'name':str(task.get('unit') or query or '公开官网资料'), 'domains':domains,'urls':urls}])[0]
            # Explicit URLs define their own allowed hosts. Pure queries restrict
            # discovery to education/research admissions domains unless specified.
            unit['domains']=sorted(set(unit['domains']+[urlsplit(u).hostname.lower() for u in unit['urls']]))
            row.update(unit=unit['name'],target=unit,search_limit=int(task.get('limit',8)))
            units.append(unit)
        elif platform=='github':
            row.update(repo=task.get('repo'),search_limit=int(task.get('limit',3)))
        else:
            row.update(platform=platform,unit=str(task.get('unit') or query),keyword=query,
                sort=task.get('sort',keywords['platform_sorts'][platform]),generic_search=True,
                detail_limit=int(task.get('limit',policy['social']['detail_limit'])))
            if row['sort'] not in ('general','popular','latest') or (platform=='dy' and row['sort']!='general'):
                raise ValueError('Unsupported sort (Douyin currently supports general only)')
        if not 1<=row.get('search_limit',row.get('detail_limit',1))<=20:raise ValueError('Task limit must be 1–20')
        row['id']=digest({k:v for k,v in row.items() if k!='input_task'})
        if row['id'] not in seen:jobs.append(row);seen.add(row['id'])
    as_of=as_of or date.today().isoformat();date.fromisoformat(as_of)
    plan={'schema_version':1,'as_of':as_of,'created_at':datetime.now(timezone.utc).isoformat(),
        'units':units,'keywords':keywords,'policy':policy,'jobs':jobs,'input_sha':digest(source),
        'input_mode':'query-json','scope':'Explicit finite queries; raw materials for later review'}
    plan['plan_sha']=digest(plan)
    folder=root/'.research/autonomous-collection'/('batch-'+as_of.replace('-','')+'-'+plan['plan_sha'][:12])
    folder.mkdir(parents=True,exist_ok=False)
    write_json(folder/'input.json',source);write_json(folder/'plan.json',plan)
    write_json(folder/'queries.json',[j for j in jobs if j.get('query') or j.get('keyword')])
    write_json(folder/'state.json',{'plan_sha':plan['plan_sha'],'jobs':{},'paused_official':{},'last_queries':{}})
    write_json(root/'.research/autonomous-collection/latest.json',{'batch':str(folder),'plan_sha':plan['plan_sha']})
    return folder,plan


def validate_policy(policy):
    if policy['social']['query_interval_seconds']<30 or not 1<=policy['social']['detail_limit']<=20:
        raise ValueError('Preserve 30-second social interval and bounded details')
    if not 1<=policy['official']['max_pages_per_unit']<=500 or not 0<=policy['official']['max_depth']<=6:
        raise ValueError('Official page/depth budget outside range')
    if not 0<policy['execution']['default_hours']<=168:raise ValueError('Invalid execution hours')
    if not 0<=policy['official']['host_interval_seconds']<=60 or not 1<=policy['official']['timeout_seconds']<=120:
        raise ValueError('Invalid official request budget')
    if not 1024<=policy['official']['max_file_bytes']<=200000000 or not 1024<=policy['github']['max_archive_bytes']<=500000000:
        raise ValueError('Invalid byte budget')
    if policy['storage']!={'mode':'mysql-vm','publish_admissions':False}:
        raise ValueError('This collector archives raw materials only')


def digest(value):
    return hashlib.sha256(encode(value).encode('utf-8')).hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.tmp')
    temp.write_text(encode(value), encoding='utf-8');temp.replace(path)


def known_units(root):
    full = root/'.research/full-collection-20261008/expanded-corpus.json'
    manual = root/'.research/manual-downloads/全量采集资料.json'
    path = full if full.is_file() else manual
    if not path.is_file():
        raise ValueError('Provide a units JSON or prepare from an existing candidate registry')
    return json.loads(path.read_text(encoding='utf-8'))['units']


def compact_units(raw):
    units = {}
    for row in raw:
        name = str(row.get('name') or row.get('unit') or '').strip()
        if not name or len(name) > 160:
            raise ValueError('Candidate needs a bounded institution name')
        target = units.setdefault(name, {'name': name, 'domains': [], 'urls': []})
        domains = list(row.get('official_domains') or row.get('domains') or [])
        if row.get('domain'): domains.append(row['domain'])
        urls = list(row.get('urls') or [])
        if row.get('portal'): urls.append(row['portal'])
        for key in ('documents','supplement_documents'):
            urls.extend(d['url'] for d in row.get(key, []) if isinstance(d,dict) and d.get('url'))
        for domain in domains:
            domain = domain.lower().strip().lstrip('.')
            if domain and '/' not in domain and ':' not in domain:
                target['domains'].append(domain)
        for url in urls:
            parsed = urlsplit(url)
            if parsed.scheme in ('http','https') and parsed.hostname and not parsed.username and not parsed.password:
                target['urls'].append(url)
        target['domains'] = sorted(set(target['domains']))
        target['urls'] = list(dict.fromkeys(target['urls']))
    return list(units.values())


def prepare(root, units, keywords, policy, *, as_of, unit_limit=None):
    date.fromisoformat(as_of)
    if unit_limit is not None and unit_limit<1:raise ValueError('Unit limit must be positive')
    if policy['social']['query_interval_seconds'] < 30 or not 1 <= policy['social']['detail_limit'] <= 20:
        raise ValueError('Social budget must preserve 30-second query spacing and bounded details')
    if not 1 <= policy['official']['max_pages_per_unit'] <= 500 or not 0 <= policy['official']['max_depth'] <= 6:
        raise ValueError('Official page/depth budget outside supported range')
    units = compact_units(units)
    if unit_limit: units = units[:unit_limit]
    if not units: raise ValueError('No candidates to collect')
    jobs = []
    for unit in units:
        row = {'type':'official','unit':unit['name']};row['id'] = digest(row);jobs.append(row)
        for platform in policy['social']['platforms']:
            if platform not in keywords['platform_sorts']: raise ValueError('Unsupported platform')
            for template in keywords['query_templates']:
                query = template['template'].format(unit=unit['name'],entry_year=keywords['entry_year'],
                    last_year=keywords['history_years'][0],previous_year=keywords['history_years'][1])
                if len(query)>500: raise ValueError('Query exceeds budget')
                row={'type':'social','unit':unit['name'],'platform':platform,'keyword':query,
                    'topic':template['topic'],'sort':keywords['platform_sorts'][platform]}
                row['id']=digest(row);jobs.append(row)
    if policy.get('github',{}).get('enabled'):
        for repo in keywords.get('repositories',[]):
            row={'type':'github','repo':repo};row['id']=digest(row);jobs.append(row)
    plan={'schema_version':1,'as_of':as_of,'created_at':datetime.now(timezone.utc).isoformat(),
        'units':units,'keywords':keywords,'policy':policy,'jobs':jobs,
        'scope':'Known candidates; 2027 11408 eligibility is not established by a collection plan'}
    plan['plan_sha']=digest(plan)
    folder=root/'.research/autonomous-collection'/('batch-'+as_of.replace('-','')+'-'+plan['plan_sha'][:12])
    folder.mkdir(parents=True,exist_ok=False)
    write_json(folder/'plan.json',plan)
    write_json(folder/'queries.json',[j for j in jobs if j['type']=='social'])
    write_json(folder/'state.json',{'plan_sha':plan['plan_sha'],'jobs':{},'paused_official':{},'last_queries':{}})
    write_json(root/'.research/autonomous-collection/latest.json',{'batch':str(folder),'plan_sha':plan['plan_sha']})
    return folder,plan


def read_plan(folder):
    plan=json.loads((folder/'plan.json').read_text(encoding='utf-8'))
    if digest({k:v for k,v in plan.items() if k!='plan_sha'})!=plan['plan_sha']:
        raise ValueError('Frozen collection plan changed')
    if len({j['id'] for j in plan['jobs']})!=len(plan['jobs']):
        raise ValueError('Repeated collection task')
    if len({j['id'][:16] for j in plan['jobs']})!=len(plan['jobs']):
        raise ValueError('Task path prefix collision')
    return plan


def load_state(folder):
    state=json.loads((folder/'state.json').read_text(encoding='utf-8'))
    journal=folder/'events.jsonl'
    if journal.exists():
        with journal.open(encoding='utf-8') as stream:
            for line in stream:
                event=json.loads(line)
                if event['sha256']!=digest({k:v for k,v in event.items() if k!='sha256'}) or event['plan_sha']!=state['plan_sha']:
                    raise ValueError('Collection journal integrity failure')
                state['jobs'][event['job_id']]=event['row']
                state['last_queries']=event['last_queries'];state['paused_official']=event['paused_official']
    return state


def checkpoint(folder,state,job_id):
    # Write/fsync the small event before any network request, instead of rewriting
    # a multi-megabyte global state for every query in a long collection plan.
    import os
    event={'plan_sha':state['plan_sha'],'job_id':job_id,'row':state['jobs'][job_id],
        'last_queries':state.get('last_queries',{}),'paused_official':state.get('paused_official',{})}
    event['sha256']=digest(event)
    with (folder/'events.jsonl').open('a',encoding='utf-8') as stream:
        stream.write(encode(event)+'\n');stream.flush();os.fsync(stream.fileno())
