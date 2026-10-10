"""Read back current consensus, candidate records and public projection from MySQL."""
import argparse
import hashlib
import json
import sys
from pathlib import Path
from urllib.request import urlopen
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'crawler'), str(ROOT / 'workbench')]
from gradheat.vm_db import connect_vm
from gradheat.material_store import encode
from gradheat_workbench.corroboration import digest


def run(in_process_api=False):
    folder = ROOT / '.research/source-consensus'
    latest = json.loads((folder / 'latest.json').read_text(encoding='utf-8'))
    expected_run = json.loads((folder / (latest['run_id'] + '.json')).read_text(encoding='utf-8'))
    candidates = json.loads((ROOT / '.research/github-sources/candidates.json').read_text(encoding='utf-8'))
    pointer = json.loads((ROOT / '.research/admissions-data/latest.json').read_text(encoding='utf-8'))
    with connect_vm(folder) as con:
        with con.cursor() as cur:
            cur.execute('SELECT payload_json FROM corroboration_run WHERE run_id=%s', (latest['run_id'],))
            stored_run = json.loads(cur.fetchone()[0])
            assert stored_run == expected_run
            assert hashlib.sha256(encode(stored_run).encode()).hexdigest() == latest['run_id']
            for table, id_field, expected in [
                ('corroboration_observation', 'observation_id', stored_run['observation_ids']),
                ('corroboration_decision', 'decision_id', stored_run['decision_ids'])
            ]:
                cur.execute(f'SELECT {id_field},payload_json FROM {table}')
                actual = {}
                for row_id, raw in cur.fetchall():
                    item = json.loads(raw)
                    item_id = item.pop('id')
                    assert row_id == item_id == digest(item)
                    actual[row_id] = item
                assert set(expected).issubset(actual)
            cur.execute('SELECT candidate_id,payload_json FROM external_candidate')
            stored_candidates = {row_id: json.loads(raw) for row_id, raw in cur.fetchall()}
            assert all(stored_candidates.get(row['id']) == row for row in candidates)
            cur.execute("SELECT COUNT(*),COALESCE(SUM(byte_size),0) FROM material_blob WHERE state='complete'")
            unique, size = cur.fetchone()
            cur.execute("SELECT COUNT(*) FROM material_blob WHERE state<>'complete'")
            assert cur.fetchone()[0] == 0
            # Hash columns in older tables have different character sets. A
            # cross-charset SQL join can defeat the blob's primary-key index
            # and multiply two entire tables during a readback check. Compare
            # the bounded hash sets instead, without a long server-side join.
            cur.execute("SELECT sha256 FROM material_blob WHERE state='complete'")
            complete_hashes={row[0] for row in cur.fetchall()}
            for table in ('research_artifact', 'corroboration_observation', 'external_candidate'):
                field = 'sha256' if table == 'research_artifact' else 'artifact_sha256'
                cur.execute(f"SELECT DISTINCT {field} FROM {table} WHERE {field} IS NOT NULL")
                referenced={row[0] for row in cur.fetchall()}
                assert referenced <= complete_hashes,(table,len(referenced-complete_hashes))
            cur.execute("SELECT p.version_id,p.payload_json,p.internal_manifest FROM admissions_head h JOIN admissions_publication p ON p.version_id=h.version_id WHERE h.name='current'")
            version, raw, internal = cur.fetchone()
            payload, manifest = json.loads(raw), json.loads(internal)
            assert version == pointer['version_id'] == hashlib.sha256(encode(payload).encode()).hexdigest()
            assert manifest['consensus_run_id'] == latest['run_id']
        con.rollback()
    runtime=ROOT/'.research/decision-workbench/runtime.json'
    base=json.loads(runtime.read_text(encoding='utf-8-sig'))['url'].rstrip('/') if runtime.exists() else 'http://127.0.0.1:18727'
    if in_process_api:
        # Check the actual handler without launching a persistent service.
        from fastapi.testclient import TestClient
        from gradheat_workbench.app import create_app
        with TestClient(create_app(session_db=folder/'api-check-sessions.sqlite'),base_url='http://127.0.0.1') as client:
            response=client.get('/api/admissions');response.raise_for_status()
            live=response.json()
    else:
        with urlopen(base+'/api/admissions', timeout=30) as response:
            live = json.load(response)
    assert live == payload
    def check_public(value):
        if isinstance(value, dict):
            for key, child in value.items():
                assert key not in ('source_url', 'source_artifact', 'artifact', 'artifact_sha256', 'source_sha256', 'origin_id')
                check_public(child)
        elif isinstance(value, list):
            for child in value:
                check_public(child)
        elif isinstance(value, str):
            assert 'http://' not in value and 'https://' not in value and str(ROOT) not in value
    check_public(live)
    verified_at = datetime.now(timezone.utc)
    result = dict(verified_on=verified_at.astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat(),
        verified_at=verified_at.isoformat(), run_id=latest['run_id'], publication_version=version,
        policy=latest['policy'],agreed_information=latest.get('agreed_information',0),
        candidate_readback=len(candidates), observation_readback=latest['observations'],
        decision_readback=latest['decisions'], states=latest['states'], stored_unique=unique,
        stored_bytes=int(size), incomplete_materials=0, missing_originals=0,
        publication_matches_live_api=not in_process_api, publication_matches_checked_api=True,
        api_check_mode='in-process' if in_process_api else 'live-http',public_projection_without_sources=True)
    path = folder / ('verification-' + verified_at.strftime('%Y%m%d-%H%M%S-%f') + '.json')
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    (folder / 'verification-latest.json').write_text(encode(dict(path=str(path),**result)),encoding='utf-8')
    print(encode(result))


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--in-process-api',action='store_true',help='Check the real API handler in TestClient; does not certify a running website')
    run(parser.parse_args().in_process_api)
