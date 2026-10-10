"""Append a correction for already-saved verification responses; never rewrite a run."""
import argparse
import hashlib
import json
from pathlib import Path
import uuid

from collect_social_sources import ROOT, finish_ingestion, set_platform_health
from social_evidence import encode, now, PlatformVerificationRequired, validate_search


def review(paths, as_of):
    jobs, artifacts, units = [], [], set()
    for path in paths:
        path = Path(path).resolve()
        if path.is_dir():path /= 'manifest.json'
        if not path.is_relative_to((ROOT / '.research/social/runs').resolve()):
            raise ValueError('Review only saved project collection runs')
        previous = json.loads(path.read_text(encoding='utf-8'))
        units.update(previous.get('selected_units', []))
        for source in path.parent.glob('raw/*-public-response.json'):
            response = json.loads(source.read_text(encoding='utf-8'))
            for item in response:
                if not isinstance(item, dict) or 'search_nil_info' not in item:continue
                try:validate_search('dy', item)
                except PlatformVerificationRequired:
                    jobs.append(dict(platform='dy', state='needs-human', reason='platform-verification-required',
                        route='saved-response-review', references_run_id=previous['run_id'],
                        previous_state=next((j['state'] for j in previous['jobs'] if j.get('platform') == 'dy'), None),
                        source_artifact=str(source), source_sha256=hashlib.sha256(source.read_bytes()).hexdigest()))
                    artifacts.append(str(source))
    if not jobs:raise ValueError('No saved verification responses to correct')
    set_platform_health('dy', 'needs-human', 'platform-verification-required')
    run_id = as_of.replace('-', '') + '-access-review-' + uuid.uuid4().hex[:12]
    folder = ROOT / '.research/social/runs' / run_id
    folder.mkdir(parents=True)
    manifest = dict(run_id=run_id, started_at=now(), as_of=as_of, state='partial',
        selected_units=sorted(units), policy='social-evidence-v1', query_version='saved-access-review-v1',
        jobs=jobs, artifacts=list(dict.fromkeys(artifacts)), snapshots=[], candidates=[], reviewed_claims=[])
    (folder / 'manifest.json').write_text(encode(manifest), encoding='utf-8')
    return finish_ingestion(manifest, folder, dict(run_id=run_id, state='needs-human',
        corrected_jobs=len(jobs), snapshots=0, candidates=0, folder=str(folder)))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--as-of', required=True)
    parser.add_argument('paths', nargs='+', type=Path)
    args = parser.parse_args()
    print(encode(review(args.paths, args.as_of)))
