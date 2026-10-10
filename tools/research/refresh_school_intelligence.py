"""Rebuild school-local dossiers from committed sources; optionally import search data."""
import argparse
from datetime import date
import json
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


def import_search(con, rows, units):
    for r in rows:
        if (r.get('unit') not in units or r.get('kind') not in ('search-index','search-volume')
            or number(r.get('value')) is None or r['value'] < 0 or number(r.get('reference_scale')) is None
            or r['reference_scale'] <= 0 or not r.get('provider') or not r.get('keyword')
            or urlsplit(r.get('source_url','')).scheme not in ('http','https')
            or date_value(r.get('window_start')) is None or date_value(r.get('window_end')) is None
            or date_value(r['window_start']) > date_value(r['window_end']) or date_value(r.get('observed_at')) is None):
            raise ValueError('Search record needs actual measured index/volume, school, source and comparable window/scale')
    with con.cursor() as cur:
        for row in rows:
            cur.execute('INSERT IGNORE INTO school_search_signal(signal_id,unit,observed_at,payload_json) VALUES(%s,%s,%s,%s)',
                (digest(row),row['unit'],row['observed_at'],encode(row)))
    con.commit()


def rebuild(root=ROOT, search=None):
    with connect_vm(root/'.research/school-intelligence/private') as con:
        with con.cursor() as cur:
            cur.execute("SELECT p.content,p.version_id FROM admissions_publication_bytes p JOIN admissions_head h ON h.version_id=p.version_id WHERE h.name='current'")
            raw, version = cur.fetchone(); payload = json.loads(raw)
            if publication_version(payload) != version: raise ValueError('Publication integrity mismatch')
        migrate(con, root)
        if search:
            registry_path=root/'.research/full-collection-20261008/expanded-corpus.json'
            registry=json.loads(registry_path.read_text(encoding='utf-8'))['units'] if registry_path.is_file() else []
            names=[u['name'] for u in payload['units']]+[u.get('name') or u.get('unit') for u in registry]
            import_search(con,json.loads(Path(search).read_text(encoding='utf-8-sig')),names)
        report = refresh(con,root,payload)
    folder = root/'.research/school-intelligence'; folder.mkdir(parents=True,exist_ok=True)
    (folder/'latest-report.json').write_text(encode(report),encoding='utf-8')
    return report


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--search-json',type=Path); args=p.parse_args()
    print(encode(rebuild(search=args.search_json)))
