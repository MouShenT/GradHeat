"""Immutable canonical JSON bytes shared across Python and Java runtimes."""
import hashlib
import json
from .material_store import encode


def canonical_bytes(version, payload):
    raw = encode(payload).encode('utf-8')
    if hashlib.sha256(raw).hexdigest() != version:
        raise ValueError('Publication canonical SHA mismatch')
    return raw


def store_publication_bytes(cur, version, payload):
    raw = canonical_bytes(version, payload)
    cur.execute('INSERT IGNORE INTO admissions_publication_bytes(version_id,content) VALUES(%s,%s)', (version, raw))
    cur.execute('SELECT content FROM admissions_publication_bytes WHERE version_id=%s', (version,))
    stored = cur.fetchone()
    if not stored or stored[0] != raw:
        raise ValueError('Immutable publication byte readback differs')
    return len(raw)


def backfill(con):
    """Replay existing immutable publications; never change their head or values."""
    with con.cursor() as cur:
        cur.execute('SELECT version_id FROM admissions_publication ORDER BY created_at,version_id')
        versions = [r[0] for r in cur.fetchall()]
    completed = 0
    total_bytes = 0
    for version in versions:
        try:
            with con.cursor() as cur:
                cur.execute('SELECT payload_json FROM admissions_publication WHERE version_id=%s', (version,))
                row = cur.fetchone()
                if not row:
                    raise ValueError('Publication disappeared during byte replay')
                total_bytes += store_publication_bytes(cur, version, json.loads(row[0]))
            con.commit()
            completed += 1
        except Exception:
            con.rollback()
            raise
    return {'publications_verified': completed, 'canonical_bytes': total_bytes, 'head_changed': False}
