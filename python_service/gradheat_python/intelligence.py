"""Per-school MySQL dossiers; raw sources remain behind the public projection."""
from . import bootstrap
from datetime import datetime, timezone
import hashlib
import json
import threading
import time

from gradheat.material_store import encode
from gradheat.db import _split_statements
from gradheat_core.admissions_decision import publication_version
from gradheat_core.history_alignment import align_history
from gradheat_core.intelligence import canonical, digest, identify, plausible_claims, heat_index, unique_units, unit_key


def migrate(con, root):
    path = root/'crawler/sql/010_school_intelligence.sql'
    checksum = hashlib.sha256(path.read_bytes()).hexdigest()
    with con.cursor() as cur:
        cur.execute("SELECT GET_LOCK('gradheat_school_migration',10)")
        if cur.fetchone()[0] != 1: raise RuntimeError('School migration busy')
    try:
        with con.cursor() as cur:
            cur.execute('SELECT checksum FROM research_schema_migration WHERE migration_id=%s', (path.name,))
            old = cur.fetchone()
            if old:
                if old[0] != checksum: raise ValueError('Applied school migration changed')
                return
            statements = _split_statements(path.read_text(encoding='utf-8'))
            if not all(s.lstrip().upper().startswith('CREATE TABLE IF NOT EXISTS ') for s in statements):
                raise ValueError('Only additive school migration allowed')
            for statement in statements: cur.execute(statement)
            cur.execute('INSERT INTO research_schema_migration(migration_id,checksum) VALUES(%s,%s)', (path.name,checksum))
        con.commit()
    finally:
        with con.cursor() as cur: cur.execute("SELECT RELEASE_LOCK('gradheat_school_migration')")


def refresh(con, root, payload):
    import yaml
    migrate(con, root)
    tiers = yaml.safe_load((root/'crawler/refs/school_tiers.yaml').read_text(encoding='utf-8'))
    c985, c211 = set(tiers['c985']), set(tiers['c211_extra'])
    version = publication_version(payload)
    registry_path = root/'.research/full-collection-20261008/expanded-corpus.json'
    registry = json.loads(registry_path.read_text(encoding='utf-8'))['units'] if registry_path.is_file() else []
    units = unique_units([u['name'] for u in payload['units']] + [u.get('name') or u.get('unit') for u in registry])
    identity={unit_key(u):u for u in units}
    registry_by_name = {}; materials={}
    for entry in registry:
        name=identity[unit_key(entry.get('name') or entry.get('unit'))]
        registry_by_name.setdefault(name,entry)
        materials.setdefault(name,[]).extend(entry.get('documents',[])+entry.get('supplement_documents',[]))
    now = datetime.now(timezone.utc).isoformat()
    dossiers = {u:dict(unit=u, tier='985' if u in c985 else '211' if u in c211 else '研究所' if '研究所' in u else '普通院校',
        admissions_version=version, observed_at=now, programmes=[], history=[], contents=[], claims=[], search_signals=[],
        official_materials=materials.get(u,[])) for u in units}
    for u,dossier in dossiers.items():
        if registry_by_name.get(u,{}).get('group') == '国科大培养单位目录扩展':
            dossier.update(parent_unit='中国科学院大学',entity_kind='cultivating-unit',tier='国科大培养单位')
    for p in payload['programmes']: dossiers[p['unit']]['programmes'].append(p)
    for h in payload.get('history', []):
        target=identity.get(unit_key(h.get('unit','')))
        if target in dossiers: dossiers[target]['history'].append(h)
    with con.cursor() as cur:
        cur.execute('SELECT unit_name,payload_json FROM collection_observation ORDER BY observation_id')
        for unit,raw in cur.fetchall():
            target=identity.get(unit_key(unit))
            if target in dossiers: dossiers[target]['official_materials'].append(json.loads(raw))
        # Stream all stored public snapshots; no arbitrary 1000-row school cap.
        cur.execute('SELECT snapshot_id,payload_json FROM social_content_snapshot ORDER BY observed_at,snapshot_id')
        count = 0; links_count = 0
        for sid, raw in cur.fetchall():
            doc = json.loads(raw)
            if doc.get('id') != sid or hashlib.sha256(encode({k:v for k,v in doc.items() if k!='id'}).encode()).hexdigest() != sid:
                raise ValueError('Social original integrity failure')
            links = identify(doc, units)
            count += 1
            for link in links:
                unit = link['unit']; dossier = dossiers[unit]
                dossier['contents'].append(dict(doc, attribution_weight=link['weight'], attribution_basis=link['basis']))
                cur.execute('INSERT INTO school_content_link(unit,snapshot_id,attribution_weight,basis) VALUES(%s,%s,%s,%s) ON DUPLICATE KEY UPDATE attribution_weight=VALUES(attribution_weight),basis=VALUES(basis)',
                    (unit,sid,link['weight'],link['basis']))
                links_count += 1
            for claim in plausible_claims(doc, links): dossiers[claim['unit']]['claims'].append(claim)
        cur.execute('SELECT signal_id,payload_json FROM school_search_signal ORDER BY observed_at')
        for signal_id, raw in cur.fetchall():
            signal = json.loads(raw)
            if digest(signal) != signal_id: raise ValueError('Search signal integrity failure')
            target=identity.get(unit_key(signal['unit']))
            if target in dossiers: dossiers[target]['search_signals'].append(signal)
        for unit, dossier in dossiers.items():
            # Independent chains agreeing on numeric facts increase confidence.
            groups = {}
            for claim in dossier['claims']:
                if claim['field'] == 'background_note': continue
                key = (claim['year'], claim['field'], claim['scope'], claim['value'])
                groups.setdefault(key, set()).add(claim['origin'])
            for claim in dossier['claims']:
                key = (claim['year'], claim['field'], claim['scope'], claim['value'])
                if len(groups.get(key, ())) >= 2: claim.update(confidence=.75, state='cross-source-consistent')
            dossier['heat'] = heat_index(dossier['contents'], dossier['search_signals'], now)
            dossier['counts'] = dict(programmes=len(dossier['programmes']), history=len(dossier['history']), official_materials=len(dossier['official_materials']),
                social_snapshots=len(dossier['contents']), claims=len(dossier['claims']), search_signals=len(dossier['search_signals']))
            body = canonical(dossier).encode(); sha = hashlib.sha256(body).hexdigest()
            cur.execute('INSERT IGNORE INTO school_dossier_version(unit,version_sha,admissions_version,observed_at,payload_json,canonical_bytes) VALUES(%s,%s,%s,%s,%s,%s)',
                (unit,sha,version,now,body.decode(),body))
            cur.execute('SELECT canonical_bytes FROM school_dossier_version WHERE unit=%s AND version_sha=%s', (unit,sha))
            if bytes(cur.fetchone()[0]) != body: raise ValueError('School dossier readback mismatch')
            cur.execute('INSERT INTO school_dossier_head(unit,version_sha) VALUES(%s,%s) ON DUPLICATE KEY UPDATE version_sha=VALUES(version_sha)', (unit,sha))
    con.commit()
    return dict(units=len(dossiers), scanned_snapshots=count, school_content_links=links_count,
        schools_with_heat=sum(d['heat']['heat_value'] is not None for d in dossiers.values()),
        extracted_claims=sum(len(d['claims']) for d in dossiers.values()), admissions_version=version, observed_at=now)


