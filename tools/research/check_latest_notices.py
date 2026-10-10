"""Bounded fresh notice checks; reports access and discovery separately."""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin
import re
from bs4 import BeautifulSoup
import build_unit_dossiers as d
import refresh_dossier_sources as r
import collect_gap_round2 as b
from recover_gap_tls import verified_curl

BASE=d.WORK
BATCH=d.ROOT/'.research/news-check-20261004'
OVERRIDES={
 '北京邮电大学':'https://yzb.bupt.edu.cn/',
 '南方科技大学':'https://cse.sustech.edu.cn/graduate/graduate-admissions/masters/?page=1',
 '华中科技大学':'https://gszs.hust.edu.cn/?s=107',
 '浙江大学':'https://www.grs.zju.edu.cn/yjszs/28480/list.htm',
 '中国科学技术大学':'https://yz.ustc.edu.cn/column/176?num=-1',
 '南京航空航天大学':'https://www.graduate.nuaa.edu.cn/13541/list.htm',
 '中国科学院深圳先进技术研究院':'https://www.siat.ac.cn/jyjx/zsxx/sszs/',
}

def run(batch=None, as_of=None, max_sources=300, corpus_path=None, all_units=False):
    global BATCH
    if batch is not None:BATCH=batch
    if as_of is None:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        as_of=datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()
    corpus={u['name']:u for u in d.read(corpus_path or d.ROOT/'.research/manual-downloads/全量采集资料.json')['units']}
    old=d.read(BASE/'live-sources.json');known={(x['unit'],x['url']):x for x in old}
    prior_discovery={(x['unit'],x['url']):x for x in d.read(BATCH/'notice-links.json',[])}
    tasks={};results={};notice_links=[]
    def add(name,url,title,year=None,origin=None):
        u=corpus[name]
        if r.allowed(url,u):tasks[(name,url)]=dict(unit=name,unit_info=u,url=url,title=title,year=year,discovered_on=origin)
    selected=[dict(name=name) for name in corpus] if all_units else d.priority.load()
    for p in selected:
        name=p['name'];u=corpus[name];url=OVERRIDES.get(name,u['portal'])
        if url:add(name,url,name+'当前研招公告入口')
        recent=[x for x in old if x['unit']==name and x.get('year')==2027 and x.get('status') in ('html-saved','file-saved')]
        for x in recent[-2:]:add(name,x['url'],x['title'],2027)
    if all_units:
        # The home page may no longer link last year's lists. Recheck known
        # original URLs by year and document role, without equating retrieval
        # with table verification. Portals for all units were queued first.
        for year in (2027,2026,2025):
            patterns = [r'专业目录|招生简章|招生章程|考试科目|招生计划'] if year==2027 else [r'分数线|复试.*(?:细则|办法|方案)',r'拟录取|录取名单|录取.*公示']
            for p in selected:
                name=p['name'];u=corpus[name]
                documents=[x for x in d.docs_for(u) if x.get('year')==year and x.get('source_tier')=='primary' and r.allowed(x['url'],u) and d.source_score(x,u,year)>0]
                for pattern in patterns:
                    matches=sorted((x for x in documents if re.search(pattern,x['title'])),key=lambda x:d.source_score(x,u,year),reverse=True)
                    for x in matches[:2 if year==2027 else 1]:add(name,x['url'],x['title'],year,'known-original-url')
    for t in d.read(BATCH/'observed-tasks.json',[]):add(t['unit'],t['url'],t['title'],t.get('year'),t.get('discovered_on'))
    add('北京交通大学','https://yzb.bjtu.edu.cn/tzgg/5f9b7b7e45ae494189f586f1a383ca62.htm','北京交通大学2027年硕士研究生招生简章',2027,'search48.json')
    add('中国科学技术大学','https://iatyz.ustc.edu.cn/','先进技术研究院2027统招专业领域入口',2027,'search49.json')
    d.WORK=BATCH
    def fetch(t):
        x=r.fetch(t)
        if 'SSLError' in x.get('error',''):x=verified_curl(t)
        x['source_tier']='primary';return x
    try:
        for depth in range(3):
            current=[x for k,x in tasks.items() if k not in results][:max(0,max_sources-len(results))]
            if not current:break
            with ThreadPoolExecutor(4) as pool:
                for n,f in enumerate(as_completed([pool.submit(fetch,t) for t in current]),1):
                    x=f.result();results[(x['unit'],x['url'])]=x
                    if n%15==0:print(dict(depth=depth,done=n,total=len(current)),flush=True)
            d.dump(BATCH/'sources.json',list(results.values()))
            if depth==0:
                for x in list(results.values()):
                    if x.get('status')!='html-saved':continue
                    soup=BeautifulSoup(b.e.rawhtml(x),'html.parser');new=[]
                    for a in soup.select('a[href]'):
                        label=a.get_text(' ',strip=True) or a.get('title','')
                        if not re.search(r'202[567]',label) or not re.search(r'硕士|专业目录|招生计划|考试科目|复试|拟录取|成绩',label) or re.search(r'推免|免试|博士|夏令营|网络课程',label):continue
                        url=urljoin(x.get('final_url') or x['url'],a['href'])
                        if not r.allowed(url,corpus[x['unit']]):continue
                        key=(x['unit'],url);prior=known.get(key)
                        new.append((url,label))
                        item=dict(unit=x['unit'],url=url,title=label,observed_on=x['url'],previously_observed=bool(prior),previous_sha256=prior.get('sha256') if prior else None)
                        if key in prior_discovery:
                            item.update({k:prior_discovery[key][k] for k in ('previously_observed','previous_sha256')})
                        if not any(z['unit']==item['unit'] and z['url']==url for z in notice_links):notice_links.append(item)
                    for url,title in list(dict.fromkeys(new))[:3]:add(x['unit'],url,title,int(re.search(r'202[567]',title).group()),x['url'])
            elif depth==1:
                for x in list(results.values()):
                    for t in b.follow(x,corpus[x['unit']]):
                        if t.get('year') in (2025,2026,2027) and not re.search(r'博士|推免|推荐免试',t['title']):tasks.setdefault((t['unit'],t['url']),t)
        d.dump(BATCH/'notice-links.json',notice_links)
    finally:d.WORK=BASE
    changes=[]
    for key,x in results.items():
        if x.get('status') in ('html-saved','file-saved') or key not in known:
            prior=known.get(key)
            if x.get('sha256') and x.get('status') in ('html-saved','file-saved') and (not prior or prior.get('sha256')!=x['sha256']):
                changes.append(dict(unit=x['unit'],url=x['url'],title=x['title'],year=x.get('year'),sha256=x['sha256'],previous_sha256=prior.get('sha256') if prior else None,status='needs-content-review'))
            if prior and prior.get('sha256')==x.get('sha256') and re.fullmatch(r'(?:点击下载|下载|附件\d*|\.[a-zA-Z]+)',x.get('title','')):
                x=dict(x,observed_link_label=x['title'],title=prior['title'])
            known[key]=x
    d.dump(BASE/'live-sources.json',list(known.values()))
    d.dump(BATCH/'changes.json',changes)
    report=dict(as_of=as_of,units_attempted=len({x['unit'] for x in results.values()}),source_checks=len(results),states=dict(Counter(x['status'] for x in results.values())),changed_documents=len(changes),notice_links=len(notice_links),previously_unobserved_links=sum(not x['previously_observed'] for x in notice_links),limitation='新增发现不等于刚发布；内容变化需核对正文，失败不等于未公布。')
    d.dump(BATCH/'summary.json',report);print(report)
    return report

if __name__=='__main__':run()
