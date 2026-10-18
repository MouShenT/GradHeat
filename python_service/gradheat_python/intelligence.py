"""Per-school MySQL dossiers; raw sources remain behind the public projection."""
from . import bootstrap
from datetime import datetime, timezone
import hashlib
import json
import math
import threading
import time

from gradheat.material_store import encode
from gradheat.db import _split_statements
from gradheat_core.admissions_decision import publication_version
from gradheat_core.history_alignment import align_history
from gradheat_core.decision_inputs import enrich_history, resolve_inputs
from gradheat_core.intelligence import canonical, digest, identify, plausible_claims, heat_index, unique_units, unit_key


def migrate(con, root):
    for name in ('010_school_intelligence.sql', '011_school_decision_facts.sql', '012_search_signal_bytes.sql', '013_school_web_sources.sql'):
        _migrate(con, root, name)


def _migrate(con, root, name):
    path = root/'crawler/sql'/name
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
        admissions_version=version, observed_at=now, programmes=[], history=[], contents=[], claims=[], search_signals=[], decision_facts=[],community_sources=[],
        official_materials=materials.get(u,[])) for u in units}
    for u,dossier in dossiers.items():
        if registry_by_name.get(u,{}).get('group') == '国科大培养单位目录扩展':
            dossier.update(parent_unit='中国科学院大学',entity_kind='cultivating-unit',tier='国科大培养单位')
    for p in payload['programmes']: dossiers[p['unit']]['programmes'].append(p)
    for h in payload.get('history', []):
        target=identity.get(unit_key(h.get('unit','')))
        if target in dossiers: dossiers[target]['history'].append(enrich_history(h))
    alignment=align_history(payload['programmes'],payload.get('history',[]))
    history_by_id={h['id']:h for h in payload.get('history',[])}
    with con.cursor() as cur:
        cur.execute('SELECT snapshot_sha,unit,canonical_bytes FROM school_web_source ORDER BY observed_at,snapshot_sha')
        websites={}
        for sha,unit,raw in cur.fetchall():
            if hashlib.sha256(bytes(raw)).hexdigest()!=sha:raise ValueError('Community source hash mismatch')
            source=json.loads(raw)
            if source['unit']!=unit:raise ValueError('Community source identity mismatch')
            websites[(unit,source['site_url'])]=source
        for (unit,_),source in websites.items():
            target=identity.get(unit_key(unit))
            if target in dossiers:
                dossiers[target]['community_sources'].append(source)
                from gradheat_core.community_sources import source_family
                for page in source['pages']:
                    doc=dict(id=page['source_sha256'],title=page['title'],text=page['text'],query=unit+' 考研',url=page['url'])
                    for claim in plausible_claims(doc,[dict(unit=target,weight=1,basis='school-guide')]):
                        claim['origin']='community:'+source_family(source['site_url'])
                        dossiers[target]['claims'].append(claim)
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
        cur.execute('SELECT s.signal_id,s.payload_json,b.canonical_bytes FROM school_search_signal s LEFT JOIN school_search_signal_bytes b ON b.signal_id=s.signal_id ORDER BY s.observed_at')
        for signal_id, raw, original in cur.fetchall():
            if original is not None: raw=bytes(original)
            signal = json.loads(raw)
            if digest(signal) != signal_id: raise ValueError('Search signal integrity failure')
            target=identity.get(unit_key(signal['unit']))
            if target in dossiers: dossiers[target]['search_signals'].append(signal)
        cur.execute('SELECT fact_sha,canonical_bytes FROM school_decision_fact ORDER BY observed_at,fact_sha')
        for sha,raw in cur.fetchall():
            body=bytes(raw)
            if hashlib.sha256(body).hexdigest()!=sha: raise ValueError('School fact integrity failure')
            fact=json.loads(body);target=identity.get(unit_key(fact['unit']))
            if target in dossiers: dossiers[target]['decision_facts'].append(fact)
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
            dossier['decision_inputs']={p['id']:resolve_inputs(p,dossier,[history_by_id[key] for key in alignment.get(p['id'],{}).get('matched',[]) if key in history_by_id])
                                        for p in dossier['programmes']}
            dossier['counts'] = dict(programmes=len(dossier['programmes']), history=len(dossier['history']), official_materials=len(dossier['official_materials']),
                social_snapshots=len(dossier['contents']), claims=len(dossier['claims']), search_signals=len(dossier['search_signals']),
                decision_facts=len(dossier['decision_facts']),numeric_quotas=sum(d['ordinary_quota'] is not None for d in dossier['decision_inputs'].values()),
                community_sites=len(dossier['community_sources']),community_score_rows=sum(len(s['scores']) for s in dossier['community_sources']),
                score_ready_programmes=sum(d['threshold'] is not None for d in dossier['decision_inputs'].values()))
            body = canonical(dossier).encode(); sha = hashlib.sha256(body).hexdigest()
            cur.execute('INSERT IGNORE INTO school_dossier_version(unit,version_sha,admissions_version,observed_at,payload_json,canonical_bytes) VALUES(%s,%s,%s,%s,%s,%s)',
                (unit,sha,version,now,body.decode(),body))
            cur.execute('SELECT canonical_bytes FROM school_dossier_version WHERE unit=%s AND version_sha=%s', (unit,sha))
            if bytes(cur.fetchone()[0]) != body: raise ValueError('School dossier readback mismatch')
            cur.execute('INSERT INTO school_dossier_head(unit,version_sha) VALUES(%s,%s) ON DUPLICATE KEY UPDATE version_sha=VALUES(version_sha)', (unit,sha))
    con.commit()
    return dict(units=len(dossiers), scanned_snapshots=count, school_content_links=links_count,
        schools_with_heat=sum(d['heat']['heat_value'] is not None for d in dossiers.values()),
        decision_facts=sum(len(d['decision_facts']) for d in dossiers.values()),
        community_sites=sum(len(d['community_sources']) for d in dossiers.values()),
        community_score_rows=sum(len(s['scores']) for d in dossiers.values() for s in d['community_sources']),
        numeric_quotas=sum(d['counts']['numeric_quotas'] for d in dossiers.values()),
        score_ready_programmes=sum(d['counts']['score_ready_programmes'] for d in dossiers.values()),
        extracted_claims=sum(len(d['claims']) for d in dossiers.values()), admissions_version=version, observed_at=now)