class DossierReader:
    def __init__(self, database):
        self.database = database; self.cache = None; self.lock = threading.RLock()

    def all(self, version):
        with self.lock:
            if self.cache and self.cache[0] == version and time.monotonic()-self.cache[1] < 60:
                return self.cache[2]
            with self.database.connect() as con:
                with con.cursor() as cur:
                    cur.execute('SELECT v.unit,v.version_sha,v.canonical_bytes FROM school_dossier_head h JOIN school_dossier_version v ON v.unit=h.unit AND v.version_sha=h.version_sha WHERE v.admissions_version=%s', (version,))
                    result = {}
                    for unit,sha,raw in cur.fetchall():
                        body = bytes(raw)
                        if hashlib.sha256(body).hexdigest() != sha: raise ValueError('School dossier hash mismatch')
                        item = json.loads(body)
                        if item['unit'] != unit or item['admissions_version'] != version: raise ValueError('School dossier identity mismatch')
                        item['dossier_version'] = sha; result[unit] = item
                con.rollback()
            self.cache = (version,time.monotonic(),result)
            return result

    def public(self, unit, version):
        d = self.all(version).get(unit)
        if d is None: return dict(unit=unit, available=False)
        return dict(unit=unit, available=True, tier=d['tier'], parent_unit=d.get('parent_unit'),entity_kind=d.get('entity_kind','admissions-unit'),counts=d['counts'], heat=d['heat'],
            programmes=d['programmes'], history=d['history'], dossier_version=d['dossier_version'],
            notes=list(dict.fromkeys(c['value'] for c in d['claims'] if c['field']=='background_note'))[:8])

    def summaries(self, version):
        return [dict(unit=d['unit'],tier=d['tier'],**d['heat']) for d in self.all(version).values()]
