"""Recover observed official URLs and their actual attachments for open gaps."""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
import re
from urllib.parse import urljoin
from bs4 import BeautifulSoup
import build_unit_dossiers as d
import refresh_dossier_sources as r
import supplement_missing_sources as s
import extract_dossier_evidence as e

BASE=d.WORK
BATCH=d.ROOT/'.research/gap-round2-20261003'

def follow(doc,unit):
 tasks=s.follow(doc,unit)
 if doc.get('status')!='html-saved':return tasks
 soup=BeautifulSoup(e.rawhtml(doc),'html.parser')
 for a in soup.select('[pdfsrc]'):
  url=urljoin(doc.get('final_url') or doc['url'],a['pdfsrc'])
  if r.allowed(url,unit):tasks.append(dict(unit=unit['name'],unit_info=unit,url=url,title=doc['title']+'（PDF播放器原件）',year=doc.get('year'),discovered_on=doc['url']))
 return tasks

def run():
 corpus={u['name']:u for u in d.read(d.ROOT/'.research/manual-downloads/全量采集资料.json')['units']}
 old=d.read(BASE/'live-sources.json',[]);queue={};sources={}
 def add(unit,url,title,year=None,origin=None):
  u=corpus[unit]
  if r.allowed(url,u) and not d.BLOCK.search(title):queue[(unit,url)]=dict(unit=unit,unit_info=u,url=url,title=title,year=year,discovered_on=origin)
 for file in sorted((BASE/'search').glob('search*.json')):
  number=re.search(r'search(\d+)',file.name)
  if not number or int(number[1])<38:continue
  result=d.read(file)
  for title,url in re.findall(r'^([^\n]+?) \((https?://[^)\s]+)\)\n[^\n]*cite',result['result'],re.M):
   if re.search(r'博士|夏令营|直博|推免|推荐免试|导师|暑期|招聘',title):continue
   if not re.search(r'硕士|专业目录|复试|拟录取|招生信息|研究生招生|研究生院|招考信息|^招生$',title):continue
   year=re.search(r'202[567]',title)
   for unit in result['units']:add(unit,url,title,int(year[0]) if year else None,str(file))
 # Public, already-observed pages can have PDF players outside their body text.
 for doc in old:
  if doc['unit'] in ['南京邮电大学','北京科技大学','南京航空航天大学','同济大学','西北农林科技大学'] and doc.get('year') in [2025,2026,2027]:
   for task in follow(doc,corpus[doc['unit']]):queue.setdefault((task['unit'],task['url']),task)
 for t in d.read(BATCH/'observed-tasks.json',[]):add(t['unit'],t['url'],t['title'],t.get('year'),t.get('discovered_on'))
 # Keep a reproducible baseline before altering current derived metadata.
 for name in ['live-sources.json','missing-fields.json','summary.json','admission-statistics-candidates.json','supplement-catalogue-rows.json']:
  p=BATCH/'baseline'/name
  if not p.exists():d.dump(p,d.read(BASE/name))
 d.dump(BATCH/'tasks.json',[{k:v for k,v in t.items() if k!='unit_info'} for t in queue.values()])
 d.WORK=BATCH
 for depth in range(3):
  current=[t for key,t in queue.items() if key not in sources]
  if not current:break
  with ThreadPoolExecutor(4) as pool:
   for i,future in enumerate(as_completed([pool.submit(r.fetch,t) for t in current]),1):
    doc=future.result();doc['source_tier']='primary'
    body=d.textfile(doc.get('text_path'))
    if doc.get('year') is None:
     years=re.findall(r'(?<!\d)(202[567])\s*年',doc.get('live_title',''))
     if len(set(years))==1:doc['year']=int(years[0])
    sources[(doc['unit'],doc['url'])]=doc
    if i%10==0:print(dict(depth=depth,done=i,total=len(current)),flush=True)
  d.dump(BATCH/'sources.json',list(sources.values()))
  if depth<2:
   for doc in list(sources.values()):
    for task in follow(doc,corpus[doc['unit']]):queue.setdefault((task['unit'],task['url']),task)
 d.WORK=BASE
 # Historical source observations and raw bytes remain in their batch caches.
 merged={(x['unit'],x['url']):x for x in old}
 for key,x in sources.items():
  if x.get('status') in ('html-saved','file-saved') or key not in merged:merged[key]=x
 d.dump(BASE/'live-sources.json',list(merged.values()))
 print(dict(sources=len(sources),units=len({x['unit'] for x in sources.values()}),states=dict(Counter(x['status'] for x in sources.values()))),flush=True)

if __name__=='__main__':run()
