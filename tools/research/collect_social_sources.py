"""Bounded social collection, resumable public evidence and optional MySQL ingestion."""
import argparse
from contextlib import contextmanager
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'crawler'))
from social_evidence import candidate_segments, clean_url, document, encode, now, public_response, snapshot


def platform_health():
    path = ROOT / '.research/social/platform-health.json'
    health = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    for item in (ROOT / '.research/social/platform-health').glob('*.json'):
        health[item.stem] = json.loads(item.read_text(encoding='utf-8'))
    return health


def set_platform_health(platform, state, reason=None, restriction_scope=None):
    path = ROOT / '.research/social/platform-health' / (platform + '.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    previous = platform_health().get(platform, {})
    restrictions = dict(previous.get('restrictions') or {})
    if previous.get('restriction_scope') and previous.get('reason') == 'platform-access-refused':
        restrictions.setdefault(previous['restriction_scope'], dict(reason=previous['reason'], checked_at=previous.get('checked_at')))
    record = dict(state=state, reason=reason, checked_at=now())
    if state == 'retry-authorized':
        restrictions = {}
    elif restriction_scope and reason == 'platform-access-refused':
        restrictions[restriction_scope] = dict(reason=reason, checked_at=record['checked_at'])
    if restrictions:
        record['restrictions'] = restrictions
        if state == 'accessible' and platform == 'zhihu' and 'platform-detail' in restrictions:
            record.update(state='partial-access', reason='platform-access-refused', restriction_scope='platform-detail')
    if restriction_scope:record['restriction_scope']=restriction_scope
    temp = path.with_name(path.stem + '-' + uuid.uuid4().hex + '.tmp')
    temp.write_text(encode(record), encoding='utf-8')
    temp.replace(path)


def platform_paused(platform, health):
    # A refused detail endpoint does not prohibit a normal public search page.
    return health.get('state') == 'needs-human' and not (
        platform == 'zhihu' and health.get('reason') == 'platform-access-refused'
        and health.get('restriction_scope') == 'platform-detail')


@contextmanager
def collector_lock(root, namespace='global'):
    # Shared name for GradHeat jobs. In-memory configuration also avoids sibling file races.
    folder = root / '.research/social'
    folder.mkdir(parents=True, exist_ok=True)
    if namespace not in ('global', 'xhs', 'zhihu', 'dy', 'bili', 'full-run'):
        raise ValueError('Unsupported collector lock namespace')
    with (folder / (namespace + '-collector.lock')).open('a+b') as stream:
        stream.seek(0)
        stream.write(b'0')
        stream.flush()
        stream.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def collector_version(path):
    command = subprocess.run(['git', '-C', str(path), 'rev-parse', 'HEAD'], capture_output=True, text=True, timeout=8)
    keys = ('config/base_config.py', 'config/xhs_config.py', 'store/xhs/__init__.py', 'store/xhs/_store_impl.py')
    return dict(commit=command.stdout.strip() if command.returncode == 0 else None,
        shared_file_hashes={p: hashlib.sha256((path / p).read_bytes()).hexdigest() for p in keys})


def full_collection_active():
    marker = ROOT / '.research/social/full-run-active.json'
    if not marker.exists():
        return False
    try:
        with collector_lock(ROOT, 'full-run'):
            # An OS lock is released after a crash; the old marker alone is not liveness.
            marker.unlink(missing_ok=True)
        return False
    except OSError:
        return True


def units_for_day(units, as_of, size):
    # Stable rotation; daily failures never silently skip that day's selected units.
    offset = (date.fromisoformat(as_of).toordinal() * size) % len(units)
    return [units[(offset + i) % len(units)] for i in range(min(size, len(units)))]


def safe_social_url(url):
    p = urllib.parse.urlsplit(url)
    host = (p.hostname or '').lower()
    return p.scheme == 'https' and (
        (host == 'zhuanlan.zhihu.com' and p.path.startswith('/p/')) or
        (host == 'www.zhihu.com' and p.path.startswith('/question/')) or
        (host == 'www.xiaohongshu.com' and p.path.startswith('/explore/')))


def discover(query):
    from gradheat.vm_connection import ssh_connection
    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    ssh, target = ssh_connection()
    response = subprocess.run(ssh + [target, 'python3',
        '/opt/gradheat/search/gradheat_search.py', '--stdin'],
        input=encode({'operation': 'search', 'query': query}), encoding='utf-8',
        capture_output=True, timeout=48, creationflags=flags)
    try:
        record = json.loads(response.stdout)
    except ValueError:
        return dict(status='down', error_type='search-service-unavailable', results=[])
    return public_response({k: record.get(k) for k in ('query', 'status', 'observed_at', 'result_count', 'failed_engines', 'results')})


def public_page(url):
    """Normal public GET only; one attempt, no sign guessing or challenge retries."""
    try:
        request = urllib.request.Request(url, headers={'User-Agent': 'GradHeatResearch/1.0', 'Accept': 'text/html'})
        with urllib.request.urlopen(request, timeout=15) as response:
            if not safe_social_url(response.url):
                return dict(state='needs-human', reason='non-content-redirect')
            raw = response.read(4_000_001)
            if len(raw) > 4_000_000:
                return dict(state='unavailable-at-check', reason='page-size-limit')
            html = raw.decode('utf-8', errors='replace')
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, 'html.parser')
        article = soup.select_one('.RichText.ztext, .NoteContent, .note-content')
        if article is None or len(article.get_text(strip=True)) < 100:
            return dict(state='needs-human', reason='no-readable-public-body')
        title = soup.title.get_text() if soup.title else ''
        platform = 'xhs' if 'xiaohongshu.com' in url else 'zhihu'
        return dict(state='collected', document=dict(platform=platform,
            content_id=urllib.parse.urlsplit(url).path.rstrip('/').split('/')[-1], content_type='article',
            title=title, text=article.get_text('\n', strip=True), url=clean_url(url),
            published_at=None, author_hash=None, metrics={}, content_level='full-text',
            image_urls=[clean_url(i.get('src') or '') for i in article.select('img')],
            provider='public-http', observed_at=now()))
    except Exception as exc:
        return dict(state='unavailable-at-check', reason='public-page-fetch-failed', error_type=type(exc).__name__)


