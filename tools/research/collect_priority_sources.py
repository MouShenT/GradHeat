"""Collect public admissions sources for the prioritized university/institute batch.

Reuse retained evidence, search only official domains, follow literal source links,
and keep field eligibility separate from document availability.
"""
from __future__ import annotations
import argparse
import hashlib
import html
import json
import re
import subprocess
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urljoin, urlsplit, quote

import requests
from bs4 import BeautifulSoup
import build_download_index as base
import refine_download_resources as refine

ROOT = base.ROOT
WORK = ROOT / '.research/priority-20260930'
OUT = base.DOWNLOADS
MOE = 'https://www.moe.gov.cn/srcsite/A22/s7065/200612/t20061206_128833.html'
UCAS = 'https://admission.ucas.ac.cn/info/ZhaoshengDanwei/9e780c52-baf5-4020-b453-bc4510579559'
N985 = '北京大学 中国人民大学 清华大学 北京航空航天大学 北京理工大学 中国农业大学 北京师范大学 中央民族大学 南开大学 天津大学 大连理工大学 东北大学 吉林大学 哈尔滨工业大学 复旦大学 同济大学 上海交通大学 华东师范大学 南京大学 东南大学 浙江大学 中国科学技术大学 厦门大学 山东大学 中国海洋大学 武汉大学 华中科技大学 湖南大学 中南大学 国防科技大学 中山大学 华南理工大学 四川大学 电子科技大学 重庆大学 西安交通大学 西北工业大学 西北农林科技大学 兰州大学'.split()
STRONG = '北京邮电大学 北京交通大学 北京工业大学 北京科技大学 西安电子科技大学 哈尔滨工程大学 南京航空航天大学 南京理工大学 杭州电子科技大学 合肥工业大学 西南交通大学 重庆邮电大学 南京邮电大学 上海大学 深圳大学 南方科技大学 上海科技大学 中国科学院大学 华中师范大学'.split()
EXTRA = {
    '杭州电子科技大学': ('hdu.edu.cn', 'https://grs.hdu.edu.cn/13497/list.htm'),
    '重庆邮电大学': ('cqupt.edu.cn', 'https://yjs.cqupt.edu.cn/'),
    '深圳大学': ('szu.edu.cn', 'https://yz.szu.edu.cn/sszs/jzml.htm'),
}
INSTITUTES = [
    ('中国科学院计算技术研究所','ict.ac.cn','https://www.ict.ac.cn/yjsjy/zsxx/sszs/','计算技术研究所'),
    ('中国科学院软件研究所','iscas.ac.cn','https://www.iscas.ac.cn/yjsjy/zsxx/index.html','软件研究所'),
    ('中国科学院信息工程研究所','iie.ac.cn','https://www.iie.ac.cn/xsjy/zxtz/','信息工程研究所'),
    ('中国科学院自动化研究所','ia.cas.cn','https://ia.cas.cn/yjsjy/zs/sszs/index.html','自动化研究所'),
    ('中国科学院深圳先进技术研究院','siat.ac.cn','https://www.siat.ac.cn/jyjx/zsxx/sszs/','深圳先进技术研究院'),
    ('中国科学院计算机网络信息中心','cnic.cas.cn','https://cnic.cas.cn/yjsjy/tzgg/','计算机网络信息中心'),
    ('中国科学院空天信息创新研究院','aircas.ac.cn','https://aircas.ac.cn/kjrh/rhtzgg/','空天信息创新研究院'),
    ('中国科学院上海微系统与信息技术研究所','sim.cas.cn','https://sim.cas.cn/yjs/zsxx/yjs_sszs/','上海微系统与信息技术研究所'),
    ('中国科学院沈阳自动化研究所','sia.cas.cn','https://sia.cas.cn/','沈阳自动化研究所'),
    ('西安微电子技术研究所','yz.chsi.com.cn','https://yz.chsi.com.cn/sch/schoolInfo--schId-368539.dhtml',None),
]
locks, guard = {}, threading.Lock()


