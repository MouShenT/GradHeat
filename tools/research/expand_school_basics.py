"""Bounded official-source retrieval and immutable import of reviewed basics."""
import argparse
from datetime import datetime,timezone
import hashlib,json,re,sys,time
from pathlib import Path
from urllib.parse import urlsplit

import requests
from bs4 import BeautifulSoup

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'python_service'));sys.path.insert(0,str(ROOT/'crawler'))
from gradheat_python import bootstrap
from gradheat_core.intelligence import canonical
from run_daily_update import local_lock


def retrieve(rows,output):
    output=Path(output).resolve()
    if not output.is_relative_to((ROOT/'.research').resolve()): raise ValueError('Real originals must stay in .research')
    output.mkdir(parents=True,exist_ok=True)
    manifest=[]
    for row in rows:
        url=row['url'];parsed=urlsplit(url)
        if parsed.scheme not in {'http','https'} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError('Explicit public URLs required')
        item=dict(row,observed_at=datetime.now(timezone.utc).isoformat())
        try:
            response=requests.get(url,timeout=(8,25),headers={'User-Agent':'GradHeat public admissions research'},stream=True)
            response.raise_for_status();body=b''
            for chunk in response.iter_content(65536):
                body+=chunk
                if len(body)>20_000_000: raise ValueError('Original exceeds source budget')
            sha=hashlib.sha256(body).hexdigest()
            suffix='.pdf' if body.startswith(b'%PDF') else '.png' if body.startswith(b'\x89PNG\r\n') else '.jpg' if body.startswith(b'\xff\xd8\xff') else '.html'
            path=output/(sha+suffix);path.write_bytes(body)
            item.update(source_url=response.url,source_artifact=str(path),source_sha256=sha,state='retained')
            if suffix=='.html':
                soup=BeautifulSoup(body,'html.parser')
                for tag in soup(['script','style','nav','footer']): tag.decompose()
                content=soup.get_text('\n',strip=True)
                tables=[[[c.get_text(' ',strip=True) for c in tr.find_all(['th','td'])] for tr in t.find_all('tr')] for t in soup.find_all('table')]
                links=[dict(text=a.get_text(' ',strip=True),href=a.get('href')) for a in soup.find_all('a',href=True)
                       if re.search(r'\.pdf(?:\?|$)|分数线|复试|计划',a.get('href','')+' '+a.get_text())]
                parsed_content=dict(title=soup.title.get_text() if soup.title else '',text=content,tables=tables,links=links)
            elif suffix=='.pdf':
                import pymupdf
                with pymupdf.open(path) as pdf:
                    parsed_content=dict(text='\n'.join(p.get_text() for p in pdf),pages=len(pdf),tables=[])
            else:
                parsed_content=dict(text='',tables=[],requires_visual_review=True)
            (output/(sha+'-extracted.json')).write_text(canonical(parsed_content),encoding='utf-8')
            item['extracted_path']=str(output/(sha+'-extracted.json'))
        except Exception as error:
            item.update(state='unavailable-at-check',error_type=type(error).__name__)
        manifest.append(item)
        (output/'manifest.json').write_text(canonical(manifest),encoding='utf-8')
        print(canonical(dict(unit=row['unit'],state=item['state'])),flush=True)
        time.sleep(1)
    return manifest


def main():
    p=argparse.ArgumentParser();p.add_argument('--sources',type=Path);p.add_argument('--facts',type=Path)
    p.add_argument('--output',type=Path,default=ROOT/'.research/index-expansion/official')
    p.add_argument('--wait-for-lock',action='store_true');args=p.parse_args()
    if not args.sources and not args.facts: p.error('Provide sources or reviewed facts')
    with local_lock(wait=args.wait_for_lock):
        if args.sources:
            rows=json.loads(args.sources.read_text(encoding='utf-8-sig'))
            if len(rows)>60: raise ValueError('At most 60 explicit official originals per run')
            retrieve(rows,args.output)
        if args.facts:
            from refresh_school_intelligence import rebuild
            print(canonical(rebuild(facts=args.facts)))


if __name__=='__main__': main()
