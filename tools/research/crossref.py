"""Official Crossref metadata lookup. A hit is not full-text verification."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import urllib.parse
import requests

def main():
    p=argparse.ArgumentParser()
    group=p.add_mutually_exclusive_group(required=True)
    group.add_argument('--query')
    group.add_argument('--doi')
    p.add_argument('--limit',type=int,default=5,choices=range(1,21))
    args=p.parse_args()
    url='https://api.crossref.org/works'
    params={'query.bibliographic':args.query,'rows':args.limit} if args.query else {}
    if args.doi:
        url += '/' + urllib.parse.quote(args.doi.removeprefix('https://doi.org/'),safe='')
    r=requests.get(url,params=params,headers={'User-Agent':'GradHeat-research/1.0 (metadata verification)','Accept':'application/json'},timeout=(10,35))
    r.raise_for_status()
    d=r.json()
    if d.get('status') != 'ok': raise ValueError('Crossref did not return ok')
    items=d['message'].get('items',[]) if args.query else [d['message']]
    report={'retrieved_at':datetime.now(timezone.utc).isoformat(),'source_url':r.url,'verification':'metadata_only','items':items}
    target=Path(__file__).resolve().parents[2]/'.research'/'crossref'
    target.mkdir(parents=True,exist_ok=True)
    digest=hashlib.sha256(r.content).hexdigest()
    (target/(digest+'.json')).write_bytes(r.content)
    (target/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')+'.meta.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    for item in items:
        print(json.dumps({k:item.get(k) for k in ['DOI','title','author','published','URL','is-referenced-by-count']},ensure_ascii=True))
    return 0 if items else 2

if __name__=='__main__':
    try: raise SystemExit(main())
    except requests.RequestException as exc:
        print(json.dumps({'status':'failed','error_type':type(exc).__name__}),file=sys.stderr)
        raise SystemExit(1)
