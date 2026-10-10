"""Resolve saved official-source leads into a per-school resource ledger.

Public HTML is cached locally; attachment probes read at most 4 KiB, not full
admission lists. Discovery and successful HTTP transport never prove 11408.
"""
from __future__ import annotations
import argparse
import hashlib
import html
import json
import re
import threading
from collections import Counter, defaultdict, deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urljoin, urlsplit, parse_qs, unquote
import requests
from bs4 import BeautifulSoup
import build_download_index as base

ROOT, OUT = base.ROOT, base.DOWNLOADS
WORK = base.EVIDENCE / 'resource-audit'
KINDS = ('统考专业目录', '招生简章', '招生计划', '复试办法', '复试名单', '复试成绩', '拟录取名单', '科目或单位调整', '调剂补录')
COMPUTING = re.compile('计算机|软件|人工智能|智能科学|网络空间|网络安全|信息科学|信息工程|信息技术|信息学院|信息学部|电子信息|大数据|数据科学|智能工程')
IGNORE = re.compile('推免|推荐免试|免试攻读|夏令营|港澳台|港、澳、台|来华|留学生|本科|博士后|同等学力申硕|单独考试|国优计划|专项计划招生简章')
OTHER_DEPT = re.compile('音乐|美术|戏剧|舞蹈|体育|法学|法学院|马克思|口腔|中医|临床|护理|药学|外语|外国语|物理|化学|机械|材料|资源与|矿业|地质|农业|农学|建筑|土木|水利|文学院|商学院|经济学院|管理学院|教育学院|数学学院|统计学院')
ATTACH = re.compile(r'\.(?:pdf|docx?|xlsx?|zip|rar)(?:[?#]|$)|download\.jsp', re.I)

