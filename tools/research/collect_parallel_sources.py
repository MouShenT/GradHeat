"""Parallel public retrieval with one batch owner and one database writer."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import sys
import threading
import time
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'python_service'));sys.path.insert(0,str(ROOT/'crawler'))
from gradheat_python import bootstrap
from gradheat_core.intelligence import canonical,digest
from run_daily_update import local_lock
import collect_social_sources as social
from expand_school_basics import retrieve
from collect_community_sources import public_url


def validate(source):
    if set(source)-{'schema_version','as_of','social','websites'} or source.get('schema_version')!=1:
        raise ValueError('Explicit parallel source schema required')
    date.fromisoformat(source['as_of'])
    if not 1<=len(source.get('social',[]))+len(source.get('websites',[]))<=60:
        raise ValueError('Provide 1–60 explicit tasks')
    for row in source.get('social',[]):
        if set(row)-{'platform','query','unit','limit','pages','sort'} or row.get('platform') not in ('bili','xhs','zhihu','dy'):
            raise ValueError('Unsupported platform task')
        if not isinstance(row.get('query'),str) or not 1<=len(row['query'])<=500 or not 1<=row.get('limit',20)<=20:
            raise ValueError('Bounded query and detail limit required')
        if not 1<=row.get('pages',1)<=3 or row.get('sort','general') not in ('latest','general','popular'):
            raise ValueError('Unsupported query pagination or sort')
        if row['platform']=='dy' and (row.get('pages',1)!=1 or row.get('sort','general')!='general'):
            raise ValueError('Douyin supports one general page')
    for row in source.get('websites',[]):
        if set(row)!={'unit','url'} or not isinstance(row['unit'],str) or not 1<=len(row['unit'])<=160:
            raise ValueError('Explicit website school identity required')
        public_url(row['url'])


def collect(source,folder,social_workers=3,website_workers=4):
    """Fetch independently; no worker thread writes MySQL."""
    validate(source)
    if not 1<=social_workers<=4 or not 1<=website_workers<=8:raise ValueError('Worker budget outside range')
    folder=Path(folder).resolve()
    if not folder.is_relative_to((ROOT/'.research').resolve()):raise ValueError('Private output required')
    folder.mkdir(parents=True,exist_ok=True)
    input_path=folder/'input.json'
    if input_path.exists() and json.loads(input_path.read_text(encoding='utf-8'))!=source:
        raise ValueError('Frozen batch input differs; use a new output directory')
    input_path.write_text(canonical(source),encoding='utf-8')
    mutex=threading.Lock();host_locks={};state={};outcomes=[]
    state_path=folder/'retrieval.json'
    if state_path.exists():state=json.loads(state_path.read_text(encoding='utf-8'))
    def mark(key,value):
        with mutex:
            state[key]=value
            temporary=state_path.with_suffix('.tmp');temporary.write_text(canonical(state),encoding='utf-8');temporary.replace(state_path)
    def social_lane(platform,rows):
        results=[];last_query=0
        for row in rows:
            key=digest(row);run_id='auto-'+digest(source)[:12]+'-'+key[:24]+'-a1'
            existing=social.ROOT/'.research/social/runs'/run_id
            try:
                if existing.exists():
                    _,manifest=social.load_frozen_manifest(existing)
                    result=dict(folder=str(existing),run_id=run_id,**social.sampling_summary(manifest))
                elif social.platform_paused(platform,social.platform_health().get(platform,{})):
                    mark(key,dict(state='needs-human',platform=platform,requested=False));continue
                else:
                    wait=max(0,30-(time.monotonic()-last_query))
                    if wait:time.sleep(wait)
                    last_query=time.monotonic()
                    mark(key,dict(state='running',platform=platform,requested=True))
                    result=social.run(as_of=source['as_of'],units_override=[row.get('unit') or row['query']],
                        platforms_override=[platform],keyword_override=row['query'],detail_limit=row.get('limit',20),
                        pages=row.get('pages',1),sort_override=row.get('sort','general'),generic_search=True,
                        skip_discovery=True,image_limit=0,bulk=True,vm=False,run_id_override=run_id)
                mark(key,dict(state='retained',platform=platform,folder=result['folder'],snapshots=result.get('snapshots',0)))
                results.append(dict(type='social',task=row,result=result))
            except Exception as error:
                mark(key,dict(state='needs-review',platform=platform,error_type=type(error).__name__))
        return results
    def website(row):
        key=digest(row);child=folder/'websites'/key[:16]
        host=urlsplit(row['url']).hostname
        with mutex:lock=host_locks.setdefault(host,threading.Lock())
        with lock:
            receipt=child/'manifest.json'
            if receipt.exists():
                rows=json.loads(receipt.read_text(encoding='utf-8'))
                for item in rows:
                    if item.get('source_artifact') and hashlib.sha256(Path(item['source_artifact']).read_bytes()).hexdigest()!=item['source_sha256']:
                        raise ValueError('Retained website changed; do not refetch')
            else:
                mark(key,dict(state='running',host=host))
                rows=retrieve([row],child)
                time.sleep(1)  # The retriever already waits one second; keep two per host.
            mark(key,dict(state=rows[0]['state'],host=host))
            return [dict(type='website',task=row,result=rows[0])]
    with ThreadPoolExecutor(max_workers=social_workers) as platforms,ThreadPoolExecutor(max_workers=website_workers) as websites:
        futures=[platforms.submit(social_lane,p,[r for r in source.get('social',[]) if r['platform']==p]) for p in dict.fromkeys(r['platform'] for r in source.get('social',[]))]
        futures += [websites.submit(website,row) for row in source.get('websites',[])]
        for future in as_completed(futures):
            outcomes.extend(future.result())
    (folder/'collected.json').write_text(canonical(outcomes),encoding='utf-8')
    return outcomes


def store(outcomes,folder):
    from gradheat_python.collection_cli import ingest
    receipts=[]
    for item in outcomes:
        if item['type']=='social':
            result=social.committed_result(item['result']['folder']) or social.resume(item['result']['folder'])
            receipts.append(dict(type='social',platform=item['task']['platform'],snapshots=result.get('snapshots',0),database_state=result['database_state']))
        else:
            row=item['result']
            if row['state']!='retained':continue
            child=Path(row['source_artifact']).parent
            result=dict(state='fetched',scope_complete=True,documents=[dict(unit=item['task']['unit'],url=row['source_url'],raw_path=row['source_artifact'],sha256=row['source_sha256'],text_path=row['extracted_path'],state='fetched')])
            receipts.append(dict(type='website',**ingest(child,dict(type='official',unit=item['task']['unit'],id=digest(item['task'])),result)))
        (Path(folder)/'storage.json').write_text(canonical(receipts),encoding='utf-8')
    return receipts


def main():
    p=argparse.ArgumentParser();p.add_argument('--input',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--social-workers',type=int,default=3);p.add_argument('--website-workers',type=int,default=4);p.add_argument('--wait-for-lock',action='store_true')
    args=p.parse_args();source=json.loads(args.input.read_text(encoding='utf-8-sig'));validate(source)
    with local_lock(wait=args.wait_for_lock),social.collector_lock(ROOT,'full-run'):
        marker=ROOT/'.research/social/full-run-active.json'
        marker.write_text(canonical(dict(pid=os.getpid(),folder=str(args.output),source='parallel-collection')),encoding='utf-8')
        try:
            outcomes=collect(source,args.output,args.social_workers,args.website_workers)
            receipts=store(outcomes,args.output)
            from refresh_school_intelligence import rebuild
            states=json.loads((args.output/'retrieval.json').read_text(encoding='utf-8'))
            report=dict(receipts=receipts,retrieval_states=states,dossiers=rebuild(),social_workers=args.social_workers,website_workers=args.website_workers)
            (args.output/'report.json').write_text(canonical(report),encoding='utf-8');print(canonical(report),flush=True)
        finally:
            marker.unlink(missing_ok=True)


if __name__=='__main__':main()
