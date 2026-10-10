"""Submit frozen, previously failed MySQL batches; never request a platform."""
import argparse
import json
from pathlib import Path

from collect_social_sources import ROOT, resume
from social_evidence import encode, now


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--limit',type=int,default=30)
    args=parser.parse_args()
    if not 1<=args.limit<=100:parser.error('limit must be 1..100 frozen batches')
    pending=[]
    for status_path in sorted((ROOT/'.research/social/runs').glob('*/storage-status.json')):
        status=json.loads(status_path.read_text(encoding='utf-8'))
        if status.get('database_state')=='needs-retry' and (status_path.parent/'manifest.json').exists():
            pending.append(status_path.parent)
    results=[]
    for folder in pending[:args.limit]:
        result=resume(folder)
        results.append(dict(run_id=result['run_id'],database_state=result['database_state']))
        print(encode(results[-1]),flush=True)
    report=dict(checked_at=now(),pending_at_start=len(pending),attempted=len(results),
        committed=sum(r['database_state']=='committed' for r in results),results=results,
        platform_requests=0,fully_collected=False)
    target=ROOT/'.research/social/backlog-recovery'
    target.mkdir(parents=True,exist_ok=True)
    path=target/(now().replace(':','-')+'.json')
    path.write_text(encode(report),encoding='utf-8')
    print(encode({k:v for k,v in report.items() if k!='results'}))


if __name__=='__main__':main()
