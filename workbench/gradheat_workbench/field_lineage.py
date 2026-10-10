"""Reviewed field provenance can differ from a repository row's general URL."""
import hashlib
import json
from pathlib import Path


def load_overrides(root):
    root = Path(root).resolve()
    path = root / '.research/source-consensus/field-origin-overrides.json'
    if not path.exists():
        return {}
    entries = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(entries, list):
        raise ValueError('Field lineage reviews must be a list')
    with path.open('rb') as stream:
        review_sha = hashlib.file_digest(stream, 'sha256').hexdigest()
    result = {}
    verified_files = {}
    for entry in entries:
        required = ('candidate_id', 'field', 'artifact', 'artifact_sha256',
                    'origin_id', 'source_url', 'reason', 'quote_field', 'quote',
                    'reviewed_at', 'locator')
        if any(not entry.get(k) for k in required) or 'expected_value' not in entry:
            raise ValueError('Incomplete field lineage review')
        if entry.get('verification') != 'passage-verified':
            raise ValueError('Unreviewed field provenance cannot change a vote')
        artifact = Path(entry['artifact']).resolve()
        if not artifact.is_relative_to(root) or not artifact.is_file():
            raise ValueError('Field lineage original unavailable')
        if artifact not in verified_files:
            with artifact.open('rb') as stream:
                verified_files[artifact] = hashlib.file_digest(stream, 'sha256').hexdigest()
        if verified_files[artifact] != entry['artifact_sha256']:
            raise ValueError('Field lineage original changed')
        if entry.get('review_evidence_artifact'):
            evidence = Path(entry['review_evidence_artifact']).resolve()
            if not evidence.is_relative_to(root) or not evidence.is_file():
                raise ValueError('Field lineage review evidence unavailable')
            with evidence.open('rb') as stream:
                if hashlib.file_digest(stream, 'sha256').hexdigest() != entry.get('review_evidence_sha256'):
                    raise ValueError('Field lineage review evidence changed')
        key = (entry['candidate_id'], entry['field'])
        if key in result:
            raise ValueError('Duplicate field lineage review')
        result[key] = dict(entry, review_artifact=str(path), review_sha256=review_sha)
    return result


def resolve(row, field, value, overrides, canonical):
    review = overrides.get((row.get('id'), field))
    if review is None:
        return None
    if row.get('artifact_sha256') != review['artifact_sha256'] or row.get('locator') != review['locator']:
        raise ValueError('Field lineage review does not match candidate original')
    raw = row.get('raw') if isinstance(row.get('raw'), dict) else {}
    if review['quote'] not in str(raw.get(review['quote_field']) or ''):
        raise ValueError('Field lineage quotation does not match candidate')
    if canonical(value) != canonical(review['expected_value']):
        raise ValueError('Field lineage review does not match field value')
    return review


def load_exclusions(root):
    root = Path(root).resolve()
    path = root / '.research/source-consensus/candidate-exclusions.json'
    if not path.exists():
        return {}
    reviews = json.loads(path.read_text(encoding='utf-8'))
    result = {}
    for review in reviews:
        if review.get('verification') != 'passage-verified' or review.get('action') not in ('exclude-row', 'withhold-field'):
            raise ValueError('Unreviewed candidate exclusion')
        if any(not review.get(k) for k in ('candidate_id', 'artifact', 'artifact_sha256', 'locator', 'reason', 'quote_field', 'quote')):
            raise ValueError('Incomplete candidate exclusion')
        artifact = Path(review['artifact']).resolve()
        if not artifact.is_relative_to(root) or not artifact.is_file():
            raise ValueError('Excluded candidate original unavailable')
        with artifact.open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != review['artifact_sha256']:
                raise ValueError('Excluded candidate original changed')
        key = (review['candidate_id'], '*' if review['action'] == 'exclude-row' else review.get('field'))
        if key[1] is None or key in result:
            raise ValueError('Ambiguous candidate exclusion')
        result[key] = review
    return result


def excluded(row, field, reviews):
    review = reviews.get((row.get('id'), '*')) or reviews.get((row.get('id'), field))
    if review is None:
        return False
    if row.get('artifact_sha256') != review['artifact_sha256'] or row.get('locator') != review['locator']:
        raise ValueError('Excluded candidate identity changed')
    if review['quote'] not in str((row.get('raw') or {}).get(review['quote_field']) or ''):
        raise ValueError('Excluded candidate quotation changed')
    return True
