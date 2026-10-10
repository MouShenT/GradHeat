"""Independent MySQL readback, all public-byte hashes, idempotency and conflict rollback."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import urllib.request
import uuid
from datetime import datetime,timezone

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'crawler'))
from gradheat.vm_db import connect_vm
from gradheat.material_store import encode, readback
from gradheat.social_store import store


def main(in_process_api=False):
    folder = ROOT / '.research/social/verification'
    with connect_vm(folder) as con:
        with con.cursor() as cur:
            cur.execute('SELECT run_id,summary_json FROM social_collection_run')
            manifests = {rid: json.loads(body) for rid, body in cur.fetchall()}
            cur.execute('SELECT platform,COUNT(*),COUNT(DISTINCT content_id) FROM social_content_snapshot GROUP BY platform')
            platforms = {p:dict(snapshots=n, unique_content=unique) for p,n,unique in cur.fetchall()}
            cur.execute('SELECT review_state,COUNT(*) FROM social_claim GROUP BY review_state')
            claim_counts = dict(cur.fetchall())
            hashes = set()
            for rid, manifest in manifests.items():
                for doc in manifest['snapshots']:
                    cur.execute('SELECT payload_json FROM social_content_snapshot WHERE snapshot_id=%s', (doc['id'],))
                    if json.loads(cur.fetchone()[0]) != doc:raise ValueError('Independent social readback failed')
                for filename in manifest['artifacts']:
                    sha = hashlib.sha256(Path(filename).read_bytes()).hexdigest()
                    hashes.add(sha)
        for sha in hashes:
            with con.cursor() as cur:
                actual, size, chunks = readback(cur, sha)
            if actual != sha:raise ValueError('MySQL public original checksum failed')
        # Retry an exact frozen run: no extra snapshots or claims.
        sampled = next(m for m in manifests.values() if m['snapshots'])
        retry = store(con, ROOT, sampled)
        if retry['inserted_snapshots'] or retry['inserted_claims']:raise ValueError('Retry duplicated social records')
        # Force a manifest collision after valid new inserts to exercise rollback.
        first = next(iter(manifests.values()))
        qa_doc = dict(sampled['snapshots'][0], run_id=first['run_id'], query='QA rollback; never committed')
        qa_doc.pop('id')
        qa_doc['id'] = hashlib.sha256(encode(qa_doc).encode()).hexdigest()
        disputed = dict(first, started_at='invalid-test-start', snapshots=[qa_doc],
            candidates=[], reviewed_claims=[], artifacts=sampled['artifacts'])
        with con.cursor() as cur:
            cur.execute('SELECT COUNT(*) FROM social_content_snapshot'); before = cur.fetchone()[0]
        try:store(con, ROOT, disputed)
        except ValueError:pass
        else:raise ValueError('Changed manifest was accepted')
        with con.cursor() as cur:
            cur.execute('SELECT COUNT(*) FROM social_content_snapshot')
            after=cur.fetchone()[0]
            if after < before:raise ValueError('Existing social snapshots disappeared')
            cur.execute('SELECT COUNT(*) FROM social_content_snapshot WHERE snapshot_id=%s', (qa_doc['id'],))
            if cur.fetchone()[0]:raise ValueError('QA social record was committed')
            cur.execute('SELECT summary_json FROM social_collection_run WHERE run_id=%s',(first['run_id'],))
            if json.loads(cur.fetchone()[0])!=first:raise ValueError('Failed batch changed the original manifest')
        con.commit()
        # Freeze the original already-committed review run for reproducible retries.
        review = next((m for m in manifests.values() if m.get('reviewed_claims')), None)
        if review:
            (ROOT / '.research/social/review-ingest/manifest.json').write_text(encode(review), encoding='utf-8')
    runtime = json.loads((ROOT / '.research/decision-workbench/runtime.json').read_text(encoding='utf-8'))
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    if in_process_api:
        sys.path.insert(0,str(ROOT/'workbench'))
        from fastapi.testclient import TestClient
        from gradheat_workbench.app import create_app
        with TestClient(create_app(session_db=folder/'api-check-sessions.sqlite'),base_url='http://127.0.0.1') as client:
            response=client.get('/api/admissions');response.raise_for_status()
            public=response.json();version=response.headers.get('X-Data-Version')
    else:
        with op.open(runtime['url'].rstrip('/') + '/api/admissions', timeout=25) as response:
            public = json.load(response)
            version = response.headers.get('X-Data-Version')
    serialized = encode(public)
    if any(k in serialized for k in ('source_url', 'source_artifact', 'zhihu.com', 'xiaohongshu.com')):
        raise ValueError('Social provenance leaked into public UI')
    latest = json.loads((ROOT / '.research/admissions-data/latest.json').read_text(encoding='utf-8'))
    if version != latest['version_id']:raise ValueError('Live page not serving latest publication')
    verified_at=datetime.now(timezone.utc)
    result = dict(state='verified',verified_at=verified_at.isoformat(), platform_counts=platforms, claims=claim_counts,
        checked_original_hashes=len(hashes), runs=len(manifests), idempotency='zero-new-records',
        failed_batch_rollback='verified', public_source_free=True, public_version=version,
        api_check_mode='in-process' if in_process_api else 'live-http',live_website_checked=not in_process_api,
        concurrent_snapshot_growth=after-before)
    prior=folder/'result.json'
    if prior.exists():
        preserved=folder/('result-previous-'+hashlib.sha256(prior.read_bytes()).hexdigest()[:20]+'.json')
        if not preserved.exists():preserved.write_bytes(prior.read_bytes())
    (folder/('result-'+verified_at.strftime('%Y%m%d-%H%M%S-%f')+'.json')).write_text(encode(result),encoding='utf-8')
    (folder / 'result.json').write_text(encode(result), encoding='utf-8')
    print(encode(result))


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--in-process-api',action='store_true',help='Check the real API handler in TestClient; does not certify a running website')
    main(parser.parse_args().in_process_api)
