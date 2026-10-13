"""Rebuild school-local dossiers from committed sources; optionally import search data."""
import argparse
from datetime import date
import json
import hashlib
from pathlib import Path
import sys
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'python_service'))
from gradheat_python import bootstrap
from gradheat.vm_db import connect_vm
from gradheat.material_store import encode
from gradheat_core.intelligence import digest, number, date_value
from gradheat_core.admissions_decision import publication_version
from gradheat_python.intelligence import migrate, refresh


def import_search(con, rows, units, root=ROOT):
    originals=[]
    for r in rows:
        if (r.get('unit') not in units or r.get('kind') not in ('search-index','search-volume')
            or number(r.get('value')) is None or r['value'] < 0 or number(r.get('reference_scale')) is None
            or r['reference_scale'] <= 0 or not r.get('provider') or not r.get('keyword')
            or urlsplit(r.get('source_url','')).scheme not in ('http','https')
            or date_value(r.get('window_start')) is None or date_value(r.get('window_end')) is None
            or date_value(r['window_start']) > date_value(r['window_end']) or date_value(r.get('observed_at')) is None):
            raise ValueError('Search record needs actual measured index/volume, school, source and comparable window/scale')
        if r.get('source_artifact'):
            source=Path(r['source_artifact']).resolve()
            if not source.is_relative_to(root.resolve()) or not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest()!=r.get('raw_sha256'):
                raise ValueError('Search original integrity mismatch')
            originals.append(source)
        if r.get('daily'):
            days=[d.get('date') for d in r['daily']]
            if len(set(days))!=len(days) or any(date_value(d) is None or not date_value(r['window_start'])<=date_value(d)<=date_value(r['window_end']) for d in days):
                raise ValueError('Search daily dates differ from their window')
            known=[d['value'] for d in r['daily'] if d.get('value') is not None]
            if not known or any(number(v) is None or v<0 for v in known) or abs(sum(known)/len(known)-r['value'])>1e-6:
                raise ValueError('Search mean differs from its observed daily values')
    if originals:
        from gradheat.material_store import archive_serial
        archive_serial(con,[(p,'search-index-original') for p in set(originals)],root,progress=lambda *a,**kw:None)
    with con.cursor() as cur:
        for row in rows:
            cur.execute('INSERT IGNORE INTO school_search_signal(signal_id,unit,observed_at,payload_json) VALUES(%s,%s,%s,%s)',
                (digest(row),row['unit'],row['observed_at'],encode(row)))
            # MySQL's native JSON may round the last bit of a binary float.
            # Exact canonical bytes, rather than re-serialized JSON, are authoritative.
            body=encode(row).encode()
            cur.execute('INSERT IGNORE INTO school_search_signal_bytes(signal_id,canonical_bytes) VALUES(%s,%s)',(digest(row),body))
            cur.execute('SELECT canonical_bytes FROM school_search_signal_bytes WHERE signal_id=%s',(digest(row),))
            if bytes(cur.fetchone()[0])!=body: raise ValueError('Search signal readback mismatch')
    con.commit()


def rebuild(root=ROOT, search=None, facts=None, community=None):
    with connect_vm(root/'.research/school-intelligence/private') as con:
        with con.cursor() as cur:
            cur.execute("SELECT p.content,p.version_id FROM admissions_publication_bytes p JOIN admissions_head h ON h.version_id=p.version_id WHERE h.name='current'")
            raw, version = cur.fetchone(); payload = json.loads(raw)
            if publication_version(payload) != version: raise ValueError('Publication integrity mismatch')
        migrate(con, root)
        if community:
            from collect_community_sources import import_sources
            registry_path=root/'.research/full-collection-20261008/expanded-corpus.json'
            registry=json.loads(registry_path.read_text(encoding='utf-8'))['units'] if registry_path.is_file() else []
            names=[u['name'] for u in payload['units']]+[u.get('name') or u.get('unit') for u in registry]
            community_report=import_sources(con,root,json.loads(Path(community).read_text(encoding='utf-8-sig')),names)
        if facts:
            from gradheat_python.school_facts import import_facts
            registry_path=root/'.research/full-collection-20261008/expanded-corpus.json'
            registry=json.loads(registry_path.read_text(encoding='utf-8'))['units'] if registry_path.is_file() else []
            names=[u['name'] for u in payload['units']]+[u.get('name') or u.get('unit') for u in registry]
            fact_report=import_facts(con,root,json.loads(Path(facts).read_text(encoding='utf-8-sig')),names)
        if search:
            registry_path=root/'.research/full-collection-20261008/expanded-corpus.json'
            registry=json.loads(registry_path.read_text(encoding='utf-8'))['units'] if registry_path.is_file() else []
            names=[u['name'] for u in payload['units']]+[u.get('name') or u.get('unit') for u in registry]
            rows=json.loads(Path(search).read_text(encoding='utf-8-sig'))
            for row in rows:
                original=Path(search).parent/(str(row.get('raw_sha256',''))+'.json')
                if 'source_artifact' not in row and original.is_file(): row['source_artifact']=str(original.resolve())
            import_search(con,rows,names,root)
        report = refresh(con,root,payload)
        if facts: report['fact_import']=fact_report
        if community: report['community_import']=community_report
    folder = root/'.research/school-intelligence'; folder.mkdir(parents=True,exist_ok=True)
    (folder/'latest-report.json').write_text(encode(report),encoding='utf-8')
    return report


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--search-json',type=Path); args=p.parse_args()
    print(encode(rebuild(search=args.search_json)))