def add_document(manifest, folder, doc, units):
    doc = public_response(doc)
    if not doc.get('text') and not doc.get('title') and not doc.get('image_urls'):
        return
    doc.setdefault('observed_at', now())
    body = encode(doc).encode()
    sha = hashlib.sha256(body).hexdigest()
    path = folder / 'raw' / (sha + '.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_bytes(body)
    item = snapshot(doc, manifest['run_id'], path)
    if item['id'] in {d['id'] for d in manifest['snapshots']}:
        return
    manifest['snapshots'].append(item)
    manifest['artifacts'].append(str(path))
    manifest['candidates'].extend(candidate_segments(item, units))


def collect_images(manifest, folder, limit):
    """Keep public table/notice images as bytes; image extraction remains a candidate."""
    seen = set()
    manifest['media'] = []
    for doc in manifest['snapshots']:
        for url in doc.get('image_urls') or []:
            host = (urllib.parse.urlsplit(url).hostname or '').lower()
            if not url or url in seen:
                continue
            seen.add(url)
            item = dict(snapshot_id=doc['id'], url=url, state='budget-deferred')
            if len([r for r in manifest['media'] if r['state'] != 'budget-deferred']) < limit and (host.endswith('.zhimg.com') or host.endswith('.xhscdn.com')):
                try:
                    request = urllib.request.Request(url, headers={'User-Agent': 'GradHeatResearch/1.0'})
                    with urllib.request.urlopen(request, timeout=15) as response:
                        final_host = (urllib.parse.urlsplit(response.url).hostname or '').lower()
                        if not (final_host.endswith('.zhimg.com') or final_host.endswith('.xhscdn.com')):
                            raise ValueError('Image redirect changed domain')
                        raw = response.read(8_000_001)
                    if len(raw) > 8_000_000:
                        raise ValueError('Image exceeds sample budget')
                    suffix = '.jpg' if raw.startswith(b'\xff\xd8\xff') else '.png' if raw.startswith(b'\x89PNG\r\n\x1a\n') else '.webp' if raw[:4] == b'RIFF' and raw[8:12] == b'WEBP' else None
                    if suffix is None:
                        raise ValueError('Response is not a supported image')
                    sha = hashlib.sha256(raw).hexdigest()
                    path = folder / 'raw' / (sha + suffix)
                    path.write_bytes(raw)
                    item.update(state='fetched', source_artifact=str(path), source_sha256=sha, extraction_state='not-extracted')
                    manifest['artifacts'].append(str(path))
                except Exception as exc:
                    item.update(state='unavailable-at-check', error_type=type(exc).__name__)
            manifest['media'].append(item)


def ingest(manifest, folder):
    from gradheat.vm_db import connect_vm
    from gradheat.social_store import store
    with connect_vm(folder) as con:
        result = store(con, ROOT, manifest)
    (folder / 'database.json').write_text(encode(result), encoding='utf-8')
    return result


def persist_result(result):
    pointer = ROOT / '.research/social/latest.json'
    temp = pointer.with_name(pointer.stem + '-' + uuid.uuid4().hex + '.tmp')
    temp.write_text(encode(result), encoding='utf-8')
    temp.replace(pointer)


def sampling_summary(manifest):
    """Rebuild collection completeness from frozen evidence, independently of storage."""
    successful = {'collected', 'empty-sample', 'healthy', 'empty'}
    failed = [job for job in manifest.get('jobs', []) if job.get('state') not in successful]
    media_missing = sum(item.get('state') != 'fetched' for item in manifest.get('media', []))
    snapshots = len(manifest.get('snapshots', []))
    state = 'partial' if failed or media_missing else 'collected' if snapshots else 'empty-sample'
    return dict(state=state, sampling_state=state, sampling_complete=not (failed or media_missing),
        snapshots=snapshots, candidates=len(manifest.get('candidates', [])),
        failed_jobs=len(failed), media_missing=media_missing,
        blockers=[dict(state=job.get('state'), reason=job.get('reason'),
            error_type=job.get('error_type'), platform=job.get('platform')) for job in failed])


def finish_ingestion(manifest, folder, result, vm=True):
    if vm:
        try:
            result['database'] = ingest(manifest, folder)
            result['database_state'] = 'committed'
        except Exception as exc:
            result['database_state'] = 'needs-retry'
            result['database_error_type'] = type(exc).__name__
    else:
        result['database_state'] = 'local-only'
    # Keep the original manifest frozen: the storage state is separate.
    status = folder / 'storage-status.json'
    temporary = status.with_name(status.stem + '-' + uuid.uuid4().hex + '.tmp')
    temporary.write_text(encode(result), encoding='utf-8')
    temporary.replace(status)
    persist_result(result)
    return result


def load_frozen_manifest(path):
    manifest_path = Path(path).resolve()
    if manifest_path.is_dir():
        manifest_path /= 'manifest.json'
    if not manifest_path.is_relative_to((ROOT / '.research/social/runs').resolve()) or manifest_path.name != 'manifest.json':
        raise ValueError('Resume requires a frozen local social collection manifest')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if manifest['run_id'] != manifest_path.parent.name:
        raise ValueError('Manifest run identity differs from its folder')
    # Validate immutable originals before contacting the database.
    for doc in manifest['snapshots']:
        original = Path(doc['source_artifact']).resolve()
        if not original.is_relative_to(ROOT.resolve()) or not original.is_file():
            raise ValueError('Resume original missing')
        if hashlib.sha256(original.read_bytes()).hexdigest() != doc['source_sha256']:
            raise ValueError('Resume original changed')
    for media in manifest.get('media', []):
        if media.get('state') != 'fetched':
            continue
        original = Path(media['source_artifact']).resolve()
        if not original.is_relative_to(ROOT.resolve()) or not original.is_file():
            raise ValueError('Resume image original missing')
        if hashlib.sha256(original.read_bytes()).hexdigest() != media['source_sha256']:
            raise ValueError('Resume image original changed')
    return manifest_path, manifest


def committed_result(path):
    """Reuse a verified prior commit receipt; never change it or request a platform."""
    manifest_path, manifest = load_frozen_manifest(path)
    status = manifest_path.parent / 'storage-status.json'
    if not status.exists():
        return None
    try:
        result = json.loads(status.read_text(encoding='utf-8'))
    except ValueError:
        # Older writers were not atomic. An incomplete receipt is not a commit.
        return None
    if (result.get('run_id') != manifest['run_id'] or result.get('database_state') != 'committed'
            or result.get('database', {}).get('readback') != 'verified'):
        return None
    return dict(result, **sampling_summary(manifest), folder=str(manifest_path.parent),
        resumed=True, storage_receipt_reused=True, storage_receipt_checked_at=now())


def resume(path):
    manifest_path, manifest = load_frozen_manifest(path)
    result = dict(run_id=manifest['run_id'], **sampling_summary(manifest),
        as_of=manifest.get('as_of'), folder=str(manifest_path.parent), resumed=True)
    return finish_ingestion(manifest, manifest_path.parent, result)


def run(*, config_path=None, as_of=None, units_override=None, imports=None, legacy=False,
        only_import=False, vm=True, skip_discovery=False, image_limit=None,
        platforms_override=None, detail_limit=None, keyword_override=None, sort_override=None,
        retry_platforms=None, bulk=False, run_id_override=None, generic_search=False, pages=1):
    if run_id_override is not None:
        import re
        if not re.fullmatch(r'(?:app-[a-f0-9]{32}(?:-[a-f0-9]{8})?|auto-[a-f0-9]{12}-[a-f0-9]{24}-a[1-9][0-9]*)', run_id_override):
            raise ValueError('Invalid application-owned social run id')
        existing = ROOT / '.research/social/runs' / run_id_override
        if existing.exists():
            if (existing / 'manifest.json').is_file():
                # Application task redelivery only resumes storage. Never repeat browser queries.
                return resume(existing)
            raise RuntimeError('Application social checkpoint incomplete; manual recovery required, no refetch')
    if not bulk and full_collection_active():
        return dict(state='full-collection-in-progress', database_state='not-applicable',
            reason='Social backfill owns the sampling budget; official/repository update can continue')
    config_path = config_path or ROOT / 'contracts/social-collection.json'
    config = json.loads(config_path.read_text(encoding='utf-8'))
    if platforms_override:
        if not set(platforms_override) <= {'xhs', 'zhihu', 'dy', 'bili'}:
            raise ValueError('Unsupported social platform')
        config['platforms'] = list(dict.fromkeys(platforms_override))
    if detail_limit is not None:
        if not 1 <= detail_limit <= 100:
            raise ValueError('Social sample limit out of range')
        config['detail_limit'] = detail_limit
    if not 1 <= pages <= 5: raise ValueError('Social pages must be 1—5')
    if pages > 1: config['worker_timeout_seconds'] = max(config['worker_timeout_seconds'],700)
    if sort_override:
        if sort_override not in ('latest', 'popular', 'general'):
            raise ValueError('Unsupported search sort')
        config['sorts'] = [sort_override]
    for platform in retry_platforms or []:
        if platform not in ('xhs', 'zhihu', 'dy', 'bili'):
            raise ValueError('Unsupported platform retry')
        set_platform_health(platform, 'retry-authorized')
    as_of = as_of or date.today().isoformat()
    unit_registry = ROOT / '.research/unit-dossiers-20261001/dossiers.json'
    units = [d['unit'] for d in json.loads(unit_registry.read_text(encoding='utf-8'))] if unit_registry.is_file() else []
    registered = set(units)
    units = list(dict.fromkeys(units + list(units_override or [])))
    if not units:
        raise ValueError('Provide collection units or an existing candidate registry')
    selected = units_override or units_for_day(units, as_of, config['units_per_day'])
    # Expand attribution without changing the frozen daily query rotation.
    extended = ROOT / '.research/full-collection-20261008/expanded-corpus.json'
    if extended.is_file():
        registry = json.loads(extended.read_text(encoding='utf-8'))
        names = [u.get('name') or u.get('unit') for u in registry['units'] if u.get('name') or u.get('unit')]
        registered.update(names)
        units = list(dict.fromkeys(units + names))
    if generic_search:
        units = [u for u in units if u in registered]
    if not units_override and len(selected) > 4:
        raise ValueError('Daily unit budget too large')
    run_id = run_id_override or as_of.replace('-', '') + '-' + uuid.uuid4().hex[:12]
    folder = ROOT / '.research/social/runs' / run_id
    folder.mkdir(parents=True)
    manifest = dict(run_id=run_id, started_at=now(), as_of=as_of, state='collected',
        query_version=config['query_version'], selected_units=selected, policy=config['policy'],
        jobs=[], artifacts=[], snapshots=[], candidates=[], reviewed_claims=[],
        sampling='bounded-keyword-sample', trend_state='not-estimated')
    if not only_import:
        from mediacrawler_worker import cdp_health
        collector = Path(config['collector'])
        before = collector_version(collector)
        manifest['collector'] = before
        with collector_lock(ROOT, config['platforms'][0] if len(config['platforms']) == 1 else 'global'):
            reachable = cdp_health(config['cdp_port'])
            for unit in selected:
                query = keyword_override or config['query_templates'][date.fromisoformat(as_of).toordinal() % len(config['query_templates'])].format(unit=unit)
                for platform in config['platforms']:
                    for sort in config['sorts']:
                        task = dict(collector=str(collector), cdp_port=config['cdp_port'], unit=unit,
                            keyword=query, platform=platform, sort=sort, limit=config['detail_limit'],generic_search=generic_search,pages=pages)
                        if not reachable:
                            manifest['jobs'].append(dict(task, state='needs-human', reason='chrome-debugging-unavailable'))
                            continue
                        health = platform_health().get(platform, {})
                        detail_only = (platform=='zhihu' and health.get('reason')=='platform-access-refused'
                                       and health.get('restriction_scope')=='platform-detail')
                        if platform_paused(platform, health):
                            manifest['jobs'].append(dict(task, state='needs-human',
                                reason=health['reason'], retry_state='paused-until-human-completes-verification'))
                            continue
                        job_id = uuid.uuid4().hex[:12]
                        task_path, output = folder / (job_id + '.task.json'), folder / (job_id + '.result.json')
                        task_path.write_text(encode(task), encoding='utf-8')
                        try:
                            with (folder / (job_id + '.private.log')).open('wb') as log:
                                process = subprocess.run([config['python'], '-X', 'utf8', '-B',
                                    str(ROOT / 'tools/research/mediacrawler_worker.py'), '--task', str(task_path),
                                    '--output', str(output)], stdout=log, stderr=log,
                                    timeout=config['worker_timeout_seconds'], cwd=ROOT)
                            data = json.loads(output.read_text(encoding='utf-8')) if output.exists() else dict(state='failed', reason='worker-result-missing', exit_code=process.returncode)
                            if data.get('reason') == 'platform-verification-required':
                                set_platform_health(platform, 'needs-human', data['reason'])
                            elif data.get('state') == 'needs-human' and data.get('error_type') in (
                                    'ForbiddenError', 'PlatformAccessError', 'IPBlockError'):
                                set_platform_health(platform, 'needs-human', data.get('reason'),data.get('failure_phase'))
                            elif data.get('state') in ('collected', 'empty-sample'):
                                if detail_only:
                                    set_platform_health(platform,'partial-access','platform-access-refused','platform-detail')
                                else:set_platform_health(platform, 'accessible')
                            elif data.get('state') == 'partial':
                                set_platform_health(platform, 'transient-error', data.get('reason'))
                            for doc in data.pop('documents', []):
                                doc.update(query=query, query_sort=data.get('actual_sort') or sort,
                                    requested_query_sort=sort, collection_route=data.get('collection_route') or 'mediacrawler-client',
                                    provider='mediacrawler', observed_at=data.get('observed_at') or now())
                                add_document(manifest, folder, doc, units)
                            raw_responses = data.pop('public_responses', [])
                            if raw_responses:
                                raw_path = folder / 'raw' / (job_id + '-public-response.json')
                                raw_path.parent.mkdir(exist_ok=True)
                                raw_path.write_text(encode(public_response(raw_responses)), encoding='utf-8')
                                manifest['artifacts'].append(str(raw_path))
                            manifest['jobs'].append(dict(task, **data))
                        except subprocess.TimeoutExpired:
                            manifest['jobs'].append(dict(task, state='partial', reason='worker-budget-expired'))
            after = collector_version(collector)
            if before != after:
                raise RuntimeError('Shared collector changed during this batch; review before importing')
            manifest['shared_configuration_unchanged'] = True
        if not skip_discovery:
            visited = set()
            for unit in selected:
                for platform, domain in [('zhihu', 'zhuanlan.zhihu.com'), ('xhs', 'xiaohongshu.com')]:
                    search = discover(f'site:{domain} {unit} 2027 408 考研')
                    artifact = folder / 'raw' / (hashlib.sha256(encode(search).encode()).hexdigest() + '-search.json')
                    artifact.parent.mkdir(exist_ok=True)
                    artifact.write_text(encode(search), encoding='utf-8')
                    manifest['artifacts'].append(str(artifact))
                    manifest['jobs'].append(dict(platform=platform, route='web-discovery', state=search['status'], query=search.get('query')))
                    links = [clean_url(r.get('url') or '') for r in search.get('results') or []]
                    for url in [u for u in links if safe_social_url(u)][:config['fallback_results_per_query']]:
                        if url in visited or len(visited) >= config['fallback_max_pages']:
                            continue
                        visited.add(url)
                        result = public_page(url)
                        doc = result.pop('document', None)
                        if doc:
                            doc['query'] = search.get('query')
                            add_document(manifest, folder, doc, units)
                        manifest['jobs'].append(dict(url=url, route='public-http', **result))
    if imports:
        for doc in json.loads(Path(imports).read_text(encoding='utf-8')):
            add_document(manifest, folder, doc, units)
    if legacy:
        for path in (ROOT / '.research/heat').rglob('search_contents_*.json'):
            observed = __import__('datetime').datetime.fromtimestamp(path.stat().st_mtime, __import__('datetime').timezone.utc).isoformat()
            for raw in json.loads(path.read_text(encoding='utf-8')):
                doc = document('xhs', public_response(raw), full=True)
                doc.update(provider='mediacrawler-historical-import', observed_at=observed,
                    query=raw.get('source_keyword'), original_local_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                    observed_time_basis='legacy-file-mtime-not-new-collection')
                add_document(manifest, folder, doc, units)
    collect_images(manifest, folder, config.get('image_limit', 24) if image_limit is None else image_limit)
    manifest['artifacts'] = list(dict.fromkeys(manifest['artifacts']))
    sampling = sampling_summary(manifest)
    manifest['state'] = sampling['state']
    (folder / 'manifest.json').write_text(encode(manifest), encoding='utf-8')
    result = dict(run_id=run_id, as_of=as_of, **sampling, folder=str(folder))
    return finish_ingestion(manifest, folder, result, vm)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--as-of')
    parser.add_argument('--unit', action='append')
    parser.add_argument('--import-public-documents', type=Path)
    parser.add_argument('--legacy', action='store_true')
    parser.add_argument('--only-import', action='store_true')
    parser.add_argument('--local-only', action='store_true')
    parser.add_argument('--skip-discovery', action='store_true')
    parser.add_argument('--image-limit', type=int, default=None)
    parser.add_argument('--resume', type=Path, help='Retry MySQL ingestion of an existing frozen batch; no refetch')
    parser.add_argument('--platform', choices=['xhs', 'zhihu', 'dy', 'bili'], action='append')
    parser.add_argument('--limit', type=int, help='Small validation budget per platform')
    parser.add_argument('--keyword', help='Validation query; daily collection keeps its versioned templates')
    parser.add_argument('--sort', choices=['latest', 'popular', 'general'])
    parser.add_argument('--retry-platform', choices=['xhs', 'zhihu', 'dy', 'bili'], action='append',
        help='One retry after the user completes a platform verification')
    args = parser.parse_args()
    if args.resume:
        print(encode(resume(args.resume)))
        return
    print(encode(run(as_of=args.as_of, units_override=args.unit, imports=args.import_public_documents,
        legacy=args.legacy, only_import=args.only_import, vm=not args.local_only,
        skip_discovery=args.skip_discovery, image_limit=args.image_limit,
        platforms_override=args.platform, detail_limit=args.limit,
        keyword_override=args.keyword, sort_override=args.sort, retry_platforms=args.retry_platform)))


if __name__ == '__main__':
    main()
