"""Download commit-pinned public repositories as data; never execute their code."""
import hashlib,json,os,re,subprocess,zipfile
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime,timezone
from pathlib import Path
import requests

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'.research/github-sources'
REPOS=['Laz8Noy/kaoyan408-share','zhwen2703-hash/kaoyan-recommendation-platform','ccdgr/cs-assistant','csseky/cskaoyan','wenliang90/408exam']

def fetch_from_public_git(repo,api_failure=None):
    """Read anonymous public HEAD when the REST discovery route is unavailable."""
    if repo not in REPOS:raise ValueError('Repository outside the configured public list')
    git_env=dict(os.environ,GIT_TERMINAL_PROMPT='0',GCM_INTERACTIVE='never')
    result=subprocess.run(['git','-c','credential.helper=','ls-remote','--symref',
        'https://github.com/'+repo+'.git','HEAD'],capture_output=True,text=True,
        timeout=60,check=True,env=git_env)
    commit=re.findall(r'^([a-f0-9]{40})\s+HEAD$',result.stdout,re.M)
    branch=re.findall(r'^ref:\s+refs/heads/(\S+)\s+HEAD$',result.stdout,re.M)
    if len(commit)!=1 or len(branch)!=1:raise ValueError('Public Git HEAD response is ambiguous')
    evidence=dict(repo=repo,commit=commit[0],branch=branch[0],transport='anonymous-git-ls-remote',
        observed_at=datetime.now(timezone.utc).isoformat(),api_failure=api_failure,
        metadata_state='REST metadata not refreshed; license/parent remain unknown')
    return fetch(repo,git_discovery=evidence)


def fetch(repo,git_discovery=None):
    slug=repo.replace('/','--');raw=OUT/'raw';raw.mkdir(parents=True,exist_ok=True)
    api='https://api.github.com/repos/'+repo
    if git_discovery:
        meta={};commit=git_discovery['commit']
        evidence_path=raw/(slug+'-'+commit+'-git-ref.json')
        if not evidence_path.exists():evidence_path.write_text(json.dumps(git_discovery,ensure_ascii=False,indent=2),encoding='utf-8')
    else:
        try:
            metadata=requests.get(api,timeout=40);metadata.raise_for_status();meta=metadata.json()
            commit_response=requests.get(api+'/commits/'+meta['default_branch'],timeout=40);commit_response.raise_for_status();commit=commit_response.json()['sha']
        except requests.RequestException as error:
            response=getattr(error,'response',None)
            failure=dict(error_type=type(error).__name__,http_status=response.status_code if response is not None else None)
            return fetch_from_public_git(repo,api_failure=failure)
    if not re.fullmatch('[a-f0-9]{40}',commit):raise ValueError('Invalid GitHub commit')
    package=OUT/'snapshots'/slug/commit
    archive=raw/(slug+'-'+commit+'.zip')
    if not git_discovery:
        for label,response in [('metadata',metadata),('commit',commit_response)]:
            path=raw/(slug+'-'+commit+'-'+label+'.json')
            if not path.exists():path.write_bytes(response.content)
    if not archive.exists():
        partial=archive.with_suffix('.part');url=f'https://codeload.github.com/{repo}/zip/{commit}'
        with requests.get(url,stream=True,timeout=(15,90)) as response:
            response.raise_for_status();size=0
            with partial.open('wb') as stream:
                for chunk in response.iter_content(1024*1024):
                    size+=len(chunk)
                    if size>3*1024**3:raise ValueError('Repository archive exceeds 3GiB bound')
                    stream.write(chunk)
        partial.replace(archive)
    package.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(archive) as zipped:
        entries=zipped.infolist();total=sum(x.file_size for x in entries)
        if total>4*1024**3:raise ValueError('Expanded repository exceeds 4GiB bound')
        for entry in entries:
            if entry.is_dir():continue
            relative=Path(*Path(entry.filename).parts[1:]);path=(package/relative).resolve()
            if not path.is_relative_to(package.resolve()) or (entry.external_attr>>16)&0o170000==0o120000:raise ValueError('Unsafe archive entry')
            if not path.exists():
                path.parent.mkdir(parents=True,exist_ok=True)
                with zipped.open(entry) as src,path.open('wb') as dst:
                    while chunk:=src.read(1024*1024):dst.write(chunk)
    with archive.open('rb') as stream:sha=hashlib.file_digest(stream,'sha256').hexdigest()
    report=dict(repo=repo,commit=commit,archive=str(archive),sha256=sha,archive_bytes=archive.stat().st_size,expanded_bytes=total,path=str(package),
        retrieved_at=datetime.now(timezone.utc).isoformat(),license=(meta.get('license') or {}).get('spdx_id'),parent=(meta.get('parent') or {}).get('full_name'),
        status='downloaded-data-only',source_family='csseky/cskaoyan' if repo=='wenliang90/408exam' else repo)
    if git_discovery:report.update(discovery_transport=git_discovery['transport'],metadata_state=git_discovery['metadata_state'])
    (package/'gradheat-download-manifest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False),flush=True)
    return report

def run():
    OUT.mkdir(parents=True,exist_ok=True);reports=[];errors=[]
    prior=json.loads((OUT/'latest.json').read_text(encoding='utf-8')) if (OUT/'latest.json').exists() else {'repositories':[]}
    with ThreadPoolExecutor(3) as pool:
        futures={pool.submit(fetch,repo):repo for repo in REPOS}
        for future in as_completed(futures):
            try:reports.append(future.result())
            except Exception as error:
                errors.append(dict(repo=futures[future],error_type=type(error).__name__,status='download-failed'))
                print(json.dumps(errors[-1]),flush=True)
    by_repo={r['repo']:r for r in prior['repositories']}
    by_repo.update({r['repo']:r for r in reports})
    result={'repositories':list(by_repo.values()),'errors':errors}
    temp=OUT/'latest.json.tmp';temp.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(OUT/'latest.json')
    if errors:raise RuntimeError('One or more GitHub archives failed; see latest.json and resume')
    return result

if __name__=='__main__':run()
