"""Validate release declarations; does not authenticate evidence or model quality."""
import argparse
from datetime import datetime
import json
import re
from pathlib import Path
from urllib.parse import urlsplit
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = json.loads((ROOT / 'contracts/release.schema.json').read_text(encoding='utf-8'))
FORMATS = FormatChecker()

@FORMATS.checks('date-time', raises=ValueError)
def checked_datetime(value):
    if not isinstance(value, str):
        return True
    # Deliberately accept a strict RFC3339 subset, independent of optional extras.
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})', value):
        return False
    if value.endswith('-00:00'):  # RFC3339 unknown local offset is not a known instant.
        return False
    if value[-1] != 'Z' and (int(value[-5:-3]) > 23 or int(value[-2:]) > 59):
        return False
    return instant(value).utcoffset() is not None

def instant(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))

def validate(manifest):
    errors = [f"{'/'.join(map(str, e.absolute_path)) or '$'}: {e.message}"
              for e in Draft202012Validator(SCHEMA, format_checker=FORMATS).iter_errors(manifest)]
    if errors:
        return errors
    cutoff, generated = instant(manifest['cutoff']), instant(manifest['generated_at'])
    if generated < cutoff:
        errors.append('generated_at precedes cutoff')
    seen = set()
    for field in ('release_id', 'snapshot_id', 'analysis_version'):
        if not manifest[field].strip():
            errors.append(f'blank {field}')
    for row in manifest['evidence']:
        key = row['fact_revision']
        if key in seen:
            errors.append(f'duplicate fact_revision: {key}')
        seen.add(key)
        try:
            url = urlsplit(row['source_url'])
            valid_url = url.scheme in ('http', 'https') and bool(url.hostname) and not url.username and not url.password and not re.search(r'\s', row['source_url'])
            _ = url.port
        except ValueError:
            valid_url = False
        if not valid_url:
            errors.append(f'{key}: valid public HTTP(S) source URL required')
        published, observed = instant(row['published_at']), instant(row['observed_at'])
        if published > cutoff:
            errors.append(f'{key}: publication after decision cutoff')
        if observed > generated:
            errors.append(f'{key}: observation after release generation')
        if manifest['mode'] == 'live_snapshot' and observed > cutoff:
            errors.append(f'{key}: observation after live cutoff')
        if manifest['mode'] == 'reconstructed' and not row.get('publication_proof', '').strip():
            errors.append(f'{key}: reconstructed history requires publication_proof')
        for field in ('fact_revision', 'pool_version', 'locator', 'review_id'):
            if not row[field].strip():
                errors.append(f'{key}: blank {field}')
    required = ['pool_consistency', 'evidence_review', 'snapshot_integrity']
    if manifest['capability'] in ('scenario', 'probability'):
        required.append('scenario_sensitivity')
    if manifest['capability'] == 'probability':
        required += ['temporal_validation', 'calibration', 'applicability']
    for name in required:
        gate = manifest['checks'].get(name, {})
        if gate.get('status') != 'passed' or not gate.get('report_ref', '').strip():
            errors.append(f'{name}: passed review with report_ref required')
    return errors

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    args = parser.parse_args()
    try:
        errors = validate(json.loads(args.manifest.read_text(encoding='utf-8-sig')))
    except (OSError, ValueError) as exc:
        print(json.dumps({'valid': False, 'errors': [str(exc)]}, ensure_ascii=True))
        return 1
    print(json.dumps({'valid': not errors, 'errors': errors}, ensure_ascii=True))
    return int(bool(errors))

if __name__ == '__main__':
    raise SystemExit(main())
