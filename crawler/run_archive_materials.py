"""Backfill all locally collected admissions originals into MySQL."""
import argparse,json,hashlib
from pathlib import Path
from gradheat.material_store import archive,inventory,migrate
from gradheat.vm_db import connect_vm

ROOT=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--inventory-only',action='store_true');parser.add_argument('--referenced-only',action='store_true');args=parser.parse_args()
    paths=[] if args.referenced_only else list(inventory(ROOT))
    report={'files':len(paths),'local_bytes':sum(p.stat().st_size for p,_ in paths)}
    print(json.dumps(report),flush=True)
    if args.inventory_only:return
    out=ROOT/'.research/material-storage';out.mkdir(parents=True,exist_ok=True)
    with connect_vm(out) as con:
        migrate(con,ROOT)
        with con.cursor() as cur:
            cur.execute('SELECT a.artifact_path,a.sha256 FROM research_artifact a LEFT JOIN material_blob b ON b.sha256=a.sha256 WHERE b.sha256 IS NULL')
            referenced=cur.fetchall()
        for filename,expected in referenced:
            path=Path(filename).resolve()
            if not path.is_relative_to(ROOT) or not path.is_file():raise ValueError('Referenced original is unavailable')
            with path.open('rb') as stream:actual=hashlib.file_digest(stream,'sha256').hexdigest()
            if actual!=expected:raise ValueError('Referenced original hash changed')
            paths.append((path,'referenced-original'))
        paths=list({str(p):(p,kind) for p,kind in paths}.values())
        report['files']=len(paths);report['local_bytes']=sum(p.stat().st_size for p,_ in paths)
        with con.cursor() as cur:
            cur.execute("SELECT GET_LOCK('gradheat_material_archive',0)")
            if cur.fetchone()[0]!=1:raise RuntimeError('Another material archive is running')
        try:report.update(archive(con,paths,ROOT))
        finally:
            with con.cursor() as cur:cur.execute("SELECT RELEASE_LOCK('gradheat_material_archive')")
    (out/('referenced-backfill.json' if args.referenced_only else 'latest.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report),flush=True)

if __name__=='__main__':main()
