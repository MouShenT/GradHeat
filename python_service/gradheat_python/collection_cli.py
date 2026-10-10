"""Unattended finite collection: prepare/check/run/status/export; no LLM calls."""
from . import bootstrap
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
import zipfile
from urllib.parse import quote
import requests
from gradheat.material_store import archive,encode
from gradheat.vm_db import connect_vm
from .bootstrap import ROOT
from .collection_plan import prepare,prepare_input,known_units,read_plan,write_json,digest,load_state,checkpoint
from .collection_fetch import official,fetch
from .collection_search import official_search,github_search

sys.path.insert(0,str(ROOT/'tools/research'))
import collect_social_sources as social

TERMINAL={'committed','empty-sample','partial-committed','missing-entry-url','needs-human','failed','not-requested-platform-blocked','invalid-content'}


def report(folder,plan,state):
    counts=Counter(r['state'] for r in state['jobs'].values())
    remaining=[j for j in plan['jobs'] if state['jobs'].get(j['id'],{}).get('state') not in TERMINAL]
    result={'batch':str(folder),'plan_sha':plan['plan_sha'],'checked_at':datetime.now(timezone.utc).isoformat(),
        'planned_units':len(plan['units']),'planned_jobs':len(plan['jobs']),'states':dict(counts),
        'never_attempted':sum(not state['jobs'].get(j['id'],{}).get('requested',bool(state['jobs'].get(j['id']))) for j in plan['jobs']),'remaining_jobs':len(remaining),
        'database_committed_jobs':sum(counts.get(k,0) for k in ('committed','empty-sample','partial-committed')),
        'finished':not remaining,'all_information_verified':False,
        'paused_social':{k:v.get('state') for k,v in social.platform_health().items() if v.get('state')=='needs-human'},
        'paused_official':list(state.get('paused_official',{})),
        'note':'Finished refers to a finite plan, not nationwide coverage or verified admissions facts.'}
    write_json(folder/'summary.json',result)
    gaps=[j for j in plan['jobs'] if state['jobs'].get(j['id'],{}).get('state')!='committed']
    result['material_scope_complete']=not gaps
    write_json(folder/'summary.json',result)
    missing=[dict(j,state=state['jobs'].get(j['id'],{}).get('state','unattempted'),
        reason=state['jobs'].get(j['id'],{}).get('reason') or state['jobs'].get(j['id'],{}).get('error_type'),
        requested=state['jobs'].get(j['id'],{}).get('requested',bool(state['jobs'].get(j['id']))),
        documents=[{'url':d.get('url'),'state':d.get('state')} for d in state['jobs'].get(j['id'],{}).get('result',{}).get('documents',[]) if d.get('state')!='fetched']) for j in gaps]
    write_json(folder/'missing.json',missing)
    retry_tasks=[]
    for j in gaps:
        task=j.get('input_task')
        if task is None:
            task={'platform':j.get('platform',j['type']),'query':j.get('keyword',j.get('query',''))}
            if j['type']=='official':
                unit=next((u for u in plan['units'] if u['name']==j['unit']),{})
                task.update(unit=j['unit'],domains=unit.get('domains',[]),urls=unit.get('urls',[]))
            elif j['type']=='github':task['repo']=j.get('repo')
        retry_tasks.append(task)
    write_json(folder/'incomplete.json',{'schema_version':1,'tasks':retry_tasks,
        'failure_details':[{'task_id':j['id'],'state':j['state'],'reason':j['reason'],'requested':j['requested']} for j in missing],
        'previous_batch':str(folder),'note':'Only incomplete queries. Successful originals remain in previous_batch. Empty content is a gap, not proof that information does not exist.'})
    lines=['# 采集交接概况','',f"计划任务：{len(plan['jobs'])}；候选名称：{len(plan['units'])}。",
        f"尚未请求：{result['never_attempted']}；未结束：{len(remaining)}；入库任务：{result['database_committed_jobs']}。",
        '',f'状态：`{encode(dict(counts))}`','',
        '详见 missing.json、plan.json、state.json 和各任务 manifest；采集结束不等于所有院校资料收齐或已核验。',
        '遇登录、验证、空内容或异常格式记录缺口并继续后续任务；已受限平台后续任务标记未请求，不反复请求验证。',
        'incomplete.json可作为补采输入；MySQL失败用原批 --only-ingest 只续传冻结原件。',
        'public-materials.json 为可导出公共材料索引，包内不含登录会话或私有日志。']
    (folder/'SUMMARY.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    return result


def ingest(folder,job,result):
    """Store raw bytes and a public collection ledger; never publish admissions."""
    paths=[]
    for doc in result.get('documents',[]):
        for field in ('raw_path','text_path'):
            if doc.get(field):
                path=Path(doc[field]).resolve()
                if not path.is_relative_to(folder.resolve()) or not path.is_file():
                    raise ValueError('Public artifact outside its frozen task')
                if field=='raw_path' and hashlib.sha256(path.read_bytes()).hexdigest()!=doc['sha256']:
                    raise ValueError('Original hash mismatch')
                paths.append((path,'original' if field=='raw_path' else 'transcription'))
    manifest=folder/'manifests'/(digest(result)[:32]+'.json')
    write_json(manifest,result)
    paths.append((manifest,'collection-manifest'))
    run_id='auto-'+job['id'][:40]+'-'+digest(result)[:10]
    with connect_vm(folder/'private') as con:
        with con.cursor() as cur:
            cur.execute("SELECT GET_LOCK('gradheat_material_archive',30)")
            if cur.fetchone()[0]!=1: raise RuntimeError('Material writer busy; resume existing originals')
        try:
            storage=archive(con,list(dict.fromkeys(paths)),ROOT,progress=lambda *a,**kw:None)
            with con.cursor() as cur:
                cur.execute('INSERT IGNORE INTO collection_run(run_id,started_at,summary_json) VALUES(%s,%s,%s)',
                    (run_id,datetime.now(timezone.utc).isoformat(),encode({'job':job,'result':result})))
                observations=[]
                for doc in result.get('documents',[]):
                    observations.append((digest({'run':run_id,'doc':doc}),run_id,job.get('unit',job.get('repo','repository')),
                        doc.get('url','https://github.com/'+job.get('repo','unknown')),doc.get('sha256') if doc.get('raw_path') else None,doc['state'],encode(doc)))
                if observations:cur.executemany('INSERT IGNORE INTO collection_observation(observation_id,run_id,unit_name,url,sha256,state,payload_json) VALUES(%s,%s,%s,%s,%s,%s,%s)',observations)
            con.commit()
            with con.cursor() as cur:
                cur.execute('SELECT summary_json FROM collection_run WHERE run_id=%s',(run_id,))
                if json.loads(cur.fetchone()[0])!={'job':job,'result':result}:raise ValueError('Collection ledger readback differs')
            con.rollback()
        finally:
            with con.cursor() as cur:cur.execute("SELECT RELEASE_LOCK('gradheat_material_archive')")
    return {'database_state':'committed','run_id':run_id,'materials':storage}


def github(job,folder,policy):
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',job['repo']):raise ValueError('Invalid repository name')
    receipt=folder/'manifest.json'
    if receipt.exists():return json.loads(receipt.read_text(encoding='utf-8'))
    request=folder/'request.started'
    folder.mkdir(parents=True,exist_ok=True)
    if (folder/'commit.json').exists():
        commit=json.loads((folder/'commit.json').read_text(encoding='utf-8'))['commit']
    else:
        if request.exists():raise ValueError('Interrupted repository resolution requires review, not a new latest commit')
        request.write_text('Started resolving a fixed public commit.',encoding='utf-8')
        r=requests.get('https://api.github.com/repos/'+job['repo']+'/commits',params={'per_page':1},timeout=30)
        r.raise_for_status();commit=r.json()[0]['sha']
    if not re.fullmatch('[a-f0-9]{40}',commit):raise ValueError('Unexpected commit SHA')
    write_json(folder/'commit.json',{'repo':job['repo'],'commit':commit})
    raw=fetch('https://codeload.github.com/'+job['repo']+'/zip/'+commit,['codeload.github.com'],folder/'raw',
        {'timeout_seconds':30,'max_file_bytes':policy['max_archive_bytes'],'browser_fallback':False,'link_terms':[]})
    result={'repo':job['repo'],'commit':commit,'state':raw['state'],'documents':[raw],
        'scope_complete':raw['state']=='fetched','extraction_state':'archive-only-for-later-analysis'}
    write_json(receipt,result);return result


def run(folder,*,max_jobs=0,hours=None,channels=None,retry_platforms=(),only_ingest=False,stop_event=None):
    if max_jobs<0:raise ValueError('max_jobs cannot be negative')
    plan=read_plan(folder)
    state=load_state(folder)
    if state['plan_sha']!=plan['plan_sha']:raise ValueError('State belongs to another plan')
    hours=plan['policy']['execution']['default_hours'] if hours is None else hours
    if not 0<hours<=168:raise ValueError('Run budget must be 0–168 hours, exclusive of zero')
    deadline=time.monotonic()+hours*3600
    units={u['name']:u for u in plan['units']};done=0
    channels=set(channels or ['github','official','social'])
    # Existing daily and frozen all-platform collectors use this same OS lock.
    from run_daily_update import local_lock
    with local_lock(), social.collector_lock(ROOT,'full-run'):
        for platform in retry_platforms:
            if platform not in plan['policy']['social']['platforms']:raise ValueError('Unknown platform')
            social.set_platform_health(platform,'retry-authorized','explicit-human-command')
        # Repositories and official inputs first; within social tasks cover the first
        # topic across all units before deeper topics, making partial batches useful.
        topics={t['topic']:i for i,t in enumerate(plan['keywords']['query_templates'])}
        jobs=plan['jobs'] if plan.get('input_mode')=='query-json' else sorted(plan['jobs'],key=lambda j:({'github':0,'official':1,'social':2}[j['type']],topics.get(j.get('topic'),0)))
        for job in jobs:
            if stop_event is not None and stop_event.is_set():break
            if time.monotonic()>=deadline or (max_jobs and done>=max_jobs):break
            if job['type'] not in channels:continue
            old=state['jobs'].get(job['id'],{})
            explicit_retry=old.get('state') in ('needs-human','not-requested-platform-blocked') and job.get('platform') in retry_platforms
            if old.get('state') in TERMINAL and not explicit_retry:continue
            if old.get('state')=='needs-human' and (job['type']!='social' or job.get('platform') not in retry_platforms):continue
            # Bounded paths on Windows, including nested raw SHA filenames.
            child=folder/job['type']/job['id'][:16]
            attempt=old.get('attempt',1)
            prior_folders=list(old.get('prior_folders',[]))
            if explicit_retry:
                if attempt>=plan['policy']['execution']['max_attempts']:continue
                if old.get('folder'):prior_folders.append(old['folder'])
                attempt+=1
            fixed_social='auto-'+plan['plan_sha'][:12]+'-'+job['id'][:24]+f'-a{attempt}'
            existing_social=ROOT/'.research/social/runs'/fixed_social
            receipt=child/'result.json'
            if only_ingest and not receipt.exists() and not (existing_social/'manifest.json').is_file():continue
            if job['type']=='social' and not existing_social.exists():
                health=social.platform_health().get(job['platform'],{})
                if (ROOT/'.research/social/human-browser-handoff.json').exists() or health.get('state')=='needs-human':
                    state['jobs'][job['id']]={'state':'not-requested-platform-blocked','requested':False,
                        'reason':health.get('reason') or 'browser-owned-by-human','attempt':attempt,'prior_folders':prior_folders}
                    checkpoint(folder,state,job['id']);done+=1
                    print(encode({'processed_this_run':done,'platform':job['platform'],'state':'not-requested-platform-blocked','continue':True}),flush=True)
                    continue
                last=state.get('last_queries',{}).get(job['platform'],0)
                wait=max(0,plan['policy']['social']['query_interval_seconds']-(time.time()-last))
                if time.monotonic()+wait>=deadline:break
                if wait:
                    if stop_event is not None:
                        if stop_event.wait(wait):break
                    else:time.sleep(wait)
                state['last_queries'][job['platform']]=time.time()
            state['jobs'][job['id']]=dict(old,state='running',attempt=attempt,prior_folders=prior_folders,
                folder=str(existing_social if job['type']=='social' else child),requested=True,started_at=datetime.now(timezone.utc).isoformat())
            checkpoint(folder,state,job['id']);done+=1
            try:
                child.mkdir(parents=True,exist_ok=True)
                if job['type']=='social':
                    if existing_social.exists():
                        result=social.resume(existing_social)
                    else:
                        result=social.run(as_of=plan['as_of'],units_override=[job['unit']],platforms_override=[job['platform']],
                            keyword_override=job['keyword'],sort_override=job['sort'],detail_limit=job.get('detail_limit',plan['policy']['social']['detail_limit']),
                            image_limit=plan['policy']['social']['image_limit'],skip_discovery=True,bulk=True,vm=True,run_id_override=fixed_social,
                            generic_search=job.get('generic_search',False))
                    write_json(receipt,result)
                    blockers=result.get('blockers',[])
                    state_value='needs-human' if any(b.get('state')=='needs-human' for b in blockers) or result.get('state')=='needs-human' else 'empty-sample' if not result.get('snapshots') else 'committed' if result.get('sampling_complete') and not result.get('media_missing') else 'partial-committed'
                    result['reason']=next((b.get('reason') or b.get('error_type') for b in blockers if b.get('reason') or b.get('error_type')),None) or ('no-public-content' if not result.get('snapshots') else None)
                    if state_value=='needs-human':social.set_platform_health(job['platform'],'needs-human',result['reason'])
                    if result.get('database_state')!='committed':state_value='needs-ingest'
                    public_folder=existing_social
                else:
                    if receipt.exists():result=json.loads(receipt.read_text(encoding='utf-8'))
                    elif job['type']=='official':
                        result=official_search(job,child,plan['policy']['official'],plan['keywords'],deadline,social.discover) if job.get('target') else official(units[job['unit']],child,plan['policy']['official'],plan['keywords'],deadline)
                    else:result=github_search(job,child,plan['policy']['github'],deadline) if job.get('query') or plan.get('input_mode') else github(job,child,plan['policy']['github'])
                    write_json(receipt,result)
                    if result.get('deadline_reached'):
                        result.pop('deadline_reached',None)
                        # Archive partial originals, then continue the same progress
                        # on the next invocation instead of caching a terminal result.
                        storage=ingest(child,job,result)
                        receipt.unlink(missing_ok=True);(child/'manifest.json').unlink(missing_ok=True)
                        state_value='budget-paused'
                    else:
                        storage=ingest(child,job,result)
                        state_value='needs-human' if result['state']=='needs-human' else 'empty-sample' if result['state']=='empty-sample' else 'missing-entry-url' if result['state']=='missing-entry-url' else 'committed' if result.get('scope_complete') else 'partial-committed'
                    result.update(storage);write_json(child/'storage.json',storage)
                    if state_value=='needs-human':state['paused_official'][job['unit']]=True
                    public_folder=child
                compact={k:v for k,v in result.items() if k in ('database_state','run_id','scope_complete','state','media_missing','sampling_complete','pages','page_budget_reached','documents','reason')}
                # Only failed document statuses belong in the compact job ledger.
                if 'documents' in compact:compact['documents']=[{'url':d.get('url'),'state':d.get('state'),'error_type':d.get('error_type')} for d in compact['documents'] if d.get('state')!='fetched']
                state['jobs'][job['id']]={'state':state_value,'folder':str(public_folder),'result':compact,'requested':True,
                    'reason':result.get('reason') or next((d.get('error_type') or d.get('state') for d in compact.get('documents',[])),None),'attempt':attempt,'prior_folders':prior_folders}
            except Exception as error:
                # An existing receipt/raw checkpoint wins over a new fetch on resume.
                state['jobs'][job['id']]={'state':'needs-ingest' if receipt.exists() else 'failed',
                    'folder':str(existing_social if job['type']=='social' else child),'requested':True,'error_type':type(error).__name__,'attempt':attempt,'prior_folders':prior_folders}
            checkpoint(folder,state,job['id'])
            if done%16==0:
                write_json(folder/'state.json',state);report(folder,plan,state)
            print(encode({'processed_this_run':done,'job_type':job['type'],'state':state['jobs'][job['id']]['state']}),flush=True)
    write_json(folder/'state.json',state)
    return report(folder,plan,state)


def export(folder):
    """Build a verified public-only handoff; never glob private session artifacts."""
    plan=read_plan(folder);state=load_state(folder)
    report(folder,plan,state)
    files={};records=[]
    def add(path,context):
        path=Path(path).resolve()
        allowed=(folder.resolve(),(ROOT/'.research/social/runs').resolve())
        if not any(path.is_relative_to(parent) for parent in allowed) or not path.is_file():raise ValueError('Missing or foreign public artifact')
        if path.name.endswith('.log') or path.suffix.lower() in ('.har','.request') or path.name in ('request.started',):raise ValueError('Private execution artifact cannot be exported')
        with path.open('rb') as stream:sha=hashlib.file_digest(stream,'sha256').hexdigest()
        name='materials/'+sha+(path.suffix.lower() if len(path.suffix)<12 else '.bin')
        files.setdefault(name,path);records.append(dict(context,sha256=sha,bytes=path.stat().st_size,path_in_package=name))
    for job in plan['jobs']:
        record=state['jobs'].get(job['id'],{})
        if not record.get('folder'):continue
        context={'task_id':job['id'],'type':job['type'],'unit':job.get('unit'),'platform':job.get('platform'),
            'query':job.get('keyword'),'database_state':record.get('result',{}).get('database_state'),'collection_state':record['state']}
        for child in [Path(p) for p in record.get('prior_folders',[])]+[Path(record['folder'])]:
            manifest=child/'manifest.json'
            candidates=[manifest] if job['type']=='social' else list((child/'manifests').glob('*.json'))
            if not candidates and manifest.is_file():candidates=[manifest]
            if not candidates:continue
            # A job can have multiple immutable manifests from budget checkpoints.
            # Every referenced original is deduplicated by SHA in the package.
            for candidate in candidates:add(candidate,context)
            documents=[]
            for candidate in candidates:
                data=json.loads(candidate.read_text(encoding='utf-8'))
                documents.extend(data.get('documents',[]))
            if job['type']=='social':
                # Only sanitized artifacts registered by the original collector manifest.
                for artifact in data.get('artifacts',[]):add(artifact,context)
            else:
                for doc in documents:
                    for key in ('raw_path','text_path'):
                        if doc.get(key):
                            if key=='raw_path':
                                with Path(doc[key]).open('rb') as s:actual=hashlib.file_digest(s,'sha256').hexdigest()
                                if actual!=doc['sha256']:raise ValueError('Original changed before export')
                            add(doc[key],dict(context,url=doc.get('url'),observed_at=doc.get('observed_at'),title=doc.get('title'),kind=key))
    write_json(folder/'public-materials.json',records)
    target=folder/'handoff.zip';temp=folder/'handoff.zip.tmp'
    with zipfile.ZipFile(temp,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=1) as z:
        for name in ('SUMMARY.md','summary.json','missing.json','incomplete.json','plan.json','queries.json','public-materials.json'):
            z.write(folder/name,name)
        # The state file contains only our sanitized receipts and error types.
        z.write(folder/'state.json','state.json')
        for name,path in files.items():z.write(path,name)
    with zipfile.ZipFile(temp) as z:
        for name in files:
            h=hashlib.sha256()
            with z.open(name) as s:
                for chunk in iter(lambda:s.read(1024*1024),b''):h.update(chunk)
            if h.hexdigest()!=name.split('/')[1].split('.')[0]:raise ValueError('Handoff ZIP hash readback failed')
    temp.replace(target)
    with target.open('rb') as s:sha=hashlib.file_digest(s,'sha256').hexdigest()
    return {'handoff':str(target),'unique_materials':len(files),'records':len(records),'sha256':sha}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    subs=parser.add_subparsers(dest='command',required=True)
    p=subs.add_parser('prepare');p.add_argument('--units',type=Path);p.add_argument('--from-existing',action='store_true');p.add_argument('--unit-limit',type=int)
    p.add_argument('--as-of',default=datetime.now().date().isoformat());p.add_argument('--keywords',type=Path,default=ROOT/'config/collection-keywords.json');p.add_argument('--policy',type=Path,default=ROOT/'config/collection-policy.json')
    for name in ('run','status','export','check'):
        p=subs.add_parser(name);p.add_argument('--batch',type=Path)
        p.add_argument('--input',type=Path)
        if name=='run':
            p.add_argument('--max-jobs',type=int,default=0);p.add_argument('--hours',type=float);p.add_argument('--channel',action='append',choices=['official','social','github'])
            p.add_argument('--retry-platform',action='append',choices=['xhs','zhihu','dy','bili'],default=[]);p.add_argument('--only-ingest',action='store_true')
    args=parser.parse_args()
    if args.command=='prepare':
        if bool(args.units)==bool(args.from_existing):parser.error('Choose --units JSON or --from-existing')
        raw=json.loads(args.units.read_text(encoding='utf-8')) if args.units else known_units(ROOT)
        if isinstance(raw,dict):raw=raw['units']
        folder,plan=prepare(ROOT,raw,json.loads(args.keywords.read_text(encoding='utf-8')),json.loads(args.policy.read_text(encoding='utf-8')),as_of=args.as_of,unit_limit=args.unit_limit)
        print(encode({'batch':str(folder),'jobs':len(plan['jobs']),'units':len(plan['units']),'plan_sha':plan['plan_sha']}));return
    if args.input and args.batch:parser.error('Use --input for a new batch or --batch to resume')
    if args.command=='run' and not (args.input or args.batch):parser.error('run requires --input JSON or --batch checkpoint')
    if args.input:
        folder,plan=prepare_input(ROOT,json.loads(args.input.read_text(encoding='utf-8-sig')))
        print(encode({'batch':str(folder),'jobs':len(plan['jobs']),'input_sha':plan['input_sha']}),flush=True)
    else:folder=args.batch or Path(json.loads((ROOT/'.research/autonomous-collection/latest.json').read_text(encoding='utf-8'))['batch'])
    folder=folder.resolve()
    if not folder.is_relative_to((ROOT/'.research/autonomous-collection').resolve()):raise ValueError('Only project-owned collection batches')
    if args.command=='run':
        result=run(folder,max_jobs=args.max_jobs,hours=args.hours,channels=args.channel,retry_platforms=args.retry_platform,only_ingest=args.only_ingest)
        with social.collector_lock(ROOT,'full-run'):result['handoff']=export(folder)
    elif args.command=='export':
        with social.collector_lock(ROOT,'full-run'):result=export(folder)
    elif args.command=='status':result=report(folder,read_plan(folder),load_state(folder))
    else:
        plan=read_plan(folder)
        from mediacrawler_worker import cdp_health
        result={'plan_sha':plan['plan_sha'],'jobs':len(plan['jobs']),'chrome_debugging':cdp_health(json.loads((ROOT/'contracts/social-collection.json').read_text())['cdp_port']),
            'platform_health':social.platform_health(),'mysql':'unchecked','publish_admissions':False}
        try:
            with connect_vm(folder/'private') as con:
                with con.cursor() as cur:cur.execute('SELECT 1');cur.fetchone()
            result['mysql']='reachable'
        except Exception as e:result['mysql']=type(e).__name__
    print(encode(result),flush=True)
    if args.command=='run':
        raise SystemExit(0 if result['material_scope_complete'] else 2 if result['finished'] else 3)


if __name__=='__main__':main()