def dump(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def allowed(url, row):
    domains = [row['domain']]
    if row['group'] == '研究所': domains.append('ucas.ac.cn')
    return any(base.within_domain(url, d) for d in domains)


def capture(url, row):
    key = hashlib.sha256(url.encode()).hexdigest()
    meta = WORK / 'pages' / (key+'.json')
    raw = meta.with_suffix('.html')
    if meta.exists():
        m = json.loads(meta.read_text(encoding='utf-8'))
        artifact = raw if raw.exists() else Path(m['artifact']) if m.get('artifact') else None
        return m, BeautifulSoup(base.decode_html(artifact.read_bytes()),'html.parser') if artifact and artifact.exists() else None
    host = urlsplit(url).hostname
    with guard: lock = locks.setdefault(host, threading.Lock())
    m = dict(url=url, checked_at=base.NOW(), status='fetch-failed')
    try:
        with lock:
            time.sleep(1)
            with requests.get(url, timeout=(5,18), headers={'User-Agent':'Mozilla/5.0'},stream=True) as r:
                m.update(http_status=r.status_code, final_url=r.url, content_type=r.headers.get('Content-Type',''))
                if r.status_code!=200: m['status']='http-error'
                elif not allowed(r.url,row): m['status']='redirect-domain-needs-review'
                elif 'html' not in m['content_type'].lower(): m['status']='non-html'
                else:
                    data=bytearray()
                    for chunk in r.iter_content(32768):
                        data.extend(chunk)
                        if len(data)>2_000_000: break
                    raw.parent.mkdir(parents=True,exist_ok=True);raw.write_bytes(data)
                    soup=BeautifulSoup(base.decode_html(bytes(data)),'html.parser')
                    title=soup.title.get_text(' ',strip=True) if soup.title else ''
                    m.update(status='html-saved',page_title=title,sha256=hashlib.sha256(data).hexdigest(),artifact=str(raw),truncated=len(data)>2_000_000)
                    dump(meta,m);return m,soup
    except requests.RequestException as e: m['error']=type(e).__name__
    dump(meta,m);return m,None


def initialize():
    existing=json.loads((OUT/'逐项资源核验.json').read_text(encoding='utf-8'))['schools']
    lookup={s['name']:s for s in existing};rows=[]
    for name in N985+STRONG:
        if name in lookup:
            row=lookup[name].copy();row.pop('slots',None)
            row['key']=row['sch_id']
        else:
            domain,portal=EXTRA[name]
            row=dict(name=name,key=hashlib.sha256(name.encode()).hexdigest()[:12],domain=domain,portal=portal,documents=[],eligibility='2027年11408待核验',folder=str(OUT/name))
        row.update(group='985' if name in N985 else '计算机相关强校候选',basis=MOE if name in N985 else '第四轮计算机学科评估及相关学科建设作为发现依据；扩展候选单独标记，非当前实力排名')
        rows.append(row)
    for name,domain,portal,ucas_name in INSTITUTES:
        rows.append(dict(name=name,key=hashlib.sha256(name.encode()).hexdigest()[:12],domain=domain,portal=portal,ucas_name=ucas_name,documents=[],group='研究所',basis='计算机、软件、网络安全、人工智能及信息技术相关培养单位候选；培养资格与11408待核验',eligibility='2027年11408待核验',folder=str(OUT/name)))
    for row in rows:
        for year in (2024,2025,2026,2027):
            for category in base.CATEGORIES: (Path(row['folder'])/str(year)/category).mkdir(parents=True,exist_ok=True)
        (Path(row['folder'])/'助手整理网页').mkdir(exist_ok=True)
    dump(WORK/'manifest.json',dict(at=base.NOW(),scope='39所985+19所计算机相关非985候选+10个研究所，优先批次，非全国全部11408',rows=rows))
    print(json.dumps(Counter(r['group'] for r in rows),ensure_ascii=False),flush=True)


def load(): return json.loads((WORK/'manifest.json').read_text(encoding='utf-8'))['rows']


def search():
    if (WORK/'search-service-stop.json').exists():
        print('Search service is paused after a recorded quota/rate error; inspect the record before retrying.', flush=True)
        return
    stop=threading.Event()
    def one(row):
        path=WORK/'search'/(row['key']+'.json')
        if path.exists(): return 'cached'
        if stop.is_set(): return 'quota-stop'
        query=f"site:{row['domain']} 2027 硕士 招生 专业目录 -推免 -博士 -港澳台"
        cmd=['powershell','-NoProfile','-File',str(ROOT/'tools/research/firecrawl.ps1'),'search',query,'--limit','6','--timeout','20000','--json','-o',str(path)]
        try:
            p=subprocess.run(cmd,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=40)
            error=(p.stderr or '')[-1200:]
            if re.search('quota|credits|payment|402|insufficient|unauthorized|401|429|rate.limit',error,re.I):
                stop.set()
                dump(WORK/'search-service-stop.json',dict(at=base.NOW(),service='Firecrawl CLI search',reason=error,action='stop pending search calls; continue official HTTP and retained discovery'))
            dump(path.with_suffix('.meta.json'),dict(at=base.NOW(),query=query,exit_code=p.returncode,error=error))
            if not path.exists(): return 'search-failed'
            r=json.loads(path.read_text(encoding='utf-8'));return 'results' if r.get('data',{}).get('web') else 'empty'
        except (subprocess.TimeoutExpired,json.JSONDecodeError) as e:
            dump(path.with_suffix('.meta.json'),dict(at=base.NOW(),query=query,error=type(e).__name__));return 'search-failed'
    counts=Counter()
    with ThreadPoolExecutor(3) as pool:
        for i,f in enumerate(as_completed([pool.submit(one,row) for row in load()]),1):
            counts[f.result()]+=1
            if i%10==0: print(json.dumps(dict(done=i,counts=dict(counts)),ensure_ascii=False),flush=True)
    print(json.dumps(counts,ensure_ascii=False),flush=True)


def ucas_index(rows):
    row=dict(domain='ucas.ac.cn',group='研究所')
    m,s=capture(UCAS,row)
    if s is None: return
    urls=[UCAS]+list(dict.fromkeys(urljoin(UCAS,a['href']) for a in s.select('a[href]') if re.fullmatch('[2-7]',a.get_text(strip=True))))
    found=[]
    for u in urls:
        m,s=capture(u,row)
        if s is None: continue
        # This server renders detail URLs as links inside table rows.
        for a in s.select('a[href]'):
            target=urljoin(u,a['href']);name=a.get_text(' ',strip=True)
            if '/ZhaoshengDanweiDetail/' not in target: continue
            found.append(dict(name=name,url=target,source=u))
    dump(WORK/'ucas-public-master-units.json',found)
    for row in rows:
        if row.get('ucas_name'):
            matches=[x for x in found if x['name']==row['ucas_name']]
            row['documents'].extend(dict(title=row['name']+'2027年硕士统考专业目录',url=x['url'],discovered_on=x['source'],source_channel='UCAS硕士招生目录') for x in matches)
    print(json.dumps(dict(ucas_index_pages=len(urls),units=len(found),matched=sum(any(x['name']==r.get('ucas_name') for x in found) for r in rows)),ensure_ascii=False),flush=True)


def collect_row(row):
    docs={d['url']:d for d in row['documents']}
    search_path=WORK/'search'/(row['key']+'.json')
    if search_path.exists():
        for d in json.loads(search_path.read_text(encoding='utf-8')).get('data',{}).get('web',[]):
            if allowed(d['url'],row) and refine.relevant(d['title']): docs.setdefault(d['url'],dict(title=d['title'],url=d['url'],discovery_file=str(search_path)))
    # Refresh the official entry once per run; inspect its actual announcement links.
    entry=row.get('portal') or row.get('chsi')
    todo=[dict(title=row['name']+'招生栏目',url=entry)] if entry else []
    pending = [d for d in docs.values() if not refine.ATTACH.search(d['url']) and (d.get('source_channel') or not d.get('actionable'))]
    pending.sort(key=lambda d: (not bool(d.get('source_channel')), -(d.get('year') or refine.year_of(d['title']) or 0), not bool(refine.COMPUTING.search(d['title']))))
    todo += pending[:24]
    seen=set(); fetched=0
    while todo and fetched<45:
        d=todo.pop(0);u=d['url']
        if not u or u in seen or not allowed(u,row): continue
        seen.add(u)
        # Reuse successful old evidence for unchanged historical announcements.
        old_key=hashlib.sha256(u.encode()).hexdigest()
        old_html=base.EVIDENCE/'pages'/(old_key+'.html')
        old_meta=old_html.with_suffix('.json')
        if old_html.exists() and old_meta.exists() and d.get('year')!=2027 and u!=entry:
            m=json.loads(old_meta.read_text(encoding='utf-8'));s=BeautifulSoup(base.decode_html(old_html.read_bytes()),'html.parser') if m.get('status','').startswith('原页') else None
        else: m,s=capture(u,row)
        fetched+=1
        if s is None:
            docs.setdefault(u,d)['priority_access']=m;continue
        title=s.title.get_text(' ',strip=True) if s.title else d['title']
        # Precise article identity remains distinct from a generic listing page.
        doc=docs.setdefault(u,d);doc['priority_access']=m
        body=None
        for selector in ('.TRS_Editor','.v_news_content','#vsb_content','.wp_articlecontent','.article-content','.article_content','article'):
            candidate=s.select_one(selector)
            if candidate and len(candidate.get_text(' ',strip=True))>60: body=candidate;break
        source_channel=doc.get('source_channel')
        if source_channel or (refine.year_of(title) and refine.kinds(title)):
            body=body or s.body or s
            y=2027 if source_channel else refine.year_of(title)
            p=Path(row['folder'])/'助手整理网页'/f'{y}_{old_key[:12]}.md'
            p.write_text(f"# {doc['title']}\n\n原始URL：{u}\n\n获取：{m.get('checked_at')}\n\n正文留存；字段和竞争池仍待核验。\n\n"+body.get_text('\n',strip=True),encoding='utf-8')
            doc.update(local_text=str(p),actionable=True,year=y,status='具体原页已留存（字段待核验）',resource_types=['统考专业目录'] if source_channel else refine.kinds(title))
        links=[]
        for a in s.select('a[href]'):
            target=urljoin(m.get('final_url',u),a['href']);label=(a.get('title') or a.get_text(' ',strip=True)).strip()
            if not allowed(target,row) or not label or len(label)>230: continue
            if not refine.relevant(label): continue
            if refine.year_of(label) and refine.kinds(label) and ('硕士' in label or refine.COMPUTING.search(label)):
                x=dict(title=label,url=target,discovered_on=u,year=refine.year_of(label),resource_types=refine.kinds(label))
            elif refine.ATTACH.search(target) and body and a in body.descendants and refine.year_of(doc.get('title','')):
                # A 2027 catalogue page can attach earlier historical statistics.
                x=dict(title=doc['title']+' — '+label,url=target,parent_url=u,parent_title=doc['title'],attachment_label=label,year=refine.year_of(label) or refine.year_of(doc['title']),resource_types=refine.kinds(label) or refine.kinds(doc['title']))
            elif u==entry and re.search('招生信息|硕士招生|招生简章|录取公示|招生公告',label):
                x=dict(title=label,url=target,discovered_on=u)
            else: continue
            if target not in docs:
                docs[target]=x
                if not refine.ATTACH.search(target): links.append(x)
        links.sort(key=lambda x: (-(x.get('year') or 0),not bool(refine.COMPUTING.search(x['title']))))
        todo.extend(links[:18])
    row['documents']=list(docs.values())
    dump(WORK/'units'/(row['key']+'.json'),row)
    return dict(name=row['name'],requests=fetched,documents=len(docs),saved=sum(bool(d.get('local_text')) for d in docs.values()))


def crawl():
    rows=load();ucas_index(rows)
    with ThreadPoolExecutor(8) as pool:
        for i,f in enumerate(as_completed([pool.submit(collect_row,r) for r in rows]),1):
            result=f.result()
            if i%5==0 or result['name'].startswith('中国科学院'): print(json.dumps(dict(done=i,**result),ensure_ascii=False),flush=True)


def build():
    field_file=OUT/'已提取11408专业.json'
    field_data=json.loads(field_file.read_text(encoding='utf-8')) if field_file.exists() else {'all_rows':[], 'counts':{}}
    attachment_records=[json.loads(f.read_text(encoding='utf-8')) for f in (WORK/'attachments').glob('*.json')]
    rows=[];counts=Counter();cards=[];summary=['# 优先院校与研究所资料清单','',f'更新：{base.NOW()}','', '按学校优先级收集；资料可访问与2027年11408资格分开核验。', '', '|单位|批次|已留存原文|目录2027|历史录取材料|','|---|---|---|---|---|']
    for row in load():
        p=WORK/'units'/(row['key']+'.json')
        if p.exists():row=json.loads(p.read_text(encoding='utf-8'))
        docs=row['documents']
        for d in docs:
            d['scope']=d.get('scope') or refine.scope_of(d['title'],row['name'])
            d['admission_route']='调剂/补录' if re.search('调剂|补录|递补',d['title']) else '一志愿' if '一志愿' in d['title'] else '推免' if re.search('推免|推荐免试',d['title']) else '具体路径待核验'
            if re.search('分数线|复试线',d['title']) and '复试' in d['title']:
                d['resource_types']=list(dict.fromkeys(d.get('resource_types',[])+['复试分数线']))
            if refine.ATTACH.search(d['url']):
                label=d.get('attachment_label') or d['title'].split(' — ')[-1]
                if d.get('parent_title') or ' — ' in d['title']:
                    d['year']=refine.year_of(label) or d.get('year') or refine.year_of(d.get('parent_title',''))
                    d['resource_types']=['招生统计'] if re.search('报考.*录取|上线.*录取|报录',label) else refine.kinds(label) or d.get('resource_types',[])
                file_meta=WORK/'attachments'/(hashlib.sha256(d['url'].encode()).hexdigest()+'.json')
                if file_meta.exists():
                    d['attachment_access']=json.loads(file_meta.read_text(encoding='utf-8'))
                    d['status']=d['attachment_access']['status']
            # A notice addressed to admitted students is not an admission list.
            if '拟录取名单' in d.get('resource_types',[]) and not re.search('拟录取.*名单|拟录取.*公示|拟录取.*结果|待录取.*名单|录取.*名单|名单.*录取|公示.*拟录取',d['title']):
                d['resource_types']=[k for k in d['resource_types'] if k!='拟录取名单']
        good=[d for d in docs if d.get('actionable')]
        slots=[]
        for y,kinds in [(2027,['统考专业目录','招生简章','招生计划','科目或单位调整']),(2026,['招生计划','复试分数线','复试办法','复试名单','复试成绩','拟录取名单','招生统计']),(2025,['复试分数线','复试办法','拟录取名单']),(2024,['复试分数线','复试办法','拟录取名单'])]:
            for k in kinds:
                matches=[d for d in good if d.get('year')==y and k in d.get('resource_types',[])]
                files=[d for d in docs if d.get('year')==y and k in d.get('resource_types',[]) and d.get('attachment_access',{}).get('artifact')]
                slots.append(dict(year=y,kind=k,urls=[d['url'] for d in matches]+[d['url'] for d in files],status='原页/附件已留存；具体专业覆盖待核验' if matches or files else '本轮未取得可核验原页'))
        subject_rows=[r for r in field_data['all_rows'] if r['unit']==row['name']]
        matched_rows=[r for r in subject_rows if r['eligible_11408'] is True]
        row['subject_screening']=dict(extracted_rows=len(subject_rows),matched_rows=len(matched_rows),subject_unknown_rows=sum(r['eligible_11408'] is None for r in subject_rows),ranking_pool_verified=False)
        if subject_rows:row['eligibility']=f'目录已逐行提取：{len(matched_rows)}条四科匹配记录；报考限制、费用与排名池待核验'
        row['slots']=slots;row['coverage_2027_catalog']=any(s['year']==2027 and s['kind']=='统考专业目录' and s['urls'] for s in slots)
        row['coverage_2026_admits']=any(s['year']==2026 and s['kind']=='拟录取名单' and s['urls'] for s in slots)
        rows.append(row);counts[row['group']]+=1;counts['resources']+=len(docs);counts['saved_articles']+=len(good);counts['units_2027_catalog']+=row['coverage_2027_catalog'];counts['units_2026_admits']+=row['coverage_2026_admits']
        lines=[f"# {row['name']} 优先采集清单",'',f"批次：{row['group']}；{row['eligibility']}",'',f"候选依据：{row['basis']}",'','## 已定位原文与附件','','|年度|材料|官方URL|访问/内容状态|','|---|---|---|---|']
        articles=[]
        for d in sorted(docs,key=lambda x:(not bool(x.get('actionable')),-(x.get('year') or 0),x['title'])):
            y=d.get('year') or refine.year_of(d['title']) or '待核对';state=d.get('status') or d.get('priority_access',{}).get('status') or '线索已发现，原文待核验'
            lines.append(f"|{y}|{d['title'].replace('|',' ')}|[打开]({d['url']})|{state}|")
            local=d.get('attachment_access',{}).get('artifact') or d.get('local_text')
            local_link=''
            if local and Path(local).exists():
                rel=Path(local).resolve().relative_to(OUT.resolve()).as_posix()
                local_link=f' · <a href="{quote(rel)}">本地留存</a>'
            if d.get('actionable') or refine.ATTACH.search(d['url']): articles.append(f'<p><a href="{html.escape(d["url"],quote=True)}">{html.escape(str(y)+" · "+d["title"])}</a>{local_link}<br><small>{html.escape(state)}</small></p>')
        lines+=['','## 待补项','']+[f"- {s['year']} {s['kind']}：{s['status']}" for s in slots if not s['urls']]
        (Path(row['folder'])/'优先采集清单.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
        summary.append(f"|{row['name']}|{row['group']}|{len(good)}|{'已取得原页' if row['coverage_2027_catalog'] else '待补/待核验'}|{'2026已取得原页' if row['coverage_2026_admits'] else '2026待补/待核验'}|")
        gaps='；'.join(f"{s['year']}{s['kind']}" for s in slots if not s['urls'])
        cards.append(f'<details data-name="{html.escape(row["name"],quote=True)}" data-group="{html.escape(row["group"],quote=True)}"><summary>{html.escape(row["name"])} · {html.escape(row["group"])} · {len(good)}条已留存原页</summary><p>{html.escape(row["eligibility"])}</p><p>目录：{html.escape(row["folder"])}</p><p class="gap">待补：{html.escape(gaps)}</p>'+''.join(articles)+'</details>')
    counts['downloaded_attachment_records']=sum(bool(x.get('artifact')) for x in attachment_records)
    counts['unique_attachment_hashes']=len({x['sha256'] for x in attachment_records if x.get('artifact')})
    payload=dict(at=base.NOW(),scope='优先批次；院校/单位数量不是11408资格数量，校级文件不代表所有目标院系齐全',counts=dict(counts),field_counts=field_data['counts'],units=rows)
    dump(OUT/'优先院校资料.json',payload)
    (OUT/'优先院校资料.md').write_text('\n'.join(summary)+'\n',encoding='utf-8')
    page='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>985、计算机强校与研究所资料</title><style>body{font:16px/1.6 system-ui;max-width:1150px;margin:30px auto;padding:20px;background:#f4f7fa;color:#18324a}details{background:white;border:1px solid #ccd6df;border-radius:8px;padding:15px;margin:14px 0}summary{font-weight:700;cursor:pointer}a{color:#135ba0}small,.gap{color:#766019}input,select{padding:9px;font:inherit}p{overflow-wrap:anywhere}</style><h1>985、计算机强校与研究所资料</h1><p>39所985、19所计算机相关非985候选、10个研究所。11408资格逐专业核验；缺项不等于学校未发布。</p>'
    page+=f'<p>当前已留存原页记录 {counts["saved_articles"]} 条；{counts["units_2027_catalog"]} 个单位取得2027目录页面；{counts["units_2026_admits"]} 个单位取得2026录取材料。包含校级、调剂等不同范围，附件与字段需分别核验。</p><p>附件留存记录 {counts["downloaded_attachment_records"]} 条，按文件哈希去重 {counts["unique_attachment_hashes"]} 份。<a href="已提取11408专业.md">科目初筛表</a> · <a href="已提取11408专业.csv">CSV</a> · <a href="杭电2026招生统计核验.md">杭电历史统计核验</a></p>'
    fc=field_data['counts']
    if fc:page+=f'<p>已逐行提取 {fc["source_units"]} 个单位目录；{fc["matched_units"]} 个单位有四科匹配记录，共 {fc["matched_rows"]} 条方向记录。未解析的替代科目等情况保留为未知，不纳入匹配。方向记录不等于独立排名池；排名池核验尚未完成。</p>'
    page+='<input id="q" placeholder="搜索学校或研究所"><select id="g"><option value="">全部批次</option><option>985</option><option>计算机相关强校候选</option><option>研究所</option></select>'
    page+=''.join(cards)+'<script>function f(){const q=document.getElementById("q").value,g=document.getElementById("g").value;document.querySelectorAll("details[data-name]").forEach(x=>x.hidden=!x.dataset.name.includes(q)||(g&&x.dataset.group!==g))}document.getElementById("q").oninput=f;document.getElementById("g").onchange=f;</script></html>'
    (OUT/'优先院校资料.html').write_text(page,encoding='utf-8')
    print(json.dumps(counts,ensure_ascii=False),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['init','search','crawl','build']);a=p.parse_args();WORK.mkdir(parents=True,exist_ok=True)
    {'init':initialize,'search':search,'crawl':crawl,'build':build}[a.action]()