def public_admission_samples(source):
    """Expose source sample summaries without candidates or original payloads."""
    fields={key:(str,) for key in ('program_name','exam_text','distribution_population','verification_state')}
    fields.update({key:(int,) for key in ('year','record_count','admitted_sample_count','unadmitted_retest_sample_count')})
    fields.update({key:(int,float) for key in ('observed_retest_list_minimum','admitted_total_minimum')})
    samples=source.get('admission_samples',[])
    if not isinstance(samples,list):return []
    result=[]
    for row in samples:
        if not isinstance(row,dict):continue
        item={}
        for key,types in fields.items():
            if key not in row:continue
            value=row[key]
            if value is None or type(value) in types and (not isinstance(value,float) or math.isfinite(value)):
                item[key]=value
        if item:result.append(item)
    return result


class DossierReader:
    def __init__(self, database):
        self.database = database; self.cache = None; self.lock = threading.RLock()

    def all(self, version):
        with self.lock:
            if self.cache and self.cache[0] == version and time.monotonic()-self.cache[1] < 60:
                return self.cache[2]
            with self.database.connect() as con:
                with con.cursor() as cur:
                    # Hash the full immutable original in MySQL; transfer only
                    # algorithm inputs, not every school's raw discussion text.
                    fields = ('unit','admissions_version','observed_at','tier','heat','programmes','claims','decision_facts','community_sources')
                    paths = ','.join("'$."+key+"'" for key in fields)
                    cur.execute('SELECT v.unit,v.version_sha,SHA2(v.canonical_bytes,256),JSON_EXTRACT(CONVERT(v.canonical_bytes USING utf8mb4),'+paths+') FROM school_dossier_head h JOIN school_dossier_version v ON v.unit=h.unit AND v.version_sha=h.version_sha WHERE v.admissions_version=%s', (version,))
                    result = {}
                    for unit,sha,actual_sha,raw in cur.fetchall():
                        if actual_sha != sha: raise ValueError('School dossier hash mismatch')
                        values = json.loads(raw)
                        if isinstance(values,list) and len(values)==len(fields):
                            item = {key:value for key,value in zip(fields,values) if value is not None}
                        else:
                            # JSON_EXTRACT omits absent paths in older dossiers.
                            # Fall back only for that one verified original.
                            cur.execute('SELECT canonical_bytes FROM school_dossier_version WHERE unit=%s AND version_sha=%s',(unit,sha))
                            original=cur.fetchone()
                            if original is None or hashlib.sha256(bytes(original[0])).hexdigest()!=sha: raise ValueError('School dossier hash mismatch')
                            full=json.loads(bytes(original[0]));item={key:full[key] for key in fields if key in full}
                        if item['unit'] != unit or item['admissions_version'] != version: raise ValueError('School dossier identity mismatch')
                        item['dossier_version'] = sha; result[unit] = item
                con.rollback()
            self.cache = (version,time.monotonic(),result)
            return result

    def public(self, unit, version):
        # A single school must not wait for all dossiers to cross the network.
        with self.database.connect() as con:
            with con.cursor() as cur:
                cur.execute('SELECT v.version_sha,v.canonical_bytes FROM school_dossier_head h JOIN school_dossier_version v ON v.unit=h.unit AND v.version_sha=h.version_sha WHERE v.unit=%s AND v.admissions_version=%s', (unit,version))
                row = cur.fetchone()
                if row is None: return dict(unit=unit,available=False)
                sha,raw = row;body=bytes(raw)
                if hashlib.sha256(body).hexdigest()!=sha: raise ValueError('School dossier hash mismatch')
                d=json.loads(body)
                if d['unit']!=unit or d['admissions_version']!=version: raise ValueError('School dossier identity mismatch')
                d['dossier_version']=sha
            con.rollback()
        return dict(unit=unit, available=True, tier=d['tier'], parent_unit=d.get('parent_unit'),entity_kind=d.get('entity_kind','admissions-unit'),counts=d['counts'], heat=d['heat'],
            programmes=[dict(p,decision_inputs=d.get('decision_inputs',{}).get(p['id'])) for p in d['programmes']], history=d['history'], dossier_version=d['dossier_version'],
            decision_facts=[dict({key:f[key] for key in ('year','department','major_code','major_name','mode','route','population','values','campus','cutoff_kind','excerpt') if key in f},
                                **({'url':f['source_url']} if f.get('source_url') else {})) for f in d.get('decision_facts',[]) if not f.get('special')],
            community_sources=[dict(title=s.get('title') or s['unit'],url=s['site_url'],observed_at=s['observed_at'],
                pages=[dict(title=p['title'],url=p['url']) for p in s['pages']],scores=s['scores'],score_url=s['score_url'],
                admission_samples=public_admission_samples(s),gaps=len(s['gaps']),source_type='community') for s in d.get('community_sources',[])],
            notes=list(dict.fromkeys(c['value'] for c in d['claims'] if c['field']=='background_note'))[:8])

    def summaries(self, version):
        return [dict(unit=d['unit'],tier=d['tier'],**d['heat']) for d in self.all(version).values()]
