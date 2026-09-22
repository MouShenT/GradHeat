#!/usr/bin/env python3
"""Local-only SearXNG client with immutable response evidence and failure states."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time
import urllib.parse
import urllib.request

ALLOWED = {'google cse', 'brave', 'bing', 'crossref', 'arxiv'}
DEFAULT = ['google cse', 'bing']
HEALTH_ENGINES = ['google cse', 'brave', 'bing']

def search(query, engines, evidence_dir):
    if not query.strip() or len(query) > 2000:
        raise ValueError('Query must contain 1..2000 characters')
    if not engines or not set(engines).issubset(ALLOWED):
        raise ValueError('Unsupported engine selection')
    started = datetime.now(timezone.utc)
    record = {'query': query, 'engines': engines, 'observed_at': started.isoformat()}
    begin = time.monotonic()
    try:
        url = 'http://127.0.0.1:8890/search?' + urllib.parse.urlencode({'q': query, 'engines': ','.join(engines), 'format': 'json'})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url, timeout=35) as response:
            raw = response.read(20_000_001)
        if len(raw) > 20_000_000:
            raise ValueError('Response too large')
        data = json.loads(raw)
        if not isinstance(data.get('results'), list):
            raise ValueError('Unexpected response shape')
        failures = data.get('unresponsive_engines', [])
        rows = data['results']
        record.update(status=('degraded' if failures else 'healthy') if rows else ('down' if failures else 'empty'), result_count=len(rows), failed_engines=failures, results=rows)
        digest = hashlib.sha256(raw).hexdigest()
        evidence_dir.mkdir(parents=True, exist_ok=True)
        raw_path = evidence_dir / (digest + '.json')
        try:
            with raw_path.open('xb') as fh:
                fh.write(raw)
        except FileExistsError:
            pass
        record.update(raw_sha256=digest, raw_path=str(raw_path))
    except Exception as exc:
        record.update(status='down', error_type=type(exc).__name__, result_count=None)
    record['elapsed_seconds'] = round(time.monotonic() - begin, 3)
    evidence_dir.mkdir(parents=True, exist_ok=True)
    import uuid
    metadata = evidence_dir / (started.strftime('%Y%m%dT%H%M%S') + '-' + uuid.uuid4().hex + '.meta.json')
    metadata.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    record['evidence_record'] = str(metadata)
    return record

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--stdin', action='store_true')
    parser.add_argument('--health', action='store_true')
    parser.add_argument('--query')
    parser.add_argument('--evidence-dir', type=Path, default=Path('/opt/gradheat/evidence/search'))
    args = parser.parse_args()
    request = json.load(sys.stdin) if args.stdin else {'operation':'health' if args.health else 'search', 'query':args.query}
    if request.get('operation') == 'health':
        def probe(engine):
            report = search('graduate admissions China', [engine], args.evidence_dir)
            return {k:v for k,v in report.items() if k != 'results'}
        with ThreadPoolExecutor(max_workers=3) as executor:
            records = list(executor.map(probe, HEALTH_ENGINES))
        print(json.dumps({'checks':records}, ensure_ascii=True))
        return 0 if all(r['status']=='healthy' for r in records) else 1
    if request.get('operation', 'search') != 'search':
        raise ValueError('Unknown operation')
    record = search(request.get('query') or '', request.get('engines') or DEFAULT, args.evidence_dir)
    print(json.dumps(record, ensure_ascii=True))
    return 1 if record['status']=='down' else 0

if __name__ == '__main__':
    raise SystemExit(main())
