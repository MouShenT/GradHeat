"""Literal public query discovery with immutable receipts and fixed GitHub SHAs."""
import hashlib
import json
import os
from pathlib import Path
import re
import time
from urllib.parse import urlsplit
import requests
from .collection_plan import write_json
from .collection_fetch import official,fetch,allowed_url


def document(path,url):
    return {'url':url,'state':'fetched','raw_path':str(path),
        'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'byte_size':path.stat().st_size}


def official_search(job,folder,policy,keywords,deadline,discover):
    target=dict(job['target']);target['urls']=list(target['urls']);target['domains']=list(target['domains'])
    discovery=None;docs=[]
    if job.get('query'):
        receipt=folder/'search.json';marker=folder/'search.started';folder.mkdir(parents=True,exist_ok=True)
        if receipt.exists():discovery=json.loads(receipt.read_text(encoding='utf-8'))
        elif marker.exists():discovery={'status':'interrupted-search','results':[]}
        else:
            marker.write_text('One public search started.',encoding='utf-8')
            # Single-domain queries are constrained at the engine as well as after discovery.
            query=job['query']+(f" site:{target['domains'][0]}" if len(target['domains'])==1 else '')
            try:discovery=discover(query)
            except Exception as e:discovery={'status':'search-unavailable','error_type':type(e).__name__,'results':[]}
            if not isinstance(discovery,dict) or not isinstance(discovery.get('results'),list):
                discovery={'status':'invalid-search-format','results':[]}
            write_json(receipt,discovery)
        if receipt.exists():docs.append(document(receipt,'https://searxng.org/'))
        selected=[];approved=list(job['target']['domains'])
        for item in discovery.get('results',[]):
            if not isinstance(item,dict) or not isinstance(item.get('url'),str):continue
            url=item['url'];host=(urlsplit(url).hostname or '').lower()
            if approved:
                if not any(host==d or host.endswith('.'+d) for d in approved):continue
            elif not any(host==d or host.endswith('.'+d) for d in ('edu.cn','ac.cn','chsi.com.cn')):
                continue
            try:allowed_url(url,approved or [host],resolve=False)
            except ValueError:continue
            selected.append(url)
            if not job['target']['domains']:target['domains'].append(host)
            if len(selected)>=job['search_limit']:break
        target['urls']=list(dict.fromkeys(selected+target['urls']))
    result=official(target,folder,policy,keywords,deadline)
    # The official executor freezes only acquisition; this wraps query discovery too.
    result['documents']=docs+result['documents'];result['query']=job.get('query')
    if discovery is not None:
        status=discovery.get('status');result['discovery_status']=status
        result['search_results']=len(discovery.get('results',[]))
        if status not in ('ok','success','healthy','partial','degraded','empty'):
            result.update(scope_complete=False,state='partial',reason='official-search-'+str(status))
        elif status=='degraded':result.update(scope_complete=False,state='partial',reason='official-search-engine-degraded')
        elif not target['urls']:
            result.update(scope_complete=False,state='empty-sample',reason='no-official-results')
    return result


def github_api(url,params=None):
    headers={'Accept':'application/vnd.github+json','User-Agent':'GradHeat-Collection/1.0'}
    token=os.getenv('GRADHEAT_GITHUB_TOKEN')
    if token:headers['Authorization']='Bearer '+token
    with requests.get(url,params=params,headers=headers,timeout=(8,30)) as response:
        if response.status_code in (401,403,429):
            raise GitHubUnavailable('github-auth-or-rate-limit')
        response.raise_for_status()
        if len(response.content)>10000000:raise ValueError('GitHub metadata over budget')
        return response.json()


class GitHubUnavailable(ValueError):pass


def repository(repo,folder,policy):
    if not isinstance(repo,str) or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repo):raise ValueError('Invalid repository name')
    receipt=folder/'manifest.json';folder.mkdir(parents=True,exist_ok=True)
    if receipt.exists():return json.loads(receipt.read_text(encoding='utf-8'))
    marker=folder/'request.started';commit_file=folder/'commit.json'
    if commit_file.exists():commit=json.loads(commit_file.read_text(encoding='utf-8'))['commit']
    elif marker.exists():return {'repo':repo,'state':'interrupted-request','scope_complete':False,'documents':[]}
    else:
        marker.write_text('Resolving a fixed public commit.',encoding='utf-8')
        response=github_api('https://api.github.com/repos/'+repo+'/commits',{'per_page':1})
        if not isinstance(response,list) or not response or not isinstance(response[0],dict):raise ValueError('Invalid commit response')
        commit=response[0].get('sha')
        if not isinstance(commit,str) or not re.fullmatch('[a-f0-9]{40}',commit):raise ValueError('Invalid commit SHA')
        write_json(commit_file,{'repo':repo,'commit':commit})
    raw=fetch('https://codeload.github.com/'+repo+'/zip/'+commit,['codeload.github.com'],folder/'raw',
        {'timeout_seconds':30,'max_file_bytes':policy['max_archive_bytes'],'browser_fallback':False,'link_terms':[]})
    result={'repo':repo,'commit':commit,'state':raw['state'],'scope_complete':raw['state']=='fetched',
        'documents':[document(commit_file,'https://api.github.com/repos/'+repo+'/commits'),raw],
        'extraction_state':'archive-only-for-later-analysis'}
    write_json(receipt,result);return result


def github_search(job,folder,policy,deadline):
    folder.mkdir(parents=True,exist_ok=True);docs=[];discovery=None
    repos=[job['repo']] if job.get('repo') else []
    if not repos:
        receipt=folder/'search.json';marker=folder/'search.started'
        if receipt.exists():discovery=json.loads(receipt.read_text(encoding='utf-8'))
        elif marker.exists():return {'state':'interrupted-search','scope_complete':False,'documents':[]}
        else:
            marker.write_text('One GitHub repository search started.',encoding='utf-8')
            data=github_api('https://api.github.com/search/repositories',{'q':job['query'],'per_page':job['search_limit'],'page':1})
            if not isinstance(data,dict) or not isinstance(data.get('items'),list):raise ValueError('Invalid GitHub search format')
            # Store only public repository search metadata; no request headers/token.
            discovery={k:data.get(k) for k in ('total_count','incomplete_results')}
            discovery['items']=[{k:i.get(k) for k in ('full_name','html_url','description','fork','default_branch')} for i in data['items'] if isinstance(i,dict)]
            write_json(receipt,discovery)
        docs.append(document(receipt,'https://api.github.com/search/repositories'))
        repos=[i['full_name'] for i in discovery['items'][:job['search_limit']] if i.get('full_name')]
    snapshots=[]
    for repo in repos:
        if time.monotonic()>=deadline:break
        child=folder/'repos'/hashlib.sha256(repo.encode()).hexdigest()[:16]
        try:row=repository(repo,child,policy)
        except Exception as e:row={'repo':repo,'state':'failed','error_type':type(e).__name__,'scope_complete':False,'documents':[]}
        snapshots.append(row);docs.extend(row['documents'])
    complete=bool(repos) and len(snapshots)==len(repos) and all(r['scope_complete'] for r in snapshots) and not (discovery or {}).get('incomplete_results')
    return {'state':'collected' if complete else 'empty-sample' if not repos else 'partial','scope_complete':complete,
        'query':job.get('query'),'repositories':snapshots,'documents':docs,'reason':None if complete else 'empty-or-incomplete-repository-snapshots',
        'deadline_reached':len(snapshots)<len(repos) and time.monotonic()>=deadline}
