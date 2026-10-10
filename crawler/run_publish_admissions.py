import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'workbench'))
from gradheat_workbench.repository import ResearchRepository
from gradheat_workbench.admissions import build_public
from gradheat.material_store import archive_references,migrate
from gradheat.publication import publish
from gradheat.vm_db import connect_vm
from gradheat_workbench.corroboration import Corroborator,observations
from gradheat.corroboration_store import store as store_corroboration

def main():
    repo=ResearchRepository(ROOT);payload=build_public(repo)
    latest=ROOT/'.research/daily-update/latest.json'
    if latest.exists():
        check=json.loads(latest.read_text(encoding='utf-8'))
        if check.get('stage')=='committed':payload['last_checked']=check['collection']['as_of']
    with connect_vm(ROOT/'.research/admissions-data') as con:
        migrate(con,ROOT)
        with con.cursor() as cur:
            cur.execute("SELECT GET_LOCK('gradheat_material_archive',60)")
            if cur.fetchone()[0]!=1:raise RuntimeError('Material archive busy')
        try:archive_references(con,ROOT)
        finally:
            with con.cursor() as cur:cur.execute("SELECT RELEASE_LOCK('gradheat_material_archive')")
        consensus=store_corroboration(con,ROOT,Corroborator(observations(repo)))
        report=publish(con,ROOT,payload,{'snapshot_id':repo.manifest['snapshot_id'],'research_batch_id':repo.batch_id,'source_sha256':repo.data_sha256,'consensus_run_id':consensus['run_id'],'state':'data-draft'})
        report['corroboration']=consensus
    report.update(payload['counts'])
    (ROOT/'.research/admissions-data/publication-status.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))

if __name__=='__main__':main()
