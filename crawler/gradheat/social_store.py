"""Immutable public social evidence, backed by the existing original-byte store."""
import hashlib
import json
from pathlib import Path
from .material_store import archive, encode, readback


def migrate(con, root):
    path = root / 'crawler/sql/008_social_evidence.sql'
    checksum = hashlib.sha256(path.read_bytes()).hexdigest()
    with con.cursor() as cur:
        cur.execute('SELECT checksum FROM research_schema_migration WHERE migration_id=%s', (path.name,))
        old = cur.fetchone()
        if old:
            if old[0] != checksum:
                raise ValueError('Social migration checksum changed')
            return
        for statement in path.read_text(encoding='utf-8').split(';'):
            if statement.strip():
                cur.execute(statement)
        cur.execute('INSERT INTO research_schema_migration(migration_id,checksum) VALUES(%s,%s)', (path.name, checksum))
    con.commit()


def store(con, root, manifest):
    migrate(con, root)
    for doc in manifest['snapshots']:
        path = Path(doc['source_artifact']).resolve()
        if not path.is_relative_to(root.resolve()) or not path.is_file():
            raise ValueError('Social original missing')
        if hashlib.sha256(path.read_bytes()).hexdigest() != doc['source_sha256']:
            raise ValueError('Social original changed before ingestion')
        if hashlib.sha256(encode({k:v for k,v in doc.items() if k != 'id'}).encode()).hexdigest() != doc['id']:
            raise ValueError('Social snapshot identity mismatch')
    for media in manifest.get('media', []):
        if media.get('state') != 'fetched':
            continue
        path = Path(media['source_artifact']).resolve()
        if not path.is_relative_to(root.resolve()) or not path.is_file():
            raise ValueError('Social image original missing')
        if hashlib.sha256(path.read_bytes()).hexdigest() != media['source_sha256']:
            raise ValueError('Social image original changed before ingestion')
    paths = [(Path(p), 'social-public-evidence') for p in manifest['artifacts']]
    with con.cursor() as cur:
        cur.execute("SELECT GET_LOCK('gradheat_material_archive',60)")
        if cur.fetchone()[0] != 1:
            raise RuntimeError('Material archive busy')
    try:
        materials = archive(con, paths, root)
    finally:
        with con.cursor() as cur:
            cur.execute("SELECT RELEASE_LOCK('gradheat_material_archive')")
    try:
        inserted_snapshots = inserted_claims = 0
        with con.cursor() as cur:
            cur.execute('INSERT IGNORE INTO social_collection_run(run_id,started_at,state,summary_json) VALUES(%s,%s,%s,%s)',
                (manifest['run_id'], manifest['started_at'], manifest['state'], encode(manifest)))
            for doc in manifest['snapshots']:
                cur.execute('INSERT IGNORE INTO social_content_snapshot(snapshot_id,run_id,platform,content_id,observed_at,published_at,artifact_sha256,content_sha256,content_level,payload_json) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                    (doc['id'], manifest['run_id'], doc['platform'], doc['content_id'], doc['observed_at'], doc.get('published_at'),
                     doc['source_sha256'], hashlib.sha256(doc.get('text', '').encode()).hexdigest(), doc['content_level'], encode(doc)))
                inserted_snapshots += cur.rowcount
            for claim in manifest['candidates'] + manifest.get('reviewed_claims', []):
                cur.execute('INSERT IGNORE INTO social_claim(claim_id,snapshot_id,review_state,payload_json) VALUES(%s,%s,%s,%s)',
                    (claim['id'], claim['snapshot_id'], claim.get('review_state', 'candidate'), encode(claim)))
                inserted_claims += cur.rowcount
            cur.execute('SELECT summary_json FROM social_collection_run WHERE run_id=%s', (manifest['run_id'],))
            if json.loads(cur.fetchone()[0]) != manifest:
                raise ValueError('Social manifest readback mismatch')
            for doc in manifest['snapshots']:
                cur.execute('SELECT payload_json FROM social_content_snapshot WHERE snapshot_id=%s', (doc['id'],))
                if json.loads(cur.fetchone()[0]) != doc:
                    raise ValueError('Social snapshot readback mismatch')
            for claim in manifest['candidates'] + manifest.get('reviewed_claims', []):
                cur.execute('SELECT payload_json FROM social_claim WHERE claim_id=%s', (claim['id'],))
                if json.loads(cur.fetchone()[0]) != claim:
                    raise ValueError('Social claim readback mismatch')
        con.commit()
    except Exception:
        con.rollback()
        raise
    return dict(run_id=manifest['run_id'], snapshots=len(manifest['snapshots']),
        candidates=len(manifest['candidates']), reviewed_claims=len(manifest.get('reviewed_claims', [])),
        inserted_snapshots=inserted_snapshots, inserted_claims=inserted_claims,
        materials=materials, readback='verified')
