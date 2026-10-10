"""Resume a finite school-by-platform research sample; no site-wide crawl."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import copy
import hashlib
import json
import os
from pathlib import Path
import threading
import time

from collect_social_sources import (ROOT, collector_lock, run, platform_health,
    sampling_summary, committed_result, resume)
from social_evidence import digest, encode, now

PLATFORMS = ('xhs', 'zhihu', 'dy', 'bili')
QUERIES = ('{unit} 2027 计算机 考研', '{unit} 2025 2026 计算机 复试 录取')


def build_plan(as_of):
    manual = json.loads((ROOT / '.research/manual-downloads/全量采集资料.json').read_text(encoding='utf-8'))
    pointer = json.loads((ROOT / '.research/admissions-data/latest.json').read_text(encoding='utf-8'))
    public = json.loads(Path(pointer['path']).read_text(encoding='utf-8'))
    priority = json.loads((ROOT / '.research/unit-dossiers-20261001/dossiers.json').read_text(encoding='utf-8'))
    names = list(dict.fromkeys([u['unit'] for u in priority] + [u['name'] for u in public['units']] + [u['name'] for u in manual['units']]))
    corpus = {u['name']: copy.deepcopy(u) for u in manual['units']}
    repo_pointer = json.loads((ROOT / '.research/github-sources/latest.json').read_text(encoding='utf-8'))
    repo = next(r for r in repo_pointer['repositories'] if r['repo'].endswith('kaoyan-recommendation-platform'))
    indexes = json.loads((Path(repo['path']) / 'data/admission-units.json').read_text(encoding='utf-8'))
    schools = {u['name']:u for u in indexes['units']}
    for name in names:
        if name not in corpus:
            corpus[name] = dict(name=name, key=hashlib.sha256(name.encode()).hexdigest()[:16],
                domain='chsi.com.cn', portal=schools.get(name, {}).get('sourceUrl'),
                official_domains=['chsi.com.cn'], group='其他招生单位', documents=[], supplement_documents=[],
                basis='Previously known public admissions candidate; 2027 11408 eligibility requires checking')
    jobs = []
    for unit in names:
        for template in QUERIES:
            for platform in PLATFORMS:
                row = dict(unit=unit, platform=platform, keyword=template.format(unit=unit), as_of=as_of)
                row['id'] = digest(row)
                jobs.append(row)
    return dict(as_of=as_of, units=names, priority_units=len(priority), public_version=pointer['version_id'],
        limit=2, pages_per_query=1, jobs=jobs, corpus=dict(units=[corpus[n] for n in names]),
        scope='All currently known school candidates; eligibility and unavailable facts remain separate')


def summary(plan, state):
    statuses = Counter(r['state'] for r in state.values())
    complete = sum(r['state'] in ('committed', 'empty-sample')
        and r.get('sampling_complete') is not False
        and not (r.get('failed_jobs') or r.get('media_missing')) for r in state.values())
    finished = len(state)==len(plan['jobs']) and all(r['state'] in ('committed','empty-sample') for r in state.values())
    return dict(as_of=plan['as_of'], planned_units=len(plan['units']), planned_jobs=len(plan['jobs']),
        states=dict(statuses), dispatched=len(state), finished=len(state)-statuses['running'], available_jobs_complete=complete,
        media_missing=sum(r.get('media_missing',0) for r in state.values()),
        failed_jobs=sum(r.get('failed_jobs') or 0 for r in state.values()),
        fully_finished=finished,
        available_materials_complete=finished and complete==len(plan['jobs']),
        all_information_verified=False, checked_at=now())


def checkpoint_result(job, result, manifest):
    """A commit certifies storage, not completion of the frozen sample."""
    sampling = sampling_summary(manifest)
    if result['database_state'] != 'committed':
        status = 'needs-retry'
    elif any(blocker['state'] == 'needs-human' for blocker in sampling['blockers']):
        status = 'needs-human'
    elif not sampling['sampling_complete']:
        status = 'partial'
    else:
        status = 'committed' if sampling['snapshots'] else 'empty-sample'
    values = dict(result, **sampling)
    return dict(job, state=status, **{k:v for k,v in values.items() if k not in ('state', 'as_of')})


def execute(folder, max_jobs=None):
    plan = json.loads((folder / 'plan.json').read_text(encoding='utf-8'))
    path = folder / 'state.json'
    state = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    mutex = threading.Lock()
    dispatched = 0
    def save():
        temporary = path.with_suffix('.tmp')
        temporary.write_text(encode(state), encoding='utf-8');temporary.replace(path)
        report = summary(plan, state)
        (folder / 'summary.json').write_text(encode(report), encoding='utf-8')
        return report
    def worker(platform):
        nonlocal dispatched
        for job in (j for j in plan['jobs'] if j['platform']==platform):
            with mutex:
                old = state.get(job['id'], {})
                if old.get('state') not in (None, 'running', 'needs-retry','interrupted-platform-paused'):continue
            # A recorded batch must be resumed, even if its file is missing.
            # Missing/tampered evidence is an error, never permission to refetch.
            frozen = bool(old.get('folder'))
            if not frozen:
                while (ROOT/'.research/social/human-browser-handoff.json').exists():
                    time.sleep(1)
                if platform_health().get(platform,{}).get('state')=='needs-human':
                    # Leave new jobs unattempted. Existing frozen batches can
                    # still recover storage without using the paused browser.
                    break
            with mutex:
                if max_jobs is not None and dispatched>=max_jobs:break
                dispatched += 1
                state[job['id']] = dict(job, state='running', started_at=now())
                if frozen:state[job['id']]['folder'] = old['folder']
                save()
            result = None
            try:
                if frozen:
                    result = committed_result(old['folder']) or resume(old['folder'])
                else:
                    result = run(as_of=plan['as_of'], units_override=[job['unit']],
                        platforms_override=[platform], keyword_override=job['keyword'], detail_limit=plan['limit'],
                        skip_discovery=True, image_limit=24, bulk=True)
                manifest = json.loads((Path(result['folder'])/'manifest.json').read_text(encoding='utf-8'))
                with mutex:
                    state[job['id']] = checkpoint_result(job, result, manifest)
                    report = save()
                    if len(state)%16==0:print(encode(report), flush=True)
            except Exception as exc:
                with mutex:
                    state[job['id']] = dict(job, state='needs-retry', error_type=type(exc).__name__)
                    # Keep the frozen batch location even when validation fails;
                    # losing it would silently turn the next resume into refetch.
                    batch = (result or {}).get('folder') or old.get('folder')
                    if batch:state[job['id']]['folder'] = batch
                    save()
            time.sleep(30)
    marker = ROOT / '.research/social/full-run-active.json'
    with collector_lock(ROOT, 'full-run'):
        # This OS lock proves the prior supervisor no longer owns the batch.
        # A lost checkpoint cannot establish whether its browser request ran.
        health=platform_health()
        for key,row in state.items():
            if row.get('state')=='running' and not row.get('folder') and health.get(row.get('platform'),{}).get('state')=='needs-human':
                state[key]=dict(row,state='interrupted-platform-paused',request_history='unknown',interruption_checked_at=now())
        save()
        marker.write_text(encode(dict(folder=str(folder), pid=os.getpid(), started_at=now())), encoding='utf-8')
        try:
            with ThreadPoolExecutor(max_workers=4) as pool:
                for future in [pool.submit(worker,p) for p in PLATFORMS]:future.result()
        finally:
            marker.unlink(missing_ok=True)
            print(encode(save()), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--as-of', required=True)
    parser.add_argument('--plan-only', action='store_true')
    parser.add_argument('--max-jobs', type=int)
    args = parser.parse_args()
    folder = ROOT / ('.research/full-collection-' + args.as_of.replace('-',''))
    folder.mkdir(parents=True, exist_ok=True)
    if not (folder/'plan.json').exists():
        plan = build_plan(args.as_of)
        (folder/'plan.json').write_text(encode(plan), encoding='utf-8')
        (folder/'expanded-corpus.json').write_text(encode(plan['corpus']), encoding='utf-8')
    else:plan=json.loads((folder/'plan.json').read_text(encoding='utf-8'))
    print(encode(dict(folder=str(folder), units=len(plan['units']), jobs=len(plan['jobs']), scope=plan['scope'])), flush=True)
    if not args.plan_only:execute(folder,args.max_jobs)


if __name__=='__main__':main()
