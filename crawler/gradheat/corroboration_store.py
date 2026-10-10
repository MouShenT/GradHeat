"""Append-only observations and decisions; preserve every conflicting value."""
import hashlib,json
from collections import Counter
from pathlib import Path
from .material_store import archive,encode

def store(con,root,checker):
    path=root/'crawler/sql/005_corroboration.sql';sha=hashlib.sha256(path.read_bytes()).hexdigest()
    with con.cursor() as cur:
        cur.execute('SELECT checksum FROM research_schema_migration WHERE migration_id=%s',(path.name,));old=cur.fetchone()
        if old and old[0]!=sha:raise ValueError('Corroboration migration changed')
        if not old:
            for sql in path.read_text(encoding='utf-8').split(';'):
                if sql.strip():cur.execute(sql)
            cur.execute('INSERT INTO research_schema_migration(migration_id,checksum) VALUES(%s,%s)',(path.name,sha))
    con.commit()
    originals={}
    for row in checker.rows:
        for path_key,sha_key in [('artifact','artifact_sha256'),('lineage_review_artifact','lineage_review_sha256'),('lineage_evidence_artifact','lineage_evidence_sha256')]:
            if not row.get(path_key):continue
            p=Path(row[path_key]).resolve()
            if not p.is_relative_to(root.resolve()) or not p.is_file():raise ValueError('Missing original for consensus')
            if p not in originals:
                with p.open('rb') as stream:actual=hashlib.file_digest(stream,'sha256').hexdigest()
            else:actual=originals[p]
            if row.get(sha_key) and row[sha_key]!=actual:raise ValueError('Consensus original changed')
            originals[p]=actual
    with con.cursor() as cur:
        cur.execute("SELECT GET_LOCK('gradheat_material_archive',60)")
        if cur.fetchone()[0]!=1:raise RuntimeError('Original archive busy')
    try:materials=archive(con,[(p,'consensus-original') for p in originals],root)
    finally:
        with con.cursor() as cur:cur.execute("SELECT RELEASE_LOCK('gradheat_material_archive')")
    decisions=checker.decisions();agreements=checker.information_agreements(decisions)
    report=dict(policy=checker.policy,observations=len(checker.rows),decisions=len(decisions),
        states=dict(Counter(x['state'] for x in decisions)),origins=len({x['origin_id'] for x in checker.rows}),
        agreed_information=len(agreements),information_agreements=agreements,
        observation_ids=sorted(x['id'] for x in checker.rows),decision_ids=sorted(x['id'] for x in decisions))
    rid=hashlib.sha256(encode(report).encode()).hexdigest()
    try:
        with con.cursor() as cur:
            cur.executemany('INSERT IGNORE INTO corroboration_observation(observation_id,scope_id,field_name,origin_id,official,artifact_sha256,payload_json) VALUES(%s,%s,%s,%s,%s,%s,%s)',
                [(x['id'],x['scope_id'],x['field'],x['origin_id'],int(x['official']),originals.get(Path(x['artifact']).resolve()) if x.get('artifact') else x.get('artifact_sha256'),encode(x)) for x in checker.rows])
            cur.executemany('INSERT IGNORE INTO corroboration_decision(decision_id,policy_version,scope_id,field_name,distinct_origins,verification_state,official_state,payload_json) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)',
                [(x['id'],x['policy'],x['scope_id'],x['field'],x['agreeing_sources'],x['state'],x['official_state'],encode(x)) for x in decisions])
            cur.execute('INSERT IGNORE INTO corroboration_run(run_id,payload_json) VALUES(%s,%s)',(rid,encode(report)))
        con.commit()
        with con.cursor() as cur:
            cur.execute('SELECT payload_json FROM corroboration_run WHERE run_id=%s',(rid,))
            if json.loads(cur.fetchone()[0])!=report:raise ValueError('Consensus report readback failed')
        con.commit()
    except Exception:con.rollback();raise
    folder=root/'.research/source-consensus';folder.mkdir(parents=True,exist_ok=True)
    (folder/(rid+'.json')).write_text(encode(report),encoding='utf-8')
    result=dict(run_id=rid,policy=report['policy'],observations=report['observations'],decisions=report['decisions'],states=report['states'],agreed_information=report['agreed_information'],origins=report['origins'],materials=materials)
    (folder/'latest.json').write_text(encode(result),encoding='utf-8')
    return result
