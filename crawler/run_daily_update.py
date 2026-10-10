"""Daily official checks -> immutable originals -> research DB -> public data/cache.

Candidate extraction never upgrades verification. Human/browser steps remain in
the review queue; a failed fetch is never labelled 'not published'.
"""
import argparse,hashlib,json,os,sys,subprocess
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools/research'))
sys.path.insert(0,str(ROOT/'python_service'))
from gradheat.material_store import archive,archive_references,encode,migrate,missing_references
from gradheat.vm_db import connect_vm
from gradheat.publication import publish
from gradheat_core.repository import ResearchRepository
from gradheat_core.admissions import build_public
from gradheat_core.corroboration import Corroborator,observations
from gradheat.corroboration_store import store as store_corroboration
import check_latest_notices as notices
import build_unit_dossiers as dossiers
import build_comparison_draft as comparison
import run_import_research as research_import
import fetch_github_sources
import compare_github_sources
import extract_dossier_evidence
import collect_social_sources


@contextmanager
def local_lock(wait=False, stop_event=None):
    folder=ROOT/'.research/daily-update';folder.mkdir(parents=True,exist_ok=True)
    with (folder/'run.lock').open('a+b') as stream:
        stream.seek(0);stream.write(b'0');stream.flush();stream.seek(0)
        if os.name=='nt':
            import msvcrt
            while True:
                try:
                    msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1);break
                except OSError:
                    if not wait: raise
                    if stop_event is not None and stop_event.wait(3): raise InterruptedError('Cancelled while queued')
                    if stop_event is None:
                        import time
                        time.sleep(3)
        else:
            import fcntl
            fcntl.flock(stream.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        try:yield
        finally:
            stream.seek(0)
            if os.name=='nt':msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
            else:fcntl.flock(stream.fileno(),fcntl.LOCK_UN)


def store_collection_ledger(con,batch_name,started_at,report,sources):
    """Store the frozen ledger without one remote round trip per URL."""
    rows=[]
    for source in sources:
        sha=source.get('sha256') if source.get('raw_path') else None
        oid=hashlib.sha256((batch_name+'\n'+encode(source)).encode()).hexdigest()
        rows.append((oid,batch_name,source['unit'],source['url'],sha,source['status'],encode(source)))
    with con.cursor() as cur:
        cur.execute('INSERT IGNORE INTO collection_run(run_id,started_at,summary_json) VALUES(%s,%s,%s)',(batch_name,started_at,encode(report)))
        for start in range(0,len(rows),100):
            cur.executemany('INSERT IGNORE INTO collection_observation(observation_id,run_id,unit_name,url,sha256,state,payload_json) VALUES(%s,%s,%s,%s,%s,%s,%s)',rows[start:start+100])
    con.commit()


def run(args):
    now=datetime.now(ZoneInfo('Asia/Shanghai'))
    if args.resume:
        batch=Path(args.resume).resolve()
        if not batch.is_relative_to(ROOT/'.research/daily-update'):raise ValueError('Resume only a local daily batch')
        report=json.loads((batch/'summary.json').read_text(encoding='utf-8'))
    else:
        batch=ROOT/'.research/daily-update'/(now.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8])
        report=notices.run(batch=batch,as_of=args.as_of or now.date().isoformat(),max_sources=args.max_sources,
            corpus_path=args.corpus,all_units=args.all_units)
    if args.collect_only:
        print(encode({'stage':'collected-local-only','path':str(batch),'summary':report}),flush=True);return
    sources=json.loads((batch/'sources.json').read_text(encoding='utf-8'))
    paths=list({x['raw_path']:None for x in sources if x.get('raw_path') and Path(x['raw_path']).is_file()})
    with connect_vm(batch) as con:
        migrate(con,ROOT)
        with con.cursor() as cur:
            cur.execute("SELECT GET_LOCK('gradheat_material_archive',60)")
            if cur.fetchone()[0]!=1:raise RuntimeError('Material backfill busy; resume this batch after it completes')
        try:
            paths+= [filename for filename,_ in missing_references(con)]
            material_report=archive(con,[(Path(p),'original') for p in dict.fromkeys(paths)],ROOT)
        finally:
            with con.cursor() as cur:cur.execute("SELECT RELEASE_LOCK('gradheat_material_archive')")
        store_collection_ledger(con,batch.name,now.isoformat(),report,sources)
    # Fresh HTML line extraction and PDF page location stay candidates.
    # The queue date controls frozen discovery/rotation. Publication reflects
    # when the actual source checks completed, including a midnight resumption.
    dossiers.REPORT_DATE=datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat();extract_dossier_evidence.extract()
    # Rebuild documents/snapshot without rewriting earlier frozen versions.
    dossiers.build();comparison.run()
    subprocess.run([sys.executable,'-X','utf8','-B',str(ROOT/'crawler/run_import_research.py'),'--vm'],check=True,cwd=ROOT)
    with connect_vm(batch) as con:
        with con.cursor() as cur:
            cur.execute("SELECT GET_LOCK('gradheat_material_archive',60)")
            if cur.fetchone()[0]!=1:raise RuntimeError('Material archive busy after research import')
        try:references=archive_references(con,ROOT)
        finally:
            with con.cursor() as cur:cur.execute("SELECT RELEASE_LOCK('gradheat_material_archive')")
    github={'state':'not-run'}
    if not args.skip_github:
        try:
            fetch_github_sources.run()
            github=compare_github_sources.run()
        except Exception as error:
            github={'state':'needs-retry','error_type':type(error).__name__}
    social={'state':'not-run'}
    if not args.skip_social:
        try:social=collect_social_sources.run(as_of=report['as_of'])
        except Exception as error:social={'state':'needs-retry','error_type':type(error).__name__}
    repo=ResearchRepository(ROOT);payload=build_public(repo)
    payload['last_checked']=datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()
    with connect_vm(batch) as con:
        consensus=store_corroboration(con,ROOT,Corroborator(observations(repo)))
        publication=publish(con,ROOT,payload,{'snapshot_id':repo.manifest['snapshot_id'],'research_batch_id':repo.batch_id,'run_id':batch.name,'consensus_run_id':consensus['run_id'],'state':'data-draft'})
    try:
        sys.path.insert(0,str(ROOT/'python_service'))
        from gradheat_python.intelligence import refresh
        with connect_vm(batch) as con: school_intelligence=refresh(con,ROOT,payload)
    except Exception as error:
        school_intelligence={'state':'needs-refresh','error_type':type(error).__name__}
    final={'stage':'committed','path':str(batch),'collection':report,'materials':material_report,'referenced_materials':references,'github':github,'social':social,'publication':publication,'school_intelligence':school_intelligence}
    (batch/'completed.json').write_text(json.dumps(final,ensure_ascii=False,indent=2),encoding='utf-8')
    pointer=ROOT/'.research/daily-update/latest.json';temp=pointer.with_suffix('.tmp')
    temp.write_text(encode(final),encoding='utf-8');temp.replace(pointer)
    print(encode(final),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--max-sources',type=int,default=300)
    parser.add_argument('--collect-only',action='store_true')
    parser.add_argument('--resume')
    parser.add_argument('--skip-github',action='store_true',help='Official-only recovery run; normal daily runs also check GitHub')
    parser.add_argument('--skip-social',action='store_true',help='Recovery only; normal daily runs sample Xiaohongshu/Zhihu/Douyin/Bilibili')
    parser.add_argument('--as-of',help='Explicit research date; original acquisition timestamps remain unchanged')
    parser.add_argument('--all-units',action='store_true')
    parser.add_argument('--corpus',type=Path,help='Frozen full-collection unit corpus')
    args=parser.parse_args()
    if not 68<=args.max_sources<=2000:parser.error('max-sources must be between 68 and 2000')
    with local_lock():run(args)
