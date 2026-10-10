"""Bounded source recovery for the current gap list; never infers nonpublication."""
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from bs4 import BeautifulSoup
import build_unit_dossiers as d
import refresh_dossier_sources as r
import extract_dossier_evidence as e

BASE=d.WORK
BATCH=d.ROOT/'.research/supplement-20261003'

def tasks():
    corpus={u['name']:u for u in d.read(d.ROOT/'.research/manual-downloads/全量采集资料.json')['units']}
    missing=d.read(BASE/'missing-fields.json',[])
    names={m['unit'] for m in missing}
    output={}
    def add(u,url,title,year=None,origin=None):
        if not r.allowed(url,u) or d.BLOCK.search(title):return
        output[(u['name'],url)]=dict(unit=u['name'],unit_info=u,url=url,title=title,year=year,discovered_on=origin)
    for name in names:
        u=corpus[name]
        if any(m['unit']==name and m['year']==2027 for m in missing):
            add(u,u.get('portal') or u.get('chsi'),name+'官方招生入口')
            candidates=sorted([x for x in d.docs_for(u) if x['year']==2027 and x.get('source_tier')=='primary' and not d.BLOCK.search(x['title'])],key=lambda x:d.source_score(x,u,2027),reverse=True)
            for x in [c for c in candidates if re.search(r'专业目录|招生章程|招生简章|招生目录',c['title'])][:2]:add(u,x['url'],x['title'],2027)
        for year in (2026,2025):
            if not any(m['unit']==name and m['year']==year for m in missing):continue
            candidates=sorted([x for x in d.docs_for(u) if x['year']==year and x.get('source_tier')=='primary' and not d.BLOCK.search(x['title']) and re.search(r'拟录取|录取名单|分数线',x['title'])],key=lambda x:d.source_score(x,u,year),reverse=True)
            for x in candidates[:2]:add(u,x['url'],x['title'],year)
    for file in sorted((BASE/'search').glob('search*.json')):
        n=re.search(r'search(\d+)',file.name)
        if not n or int(n[1])<24:continue
        x=d.read(file,{});result=x.get('result','')
        if not isinstance(result,str):continue
        for title,url in re.findall(r'^([^\n]+?) \((https?://[^)\s]+)\)\n[^\n]*cite',result,re.M):
            if not re.search(r'硕士|专业目录|研究生招生|招考信息|招生信息',title):continue
            explicit=re.findall(r'(?<!\d)(202[567])\s*年',title)
            for name in x.get('units',[]):
                u=corpus[name]
                if r.allowed(url,u):add(u,url,title,int(explicit[0]) if explicit else None,str(file))
    for t in d.read(BATCH/'observed-tasks.json',[]):
        add(corpus[t['unit']],t['url'],t['title'],t.get('year'),t.get('discovered_on'))
    return corpus,output

def follow(result,u):
    if result.get('status')!='html-saved':return []
    html=e.rawhtml(result)
    if not html:return []
    soup=BeautifulSoup(html,'html.parser')
    main=soup.select_one('.v_news_content, #vsb_content, .TRS_Editor, .wp_articlecontent, article, main') or soup.body or soup
    title=result.get('live_title') or result['title']
    if not re.search(r'目录|拟录取|分数线|章程|简章',title):title=result['title']
    year=result.get('year')
    annual=year in (2027,2026,2025) and re.search(r'目录|拟录取|录取名单|分数线|招生章程|招生简章',title)
    output=[]
    for a in main.select('a[href], iframe[src], iframe[data-src], embed[src], object[data]'):
        href=a.get('href') or a.get('data-src') or a.get('src') or a.get('data')
        if not href or href.startswith(('javascript:','mailto:','#')):continue
        url=urljoin(result.get('final_url') or result['url'],href)
        label=a.get_text(' ',strip=True) or a.get('title','')
        explicit=re.findall(r'(?<!\d)(20\d{2})\s*年',label)
        attachment=bool(re.search(r'\.(?:pdf|xlsx?|docx?)(?:$|[?])|DownloadAttachUrl',url,re.I))
        relevant=bool(re.search(r'硕士|招生.*目录|招生.*计划|专业目录|拟录取|分数线',label))
        if d.BLOCK.search(label) or not r.allowed(url,u):continue
        if not ((explicit and relevant) or (annual and (attachment or re.search(r'目录|名单|分数线|点击下载|点击查看',label)))):continue
        y=int(explicit[0]) if explicit else year
        output.append(dict(unit=u['name'],unit_info=u,url=url,title=label or result['title']+'（原页附件）',year=y,discovered_on=result['url']))
    return output[:14]

def run():
    corpus,queue=tasks()
    d.dump(BATCH/'tasks.json',[{k:v for k,v in x.items() if k!='unit_info'} for x in queue.values()])
    previous=d.read(BATCH/'sources.json',[])
    results={(x['unit'],x['url']):x for x in previous}
    for rec in list(results.values()):
        for task in follow(rec,corpus[rec['unit']]):
            queue.setdefault((task['unit'],task['url']),task)
    # This process uses a new immutable fetch cache, without changing old runs.
    d.WORK=BATCH
    for depth in range(3):
        current=[x for key,x in queue.items() if key not in results]
        if not current:break
        with ThreadPoolExecutor(5) as pool:
            futures={pool.submit(r.fetch,t):t for t in current}
            for i,f in enumerate(as_completed(futures),1):
                rec=f.result()
                body=d.textfile(rec.get('text_path'))
                if rec.get('status')=='html-saved' and len(body.strip())<100 and re.search(r'验证码|安全验证|Access Denied|enable JavaScript',body,re.I):
                    rec.update(status='verification-page',retained=False)
                live=rec.get('live_title','')
                years=re.findall(r'(?<!\d)(202[567])\s*年',live)
                if len(set(years))==1:rec['year']=int(years[0])
                if rec.get('year') is None and rec.get('status')=='file-saved':
                    heading=body[:400];m=re.search(r'(202[567])\s*年',heading)
                    if m:rec['year']=int(m[1])
                rec['source_tier']='primary'
                results[(rec['unit'],rec['url'])]=rec
                if i%15==0:print({'depth':depth,'done':i,'batch':len(current)},flush=True)
        d.dump(BATCH/'sources.json',list(results.values()))
        if depth<2:
            new={}
            for rec in list(results.values()):
                for t in follow(rec,corpus[rec['unit']]):
                    if (t['unit'],t['url']) not in results:new[(t['unit'],t['url'])]=t
            queue.update(new)
    d.WORK=BASE
    old=d.read(BASE/'live-sources.json',[])
    merged={(x['unit'],x['url']):x for x in old}
    for key,x in results.items():
        prior=merged.get(key)
        if x.get('status') in ('html-saved','file-saved') or prior is None:merged[key]=x
    d.dump(BASE/'live-sources.json',list(merged.values()))
    print({'sources':len(results),'units':len({x['unit'] for x in results.values()}),'states':dict(Counter(x['status'] for x in results.values()))},flush=True)

if __name__=='__main__':run()
