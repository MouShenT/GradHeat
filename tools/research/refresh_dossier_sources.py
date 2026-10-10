"""Bounded live verification of public source links, with immutable local versions."""
from __future__ import annotations
import hashlib
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit, unquote
import requests
from bs4 import BeautifulSoup
import build_unit_dossiers as d
import build_download_index as base

LOCKS={};GUARD=threading.Lock()
ALIASES={'中国科学院计算技术研究所':['ict.cas.cn'],'中国科学院软件研究所':['is.cas.cn'],'中国科学院信息工程研究所':['iie.cas.cn'],'中国科学院空天信息创新研究院':['aircas.cas.cn'],'中国科学院深圳先进技术研究院':['siat.cas.cn'], '西北农林科技大学':['nwsuaf.edu.cn'], '中国科学院沈阳自动化研究所':['sia.ac.cn','sia.cas.cn'], '中国科学院上海微系统与信息技术研究所':['sim.ac.cn']}

def allowed(url,u):
    host=urlsplit(url).hostname or ''
    if host.endswith('chsi.com.cn') and '/sch/' in url:
        own=re.search(r'schId-(\d+)',unquote(u.get('portal') or u.get('chsi') or ''))
        other=re.search(r'schId-(\d+)',unquote(url))
        if own and other and own.group(1)!=other.group(1):return False
    domains=[u['domain']]+u.get('official_domains',[])+ALIASES.get(u['name'],[])
    if u['group']=='研究所':domains+=['ucas.ac.cn']
    return any(host==x or host.endswith('.'+x) for x in domains)

def fetch(task):
    unit=task['unit'];url=task['url'];key=hashlib.sha256((unit+'\n'+url).encode()).hexdigest()
    meta=d.WORK/'live-meta'/(key+'.json')
    if meta.exists():return d.classify_retained_source(d.read(meta))
    result=dict(task,retrieved_at=datetime.now(timezone.utc).isoformat(),status='fetch-failed')
    try:
        host=urlsplit(url).hostname
        with GUARD:lock=LOCKS.setdefault(host,threading.Lock())
        with lock:
            time.sleep(0.8)
            with requests.get(url,headers={'User-Agent':'Mozilla/5.0'},timeout=(5,16),stream=True) as r:
                result.update(http_status=r.status_code,final_url=r.url,content_type=r.headers.get('Content-Type',''))
                if r.status_code!=200:result['status']='http-error'
                elif not allowed(r.url,task['unit_info']):result['status']='redirect-out-of-scope'
                else:
                    data=bytearray()
                    for chunk in r.iter_content(65536):
                        data.extend(chunk)
                        if len(data)>15_000_000:break
                    if len(data)>15_000_000:result['status']='size-limit'
                    else:
                        data=bytes(data);sha=hashlib.sha256(data).hexdigest();ext='.pdf' if data.startswith(b'%PDF') else '.html' if 'html' in result['content_type'].lower() else '.bin'
                        path=d.WORK/'live-raw'/(key+'-'+sha[:12]+ext);path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
                        result.update(raw_path=str(path),sha256=sha,bytes=len(data),retained=True,status='html-saved' if ext=='.html' else 'file-saved')
                        if ext=='.html':
                            soup=BeautifulSoup(base.decode_html(data),'html.parser')
                            title=soup.title.get_text(' ',strip=True) if soup.title else ''
                            result['live_title']=title
                            redirect=re.search(r'location\.(?:replace|assign)\(\s*[\'\"]([^\'\"]+)[\'\"]\s*\)',str(soup))
                            body=soup.body.get_text(' ',strip=True) if soup.body else ''
                            if redirect and not body:
                                result.update(status='javascript-redirect',retained=False,content_readable=False,
                                    observed_redirect=urljoin(r.url,redirect.group(1)))
                            elif re.search(r'验证码|安全验证|访问太频繁|Access Denied',title,re.I):result['status']='verification-page';result['retained']=False
                            elif re.search(r'WebVPN',title,re.I) or 'WebVPN 浏览器兼容性提示' in soup.get_text(' ',strip=True):result['status']='access-gateway';result['retained']=False
                            elif re.search(r'\.pdf(?:$|\?)',url,re.I):result['status']='unexpected-html';result['retained']=False
                            else:
                                main=soup.select_one('.v_news_content, #vsb_content, .TRS_Editor, .wp_articlecontent, article, main') or soup.body or soup
                                txt=main.get_text('\n',strip=True);tp=path.with_suffix('.txt');tp.write_text(txt,encoding='utf-8');result['text_path']=str(tp)
                                links=[]
                                for a in main.select('a[href]'):
                                    try:v=urljoin(r.url,a['href'])
                                    except ValueError:continue
                                    label=a.get_text(' ',strip=True)
                                    if not allowed(v,task['unit_info']):continue
                                    explicit=re.findall(r'(?<!\d)(20\d{2})\s*年',label)
                                    sameyear='2027' in label or (not explicit and task.get('year')==2027 and re.search(r'招生.*目录|招生.*计划|专业目录',label))
                                    history=re.search(r'202[56].*(?:硕士|计算机|软件|人工智能).*(?:录取|成绩|分数)',label)
                                    if (sameyear or history) and not d.BLOCK.search(label):
                                        links.append(dict(unit=unit,url=v,title=label or task['title']+'（原页附件）',year=int(explicit[0]) if explicit else 2027 if sameyear else int(re.search(r'202[56]',label).group()),unit_info=task['unit_info'],discovered_on=r.url))
                                result['follow_links']=links[:8]
                        elif ext=='.pdf':
                            import pymupdf
                            with pymupdf.open(path) as pdf:
                                txt='\n'.join(p.get_text() for p in pdf);result['pages']=len(pdf)
                            tp=path.with_suffix('.txt');tp.write_text(txt,encoding='utf-8');result['text_path']=str(tp)
    except Exception as e:result['error']=type(e).__name__+': '+str(e)[:150]
    result.pop('unit_info',None)
    # Follow tasks carry unit_info only in memory. Embedding the entire school
    # corpus in each metadata record duplicated hundreds of megabytes.
    for follow in result.get('follow_links',[]):follow.pop('unit_info',None)
    result=d.classify_retained_source(result)
    d.dump(meta,result);return result

