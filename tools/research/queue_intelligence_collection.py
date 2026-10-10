"""One queued search-then-social run, serialized behind the existing collector."""
import argparse
from datetime import date, timedelta, datetime, timezone
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'python_service'))
sys.path.insert(0,str(ROOT/'crawler'))
from gradheat_python import bootstrap
from gradheat_core.intelligence import canonical,digest
from run_daily_update import local_lock
from collect_search_indices import collect
from refresh_school_intelligence import rebuild


def main():
    p=argparse.ArgumentParser();p.add_argument('--search-queries',type=Path,required=True)
    p.add_argument('--social-batch',type=Path,required=True);p.add_argument('--hours',type=float,default=8)
    p.add_argument('--search-limit',type=int,default=2000)
    args=p.parse_args();runtime=ROOT/'.research/school-intelligence/queued-collection.json'
    record=dict(pid=os.getpid(),batch=str(args.social_batch.resolve()),execution_hours_after_lock=args.hours,
        search_query_sha=digest(json.loads(args.search_queries.read_text(encoding='utf-8-sig'))))
    def mark(state,**values):
        record.update(state=state,updated_at=datetime.now(timezone.utc).isoformat(),**values)
        runtime.write_text(canonical(record),encoding='utf-8')
    mark('queued-behind-existing-collector')
    with local_lock(wait=True):
        mark('collecting-search-indices')
        try:
            queries=json.loads(args.search_queries.read_text(encoding='utf-8-sig'))
            start,end=date.today()-timedelta(days=30),date.today()-timedelta(days=1)
            pilot=ROOT/'.research/school-intelligence/search-index-pilot/signals.json'
            cached=json.loads(pilot.read_text(encoding='utf-8')) if pilot.is_file() else []
            done={(r['unit'],r['keyword']) for r in cached if r['window_start']==start.isoformat() and r['window_end']==end.isoformat()}
            queries=[q for q in queries if (q['unit'],q['keyword']) not in done]
            folder=ROOT/'.research/school-intelligence/search-index-queued'
            result=collect(queries,ROOT/'.research/school-intelligence/private/baidu-cookies.json',
                ROOT/'.research/opensource/qdata',folder,start,end,args.search_limit)
            mark('search-indices-collected',search_result=result)
            if result['signals']: mark('search-indices-imported',dossiers=rebuild(search=folder/'signals.json'))
        except Exception as error: mark('search-needs-attention',search_error_type=type(error).__name__)
    mark('waiting-for-social-lock')
    from gradheat_python.collection_cli import run
    try:
        result=run(args.social_batch.resolve(),hours=args.hours,wait_for_lock=True)
        mark('social-run-finished',social_result={k:result[k] for k in ('finished','material_scope_complete','processed_jobs') if k in result})
    except Exception as error: mark('social-needs-attention',social_error_type=type(error).__name__)


if __name__=='__main__': main()