def dump(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')

def relevant(title):
    return not (IGNORE.search(title) or base.IRRELEVANT.search(title) or ('博士' in title and '硕士' not in title) or (OTHER_DEPT.search(title) and not COMPUTING.search(title)))

def kinds(title):
    found = []
    if re.search('目录|专业一览|专业及.*科目|专业信息|招生专业.*科目', title) and not re.search('调整|变更', title): found.append('统考专业目录')
    if re.search('简章|章程', title): found.append('招生简章')
    if re.search('招生计划|招生名额|统考.*计划|分专业.*计划', title): found.append('招生计划')
    if '复试' in title and re.search('办法|方案|细则|安排|工作|实施|通知', title): found.append('复试办法')
    if re.search('复试.*名单|进入.*复试.*名|入围.*名', title): found.append('复试名单')
    if re.search('复试.*成绩|总成绩|综合成绩|最终成绩|成绩.*公示', title): found.append('复试成绩')
    if re.search('拟录取|录取.*名单|名单.*录取', title): found.append('拟录取名单')
    if re.search('调整|变更|合并', title): found.append('科目或单位调整')
    if re.search('调剂|补录|递补|更正', title): found.append('调剂补录')
    return found

def year_of(title):
    match = re.search(r'202[4-7]', title)
    return int(match[0]) if match else None

def scope_of(title, school):
    if COMPUTING.search(title): return '计算机相关线索（具体专业待核验）'
    # Remove the university name before looking for a subordinate college.
    rest = title.replace(school, '')
    if re.search('学院|学部|研究所|实验室|中心', rest) and not re.search('研究生院|研究生招生', rest):
        return '院系范围待核验'
    return '校级综合（须定位目标院系）'

def candidates():
    previous = json.loads((OUT/'下载索引.json').read_text(encoding='utf-8'))
    old = {s['sch_id']: s for s in previous['schools']}
    output = []
    for s in base.schools():
        seed = old[s['sch_id']]
        docs = {d['url']:d.copy() for d in seed['documents']}
        for d in base.parse_results(s):
            if d['url'] not in docs: docs[d['url']] = d
        extra = WORK/'linked'/f"{s['sch_id']}.json"
        if extra.exists():
            for d in json.loads(extra.read_text(encoding='utf-8')):
                if d['url'] not in docs: docs[d['url']] = d
        seed = {k:v for k,v in seed.items() if k!='documents'}
        seed['documents'] = [d for d in docs.values() if relevant(d['title'])]
        output.append(seed)
    return output

def read_pages():
    rows = candidates()
    tasks = [(d,s['domain']) for s in rows for d in s['documents'] if not ATTACH.search(d['url'])]
    pending=[(d,domain) for d,domain in tasks if not (base.EVIDENCE/'pages'/(hashlib.sha256(d['url'].encode()).hexdigest()+'.json')).exists()]
    print(json.dumps({'candidate_pages':len(tasks),'cached':len(tasks)-len(pending),'pending':len(pending)},ensure_ascii=False),flush=True)
    tasks = interleave(pending)
    with ThreadPoolExecutor(max_workers=24) as pool:
        fs=[pool.submit(base.inspect_page,d,domain) for d,domain in tasks]
        stats=Counter()
        for i,f in enumerate(as_completed(fs),1):
            try: stats[f.result()['status']]+=1
            except Exception as e: stats[type(e).__name__]+=1
            if i%100==0:print(json.dumps({'read':i,'total':len(tasks),'statuses':dict(stats)},ensure_ascii=False),flush=True)
    dump(WORK/'page-pass.json',{'at':base.NOW(),'total':len(tasks),'statuses':dict(stats)})

def interleave(tasks):
    """Avoid parking every worker behind the same university host lock."""
    groups=defaultdict(deque)
    for d,domain in tasks:
        groups[urlsplit(d['url']).hostname].append((d,domain))
    ordered=[]
    while groups:
        for host in list(groups):
            ordered.append(groups[host].popleft())
            if not groups[host]:del groups[host]
    return ordered

def page_info(d):
    key=hashlib.sha256(d['url'].encode()).hexdigest()
    meta=base.EVIDENCE/'pages'/(key+'.json')
    raw=base.EVIDENCE/'pages'/(key+'.html')
    record=json.loads(meta.read_text(encoding='utf-8')) if meta.exists() else {}
    if not raw.exists() or not record.get('status','').startswith('原页'): return record,None,None
    soup=BeautifulSoup(base.decode_html(raw.read_bytes()),'html.parser')
    body=None
    for selector in ('.v_news_content','#vsb_content','#vsb_content_2','.wp_articlecontent','#Zoom','.TRS_Editor','.article-content','.article_content','.news_content','article'):
        body=soup.select_one(selector)
        if body and len(body.get_text(' ',strip=True))>60: break
    if body is None:
        body=soup.body or soup
    return record,soup,body

def discover():
    stats=Counter()
    for s in candidates():
        found={}
        path=WORK/'linked'/f"{s['sch_id']}.json"
        if path.exists(): found={d['url']:d for d in json.loads(path.read_text(encoding='utf-8'))}
        for d in s['documents']:
            record,soup,body=page_info(d)
            if soup is None: continue
            # VSB PDF widgets store a literal URL inside JavaScript. Read the
            # string as data without executing any source-provided code.
            for script in soup.find_all('script'):
                for target in re.findall(r'''showVsbpdfIframe\(\s*["']([^"']+)["']''',script.string or script.get_text()):
                    url=urljoin(record.get('final_url',d['url']),html.unescape(target))
                    if base.within_domain(url,s['domain']) and ATTACH.search(url):
                        found.setdefault(url,dict(title=d['title']+'（内嵌PDF）',url=url,parent_title=d['title'],parent_url=d['url'],year_inherited=year_of(d['title']),discovery_file=str(path.relative_to(ROOT)),link_type='attachment'))
            # Literal links only; entire page can include attachment widgets outside the body.
            for a in soup.find_all(['a','iframe','embed','object']):
                target=a.get('href') or a.get('src') or a.get('data')
                if not target:continue
                url=urljoin(record.get('final_url',d['url']),target)
                if not base.within_domain(url,s['domain']):continue
                title=(a.get('title') or a.get_text(' ',strip=True)).strip()
                if a.name in ('iframe','embed','object'):
                    params=parse_qs(urlsplit(url).query)
                    for name in ('file','url','pdf'):
                        if params.get(name): url=urljoin(url,unquote(params[name][0]));break
                    if not ATTACH.search(url):continue
                    title=title or d['title']+'（内嵌附件）'
                if len(title)>250 or not title:continue
                if not relevant(title):continue
                if ATTACH.search(url):
                    if not kinds(title) and not re.search('计算机|软件|人工智能|0812|0854|附件',title):continue
                    if not year_of(d['title']) and not year_of(title):continue
                    found.setdefault(url,dict(title=title,url=url,parent_title=d['title'],parent_url=d['url'],year_inherited=year_of(d['title']),discovery_file=str((base.EVIDENCE/'pages'/(hashlib.sha256(d['url'].encode()).hexdigest()+'.html')).relative_to(ROOT)),link_type='attachment'))
                elif year_of(title) and kinds(title) and ('硕士' in title or COMPUTING.search(title)):
                    found.setdefault(url,dict(title=title,url=url,discovered_on=d['url'],discovery_file=str(path.relative_to(ROOT))))
        dump(path,list(found.values()));stats['links']+=len(found)
    print(json.dumps(stats,ensure_ascii=False),flush=True)

probe_locks={}
probe_guard=threading.Lock()

def probe(d,domain):
    path=WORK/'attachment-probes'/(hashlib.sha256(d['url'].encode()).hexdigest()+'.json')
    if path.exists():return json.loads(path.read_text(encoding='utf-8'))
    record=dict(url=d['url'],checked_at=base.NOW(),status='附件访问未核验')
    with probe_guard: lock=probe_locks.setdefault(urlsplit(d['url']).hostname,threading.Lock())
    try:
        with lock,requests.get(d['url'],headers={'User-Agent':'Mozilla/5.0','Range':'bytes=0-4095'},stream=True,timeout=(5,12)) as r:
            record.update(http_status=r.status_code,final_url=r.url,content_type=r.headers.get('Content-Type'),content_length=r.headers.get('Content-Length'))
            if not base.within_domain(r.url,domain):record['status']='附件跳转域待核验'
            elif r.status_code not in (200,206):record['status']=f'附件HTTP {r.status_code}'
            else:
                head=next(r.iter_content(4096),b'')
                fmt='PDF' if head.startswith(b'%PDF-') else 'ZIP/Office' if head.startswith(b'PK\x03\x04') else 'OLE/Office' if head.startswith(bytes.fromhex('d0cf11e0a1b11ae1')) else None
                record.update(file_signature=fmt,prefix_sha256=hashlib.sha256(head).hexdigest())
                record['status']='附件可访问（文件头核验，内容待核验）' if fmt else '附件未取得文件（可能验证页/中转页）'
    except requests.RequestException as e:record.update(status='附件网络失败',error=type(e).__name__)
    dump(path,record);return record

def probe_all():
    tasks={(d['url'],s['domain']):(d,s['domain']) for s in candidates() for d in s['documents'] if ATTACH.search(d['url'])}
    stats=Counter()
    with ThreadPoolExecutor(max_workers=8) as pool:
        fs=[pool.submit(probe,d,domain) for d,domain in interleave(tasks.values())]
        for i,f in enumerate(as_completed(fs),1):
            stats[f.result()['status']]+=1
            if i%100==0:print(json.dumps({'probed':i,'total':len(fs),'statuses':dict(stats)},ensure_ascii=False),flush=True)
    print(json.dumps(stats,ensure_ascii=False),flush=True)

def resolve(s,d):
    d=d.copy();title=d['title']; parent=d.get('parent_title','')
    year=year_of(title) or d.get('year_inherited')
    cats=kinds(title)
    if not cats and parent and ATTACH.search(d['url']):cats=kinds(parent)
    d.update(year=year,resource_types=cats,scope=scope_of(title+' '+parent,s['name']),is_attachment=bool(ATTACH.search(d['url'])))
    if d['is_attachment']:
        pp=WORK/'attachment-probes'/(hashlib.sha256(d['url'].encode()).hexdigest()+'.json')
        record=json.loads(pp.read_text(encoding='utf-8')) if pp.exists() else {}
        d['status']=record.get('status','附件链接已发现（访问待核验）');d['verification']=record
        d['actionable']=d['status'].startswith('附件可访问')
        if record.get('http_status')==404:d['actionable']=False
    else:
        record,soup,body=page_info(d)
        d['status']=record.get('status','原页待获取');d['verification']=record
        d['actionable']=False
        if soup is not None:
            main_title=(soup.title.get_text(' ',strip=True) if soup.title else '')
            # A generic school-name prefix in navigation cannot establish that
            # this is the requested article. Require year and resource type in
            # the page title, or a distinct article container plus full title.
            title_core=re.split(r'[-_—]|\s20\d{2}-\d{2}-\d{2}',title)[0].strip()
            whole=soup.get_text(' ',strip=True)
            distinct=body is not soup and body is not soup.body
            title_match=(bool(year) and str(year) in main_title and bool(set(kinds(main_title)) & set(cats))) or (distinct and len(title_core)>=14 and title_core in whole)
            plain=body.get_text(' ',strip=True)
            blocked=re.search('访问验证|验证码|人机验证|Access Denied|无法访问此网站|页面不存在|404 Not Found',main_title,re.I)
            if title_match and not blocked and cats and year:
                d['actionable']=True;d['status']='具体公告原页已读取（专业/附件内容待核验）'
                if '复试办法' in cats and re.search('招生计划|招生名额',plain):
                    if '招生计划' not in cats:cats.append('招生计划')
                    d['plan_in_rules']=True
                # Store web text locally; never print applicant rows to logs.
                folder=Path(s['folder'])/'助手整理网页'
                filename=f"{year}_{hashlib.sha256(d['url'].encode()).hexdigest()[:12]}.md"
                local=folder/filename;folder.mkdir(exist_ok=True)
                local.write_text(f"# {title}\n\n原始URL：{d['url']}\n\n抓取时间：{record.get('checked_at')}\n\n范围：{d['scope']}；正文已留存，不代表院系/名单内容已逐项核验。\n\n{plain}\n",encoding='utf-8')
                d['local_text']=str(local)
            elif cats and year:d['status']='页面已获取但公告身份待核验'
            else:d['status']='栏目或年份待核验（不计入具体资源）'
    d['resource_types']=cats
    d['save_to']=str(Path(s['folder'])/str(year or '待分类')/({'统考专业目录':'01目录与简章','招生简章':'01目录与简章','招生计划':'02计划与调整','科目或单位调整':'02计划与调整','拟录取名单':'04拟录取与调剂','调剂补录':'04拟录取与调剂'}.get(cats[0] if cats else '', '03复试名单与成绩'))) if year else str(Path(s['folder'])/'待分类')
    return d

def build():
    rows=candidates();totals=Counter();queries=[]
    for s in rows:
        s['documents']=[resolve(s,d) for d in s['documents']]
        s['documents'].sort(key=lambda d:(not d['actionable'],-(d['year'] or 0),d['resource_types'],d['title']))
        s['slots']=[]
        for year in (2027,2026,2025,2024):
            for kind in (('统考专业目录','招生计划','科目或单位调整') if year==2027 else ('统考专业目录','招生计划','复试办法','复试名单','复试成绩','拟录取名单')):
                matches=[d for d in s['documents'] if d['year']==year and kind in d['resource_types'] and d['actionable']]
                leads=[d for d in s['documents'] if d['year']==year and kind in d['resource_types'] and not d['actionable']]
                status='已定位具体资源；院系/专业覆盖仍待核验' if matches else '有候选链接但原文/访问未核验' if leads else '本轮未定位；不等于未发布'
                slot=dict(year=year,kind=kind,status=status,urls=[d['url'] for d in matches],candidate_urls=[d['url'] for d in leads])
                s['slots'].append(slot);totals['slots']+=1;totals['located_slots']+=bool(matches)
        totals['schools']+=1;totals['resources']+=len(s['documents']);totals['actionable']+=sum(d['actionable'] for d in s['documents'])
        totals['accessible_attachments']+=sum(d['actionable'] and d['is_attachment'] for d in s['documents'])
        totals['read_announcements']+=sum(d['actionable'] and not d['is_attachment'] for d in s['documents'])
        queries.extend([p.name for p in (base.EVIDENCE/'search').glob(s['sch_id']+'-resource*.json')])
    payload={'updated_at':base.NOW(),'scope':'现有148所入口候选，尚未全部确认11408；资源定位不是学校资格或材料完备性验收','counts':dict(totals),'targeted_queries':len(queries),'schools':rows}
    dump(OUT/'逐项资源核验.json',payload)
    render(payload)
    print(json.dumps({'counts':dict(totals),'targeted_queries':len(queries)},ensure_ascii=False),flush=True)

def render(payload):
    esc=lambda s:html.escape(str(s),quote=True)
    cards=[];gaps=['# 逐项资源缺口','',f"更新：{payload['updated_at']}",'','未定位不等于未发布；已定位也不表示所有目标院系均覆盖。2027招生计划/调整通知属于可能单独发布或嵌入目录的条件项。不期待尚未发生的2027复试录取名单。','','|学校|年度|资料|状态|','|---|---|---|---|']
    for s in payload['schools']:
        lines=[f"# {s['name']} 具体资源清单",'',s['eligibility'],'','先看2027统考目录和科目公告；历史名单须核对同一院系、专业、统考/推免、一志愿/调剂。校级综合资源不代表计算机专业已核验。','','## 具体资源','','|年度|类型|原始公告/附件|状态|保存位置|','|---|---|---|---|---|'];articles=[]
        for d in s['documents']:
            label='/'.join(d['resource_types']) or '入口/待分类'
            lines.append(f"|{d['year'] or '待核对'}|{label}|[{d['title'].replace('|',' ')}]({d['url']})|{d['status']}；{d['scope']}|`{d['save_to']}`|")
            if not d['actionable']:continue
            parent=f'<a target="_blank" rel="noopener" href="{esc(d["parent_url"])}">附件所在公告</a>' if d.get('parent_url') else ''
            local=f'<a href="{Path(d["local_text"]).relative_to(OUT).as_posix()}">已留存网页文字</a>' if d.get('local_text') else ''
            articles.append(f'<article data-year="{d["year"]}"><h3><a target="_blank" rel="noopener" href="{esc(d["url"])}">{esc(d["title"])}</a></h3><p>{d["year"]} · {esc(label)} · {esc(d["scope"])}</p><p>{esc(d["status"])} {parent} {local}</p><code>{esc(d["save_to"])}</code></article>')
        lines+=['','## 逐项缺口','','|年度|资料|状态|','|---|---|---|']
        missing=[]
        for slot in s['slots']:
            lines.append(f"|{slot['year']}|{slot['kind']}|{slot['status']}|")
            if not slot['urls']:
                gaps.append(f"|{s['name']}|{slot['year']}|{slot['kind']}|{slot['status']}|")
                missing.append(f"{slot['year']} {slot['kind']}：{slot['status']}")
        (Path(s['folder'])/'具体资源清单.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
        cards.append(f'<details data-school="{esc(s["name"])}"><summary>{esc(s["name"])} · {len(articles)} 条具体公告/可访问附件</summary><p>{esc(s["eligibility"])}</p><p><a href="{esc(Path(s["folder"]).name)}/具体资源清单.md">全部线索与访问失败记录</a></p>{"".join(articles)}<details><summary>待补/待核验项（{len(missing)}）</summary><ul>'+''.join('<li>'+esc(x)+'</li>' for x in missing)+'</ul></details></details>')
    (OUT/'逐项资源缺口.md').write_text('\n'.join(gaps)+'\n',encoding='utf-8')
    doc='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>具体招生资料导航</title><style>body{font:16px/1.6 system-ui,sans-serif;color:#17304a;background:#f4f6f9;max-width:1100px;margin:32px auto;padding:0 20px}header{position:sticky;top:0;background:#f4f6f9;padding:12px 0}input,select{font:inherit;padding:9px}input{width:60%}details{background:white;border:1px solid #d1dbe5;border-radius:9px;padding:16px;margin:12px 0}summary{cursor:pointer;font-weight:bold}article{padding:14px 0;border-top:1px solid #ddd}h3{font-size:17px;margin:5px 0}a{color:#1762a6}code{font-size:12px;overflow-wrap:anywhere}p{margin:5px 0}.note{color:#855700}</style><header><h1>具体招生资料导航</h1><input id="q" placeholder="搜索学校"><select id="year"><option value="">全部年度</option><option>2027</option><option>2026</option><option>2025</option><option>2024</option></select></header>'''
    c=payload['counts']
    doc+=f'<p>现有 {c["schools"]} 所候选，定位 {c["read_announcements"]} 条已读取具体公告，{c["accessible_attachments"]} 条文件头验证可访问附件。</p><p class="note">这不是已确认11408名单，也不是资料齐全证明。正文/文件头可访问不表示全部院系、专业及名单内容核验完毕；目录、计划及录取口径仍需逐专业校对。只列公开官网来源。</p><p><a href="逐项资源缺口.md">逐项缺口</a> · <a href="下载总表.md">学校与目录总表</a> · <a href="下载导航.html">旧版全部线索（含栏目）</a></p>'+''.join(cards)
    doc+='''<script>function filter(){const q=document.getElementById('q').value.trim(),y=document.getElementById('year').value;document.querySelectorAll('[data-school]').forEach(s=>s.hidden=!s.dataset.school.includes(q));document.querySelectorAll('[data-year]').forEach(a=>a.hidden=!!y&&a.dataset.year!==y)}document.getElementById('q').oninput=filter;document.getElementById('year').onchange=filter;</script></html>'''
    (OUT/'具体资源导航.html').write_text(doc,encoding='utf-8')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=('read','discover','probe','build'));args=p.parse_args();WORK.mkdir(parents=True,exist_ok=True)
    {'read':read_pages,'discover':discover,'probe':probe_all,'build':build}[args.action]()