def run():
    corpus={u['name']:u for u in d.read(d.ROOT/'.research/manual-downloads/全量采集资料.json')['units']}
    tasks={}
    for entry in d.priority.load():
        u=corpus[entry['name']];candidates=[]
        for f in (d.WORK/'search').glob('*.json'):
            x=d.read(f,{});r=x.get('result','');r=r.get('value','') if isinstance(r,dict) else r
            for title,url in re.findall(r'^([^\n]+?) \((https?://[^)\s]+)\)\n[^\n]*cite',r,re.M):
                if not allowed(url,u) or d.BLOCK.search(title):continue
                if re.search(r'就业|招聘|faculty|career|job\.|师资|导师|本科',title+' '+url,re.I):continue
                if not re.search(r'硕士|研究生招生|研究生.*目录|初试科目',title):continue
                years=re.findall(r'202[567]',title);year=int(years[0]) if years else 2027
                candidates.append(dict(unit=u['name'],unit_info=u,url=url,title=title,year=year,discovery_file=str(f)))
        existing=sorted((x for x in d.docs_for(u) if x['year']==2027 and x.get('source_tier')=='primary' and not d.BLOCK.search(x['title'])),key=lambda x:d.source_score(x,u,2027),reverse=True)
        for x in existing[:3]:
            candidates.append(dict(unit=u['name'],unit_info=u,url=x['url'],title=x['title'],year=2027))
        # One compact live pass per unit; the baseline retains the wider source set.
        for t in candidates[:6]:tasks[(u['name'],t['url'])]=t
    d.dump(d.WORK/'live-tasks.json',list(tasks.values()))
    results=[]
    def batch(ts):
        with ThreadPoolExecutor(4) as pool:
            for n,f in enumerate(as_completed([pool.submit(fetch,t) for t in ts]),1):
                results.append(f.result())
                if n%20==0:print(json.dumps({'done':n,'batch':len(ts),'states':dict(__import__('collections').Counter(x['status'] for x in results))},ensure_ascii=False),flush=True)
        d.dump(d.WORK/'live-sources.json',results)
    batch(list(tasks.values()))
    follow={}
    for r in results:
        for t in r.get('follow_links',[]):
            t=dict(t,unit_info=corpus[t['unit']])
            if (t['unit'],t['url']) not in tasks:follow[(t['unit'],t['url'])]=t
    batch(list(follow.values()))
    print(json.dumps({'total':len(results),'units':len(set(x['unit'] for x in results)),'states':dict(__import__('collections').Counter(x['status'] for x in results))},ensure_ascii=False),flush=True)

if __name__=='__main__':run()
