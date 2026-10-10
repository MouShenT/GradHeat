"""Build a local manual-download navigator from saved discovery and page evidence.

Does not download attachments, infer admission eligibility or overwrite user files.
"""
from __future__ import annotations
import argparse
import hashlib
import html
import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / '.research/download-index'
DOWNLOADS = ROOT / '.research/manual-downloads'
SNAPSHOT = ROOT / 'crawler/data/school_portal.20260922T170805Z.jsonl'
YEARS = (2027, 2026, 2025, 2024)
CATEGORIES = ('01目录与简章', '02计划与调整', '03复试名单与成绩', '04拟录取与调剂')
NOW = lambda: datetime.now(timezone.utc).isoformat()
IRRELEVANT = re.compile('录取通知书|通讯地址|通信地址|调档|入学教育|新生报到|新生入学|奖学金|外国留学|来华留学|国际学生|夏令营|毕业|学位授予|师德|培训|就业|科研|学术会议')

def decode_html(raw):
    """Honor common Chinese-site encodings without slow statistical guessing."""
    head=raw[:8192].decode('ascii',errors='ignore')
    match=re.search(r'charset\s*=\s*["\x27]?([\w-]+)',head,re.I)
    encodings=[match[1]] if match else []
    for encoding in encodings+['utf-8','gb18030']:
        try:return raw.decode(encoding)
        except (UnicodeDecodeError,LookupError):pass
    return raw.decode('utf-8',errors='replace')

def schools():
    rows = [r for line in SNAPSHOT.read_text(encoding='utf-8').splitlines() if 'name' in (r := json.loads(line))]
    # Current official home and graduate page read via Exa; old probe used tjpu.edu.cn.
    # Evidence: .research/download-index/tiangong-domain.json
    for r in rows:
        if r['name'] == '天津工业大学':
            r.update(domain='tiangong.edu.cn', portal_url='https://yjsb.tiangong.edu.cn/', portal_verified=False)
    return rows

def within_domain(url, domain):
    host = (urlsplit(url).hostname or '').lower()
    return bool(domain) and (host == domain.lower() or host.endswith('.' + domain.lower()))

def parse_results(school):
    found = {}
    for path in sorted((EVIDENCE / 'search').glob(str(school['sch_id'])+'*.json')):
        data = json.loads(path.read_text(encoding='utf-8'))
        for block in data.get('result', {}).get('content', []):
            if block.get('type') != 'text':
                continue
            for part in re.split(r'(?m)^Title: ', block.get('text', ''))[1:]:
                title = part.splitlines()[0].strip()
                match = re.search(r'(?m)^URL: (https?://\S+)', part)
                if not match or not within_domain(match[1], school.get('domain')):
                    continue
                # Search can return unrelated institutional pages: do not turn these into tasks.
                if not re.search('招生|复试|录取|研究生|专业目录|考试', title):
                    continue
                if ('博士' in title and '硕士' not in title) or re.search('20(?:1[0-9]|2[0-3])',title):
                    continue
                if IRRELEVANT.search(title):continue
                url = match[1]
                if url not in found:
                    found[url] = dict(url=url, title=title, discovery_file=str(path.relative_to(ROOT)), observed_at=data.get('queried_at'))
    return list(found.values())

def linked_announcements(documents, domain):
    """Discover literal links from retained official HTML, not guessed URL patterns."""
    from urllib.parse import urljoin
    found = {}
    existing = {d['url'] for d in documents}
    for doc in documents:
        key = hashlib.sha256(doc['url'].encode()).hexdigest()
        path=EVIDENCE/'pages'/(key+'.html')
        meta=EVIDENCE/'pages'/(key+'.json')
        if not path.exists() or not meta.exists(): continue
        record=json.loads(meta.read_text(encoding='utf-8'))
        if not record['status'].startswith('原页'): continue
        soup=BeautifulSoup(decode_html(path.read_bytes()),'html.parser')
        for a in soup.find_all('a',href=True):
            title=(a.get('title') or a.get_text(' ',strip=True)).strip()
            url=urljoin(record.get('final_url',doc['url']),a['href'])
            if url in existing or url in found or not within_domain(url,domain):continue
            if not re.search(r'202[4-7]',title) or not re.search('硕士|复试|拟录取|招生专业目录',title):continue
            if ('博士' in title and '硕士' not in title) or '本科' in title:continue
            if IRRELEVANT.search(title):continue
            if len(title)<10 or len(title)>220:continue
            if not re.search('招生|复试|拟录取|调剂|计划|目录|成绩|名单',title):continue
            found[url]=dict(url=url,title=title,discovery_file=str(path.relative_to(ROOT)),discovered_on=doc['url'],status='官网页面所列链接（目标正文待核验）')
    return list(found.values())

def classify(title):
    years = re.findall(r'20(?:24|25|26|27)', title)
    year = int(years[0]) if years else None
    if '博士' in title and '硕士' not in title:
        kind = '博士信息（不作为硕士下载任务）'
    elif '推免' in title or '推荐免试' in title:
        kind = '推免资料（不能替代统考目录）'
    elif '拟录取' in title or '调剂' in title:
        kind = CATEGORIES[3]
    elif '复试' in title:
        kind = CATEGORIES[2]
    elif any(x in title for x in ('调整', '变更', '合并', '计划')):
        kind = CATEGORIES[1]
    elif any(x in title for x in ('目录', '简章', '章程')):
        kind = CATEGORIES[0]
    else:
        kind = '栏目/补充说明（需在页面选取具体公告）'
    return year, kind

locks = {}
lock_guard = threading.Lock()

def inspect_page(item, domain):
    """Capture bounded HTML only. Binary attachments remain for the user to download."""
    url = item['url']
    key = hashlib.sha256(url.encode()).hexdigest()
    folder = EVIDENCE / 'pages'; folder.mkdir(parents=True, exist_ok=True)
    meta = folder / (key+'.json')
    if meta.exists():
        return json.loads(meta.read_text(encoding='utf-8'))
    result = dict(url=url, checked_at=NOW(), status='待人工打开', attachments=[])
    if re.search(r'\.(pdf|docx?|xlsx?)(?:[?#]|$)|download\.jsp', url, re.I):
        result['status'] = '附件链接（待用户下载核验）'
    else:
        with lock_guard:
            host_lock = locks.setdefault(urlsplit(url).hostname, threading.Lock())
        try:
            with host_lock, requests.Session() as session:
                with session.get(url, timeout=(5, 12), stream=True, headers={'User-Agent':'Mozilla/5.0'}) as response:
                    result.update(http_status=response.status_code, final_url=response.url)
                    if not within_domain(response.url, domain):
                        result['status'] = '跳转域需人工核验'
                    elif response.status_code != 200:
                        result['status'] = f'HTTP {response.status_code}（待人工打开）'
                    elif 'html' not in response.headers.get('Content-Type', '').lower():
                        result['status'] = '非HTML响应（待用户下载核验）'
                    else:
                        raw = bytearray()
                        for chunk in response.iter_content(32768):
                            raw.extend(chunk)
                            if len(raw) > 1_000_000:
                                break
                        capped = len(raw) > 1_000_000
                        soup = BeautifulSoup(decode_html(bytes(raw)), 'html.parser')
                        title = soup.title.get_text(' ', strip=True) if soup.title else ''
                        for el in soup(['script','style']): el.decompose()
                        text = soup.get_text(' ', strip=True)
                        result.update(page_title=title, html_sha256=hashlib.sha256(raw).hexdigest(), text_length=len(text), truncated=capped)
                        challenge = any(x in title.lower() for x in ('captcha','403','access denied','安全验证','人机验证')) or len(text)<80
                        result['status'] = '正文待人工核验' if challenge or capped else '原页已读取（内容/附件待核验）'
                        (folder/(key+'.html')).write_bytes(raw)
                        # Save attachment labels/URLs as provenance, never credentials or form data.
                        from urllib.parse import urljoin
                        for a in soup.find_all('a', href=True):
                            href = urljoin(response.url,a['href'])
                            if within_domain(href,domain) and re.search(r'\.(pdf|docx?|xlsx?)(?:[?#]|$)|download\.jsp',href,re.I):
                                result['attachments'].append(dict(title=a.get_text(' ',strip=True),url=href))
        except requests.RequestException as exc:
            result.update(status='网络获取失败（待人工打开）',error=type(exc).__name__)
    meta.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result

def build(verify=False):
    data=[]
    for s in schools():
        # Never use scraped text as a filesystem path outside this root.
        name=re.sub(r'[<>:"/\\|?*\x00-\x1f]','_',s['name']).rstrip('. ')
        base=DOWNLOADS/name
        assert base.resolve().is_relative_to(DOWNLOADS.resolve())
        for year in YEARS:
            for category in CATEGORIES:
                (base/str(year)/category).mkdir(parents=True,exist_ok=True)
        row=dict(name=s['name'],sch_id=s['sch_id'],domain=s.get('domain'),folder=str(base),eligibility='2027年11408待核验',portal=s.get('portal_url') if s.get('portal_verified') else None,chsi=s['detail_url'],documents=parse_results(s))
        if s['name']=='华中师范大学':
            known=[('2027年人工智能教育学部招生单位合并与科目公告','https://foaie.ccnu.edu.cn/info/1008/14183.htm'),('2026年硕士招生专业目录','https://gs.ccnu.edu.cn/info/1028/5273.htm'),('2026年计算机学院复试录取工作细则及复试名单','https://cs.ccnu.edu.cn/info/1056/10516.htm'),('2026年计算机学院复试成绩','https://cs.ccnu.edu.cn/info/1056/10616.htm'),('2026年校级拟录取名单（含038/039附件）','https://gs.ccnu.edu.cn/info/1028/6263.htm'),('2027年招生考试调整通知','https://gs.ccnu.edu.cn/info/1028/6773.htm')]
            for title,url in known:
                if not any(x['url']==url for x in row['documents']): row['documents'].append(dict(title=title,url=url,discovery_file='docs/MANUAL-DOWNLOAD-CHECKLIST.md'))
            row['eligibility']='2027合并公告确认人工智能教育学部081200为11408；仍以正式目录为准'
        row['documents'].extend(linked_announcements(row['documents'],row['domain']))
        for doc in row['documents']:
            year,category=classify(doc['title']);doc.update(year=year,category=category,save_to=str(base/str(year)/category) if year and category in CATEGORIES else str(base/'待分类'),status=doc.get('status','搜索发现（原页待核验）'))
        row['documents'].sort(key=lambda d:(-(d['year'] or 0),d['category'],d['title']))
        (base/'待分类').mkdir(exist_ok=True)
        data.append(row)
    if verify:
        with ThreadPoolExecutor(max_workers=8) as pool:
            jobs={pool.submit(inspect_page,d,s['domain']):d for s in data for d in s['documents'] if not d.get('discovered_on')}
            for n,future in enumerate(as_completed(jobs),1):
                jobs[future].update(future.result())
                if n%40==0:print(json.dumps({'pages_checked':n,'total':len(jobs)}),flush=True)
    else:
        for s in data:
            for doc in s['documents']:
                meta=EVIDENCE/'pages'/(hashlib.sha256(doc['url'].encode()).hexdigest()+'.json')
                if meta.exists():doc.update(json.loads(meta.read_text(encoding='utf-8')))
    counts={'schools':len(data),'searched':sum((EVIDENCE/'search'/(s['sch_id']+'.json')).exists() for s in data),'schools_with_document_links':sum(bool(s['documents']) for s in data),'document_links':sum(len(s['documents']) for s in data)}
    payload=dict(updated_at=NOW(),scope='现有148所入口候选，不是全国全部11408院校',counts=counts,schools=data)
    DOWNLOADS.mkdir(exist_ok=True)
    (DOWNLOADS/'下载索引.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    for s in data:
        lines=[f"# {s['name']} 下载清单",'',s['eligibility'],'',f"保存根目录：`{s['folder']}`",'', '先核验2027科目；再补对应院系2026→2025→2024历史资料。没有原始PDF的正文可另存网页或打印PDF。不要把博士/推免目录当统考目录。','','|资料|年度|打开页面|存入目录|链接状态|','|---|---|---|---|---|']
        for d in s['documents']:
            title=d['title'].replace('|',' '); lines.append(f"|{title}|{d['year'] or '需核对'}|[官网页面]({d['url']})|`{d['save_to']}`|{d['status']}|")
        if not s['documents']:lines.extend(['','尚未定位具体资料链接；请勿把入口页当作已齐全的下载任务。'])
        lines.extend(['',f"[研招网学校入口]({s['chsi']})",'', '## 每校验收项目','', '- 2027：统考目录/简章、调整通知、计划/推免口径。','- 2026、2025、2024：目录/计划、相关院系复试规则、入围、成绩、拟录取、更正/补录、调剂（如有）。','- 有链接仅代表发现线索；下载后核对院系、年份、正文与附件。缺失不能直接判未发布。'])
        (Path(s['folder'])/'下载清单.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    overview=['# 院校资料下载总表','',f"更新时间：{payload['updated_at']}",'','现有148所入口候选；不等于148所均满足11408。每个资料链接都是原始官网链接或从官网HTML发现的链接，不保证所有附件已发布或仍能打开。','','[打开可筛选下载导航](下载导航.html)','','|学校|逐项下载清单|链接数量|2027资格|','|---|---|---|---|']
    for s in data:
        relative=Path(s['folder']).name
        overview.append(f"|{s['name']}|[下载清单](<{relative}/下载清单.md>)|{len(s['documents'])}|{s['eligibility']}|")
    (DOWNLOADS/'下载总表.md').write_text('\n'.join(overview)+'\n',encoding='utf-8')
    gaps=['# 尚待补查的资料链接','', '以下按公告标题自动分类，仅表示链接类别覆盖，不是文件完备性结论。即使某类别已有链接，也可能只含部分院系或专项。尚未找到不等于未发布。','','|学校|缺少对应标题链接的类别|','|---|---|']
    for s in data:
        present={(d['year'],d['category']) for d in s['documents']}
        expected=[(y,c) for y in YEARS for c in CATEGORIES if not (y==2027 and c in CATEGORIES[2:])]
        missing=[str(y)+' '+c[2:] for y,c in expected if (y,c) not in present]
        gaps.append('|'+s['name']+'|'+('；'.join(missing) or '主类别已有链接，仍需核验院系/附件覆盖')+'|')
    (DOWNLOADS/'待补链接清单.md').write_text('\n'.join(gaps)+'\n',encoding='utf-8')
    render_html(payload)
    print(json.dumps(counts,ensure_ascii=False),flush=True)

def render_html(payload):
    cards=[]
    esc=lambda x:html.escape(str(x),quote=True)
    for s in payload['schools']:
        docs=[]
        for d in s['documents']:
            ident=hashlib.sha256((s['sch_id']+d['url']).encode()).hexdigest()[:20]
            docs.append(f'<article><label><input type="checkbox" data-id="{ident}">我已保存（尚未经助手验收）</label><h3><a target="_blank" rel="noopener noreferrer" href="{esc(d["url"])}">{esc(d["title"])}</a></h3><p>{esc(d["category"])} · {esc(d["status"])}</p><code>{esc(d["save_to"])}</code></article>')
        body=''.join(docs) or '<p class="warning">本轮未定位具体资料链接；仍需查找，不能记为不招生或资料齐全。</p>'
        portal=f'<a target="_blank" rel="noopener noreferrer" href="{esc(s["portal"])}">此前核验的官网入口</a> · ' if s['portal'] else ''
        cards.append(f'<details data-school="{esc(s["name"])}"><summary>{esc(s["name"])} <small>{len(s["documents"])} 个资料/栏目链接</small></summary><p class="warning">{esc(s["eligibility"])}</p><p>{portal}<a target="_blank" rel="noopener noreferrer" href="{esc(s["chsi"])}">研招网学校入口</a></p><code>{esc(s["folder"])}</code>{body}</details>')
    document='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>11408 院校资料下载导航</title><style>body{font:16px/1.65 system-ui,sans-serif;background:#f3f5f7;color:#182638;max-width:1120px;margin:32px auto;padding:0 22px}header{position:sticky;top:0;background:#f3f5f7;padding:12px 0;z-index:1}h1{font-size:27px;margin:0}input[type=search]{width:100%;box-sizing:border-box;padding:12px;border:1px solid #adb9c8;border-radius:8px}details{background:white;margin:12px 0;padding:18px;border:1px solid #d9e0e9;border-radius:10px}summary{cursor:pointer;font-weight:650}small{font-weight:400;color:#526478;margin-left:16px}article{border-top:1px solid #e2e7ed;padding:14px 0}h3{font-size:16px;margin:6px 0}a{color:#1259a5}code{font-size:13px;overflow-wrap:anywhere}label{font-size:13px;color:#526478}.warning{color:#925a00}p{margin:8px 0}button{padding:8px 14px;margin:8px 5px 0 0;border:1px solid #adb9c8;background:white;border-radius:6px;cursor:pointer}</style><header><h1>11408 院校资料下载导航</h1><p>2027 入学 · 学硕/专硕均可 · 手动下载，助手验收</p><input id="search" type="search" placeholder="输入学校名筛选"><button id="export">导出我的勾选进度</button><span id="saved"></span></header>'''
    document+=f'<p>覆盖现有 {payload["counts"]["schools"]} 所候选，已检索 {payload["counts"]["searched"]} 所；{payload["counts"]["schools_with_document_links"]} 所有资料或栏目链接。不是全国全部11408名单，链接数量不代表材料齐全。</p><p>先下载2027目录确认201/301/408，再下载对应院系2026→2025→2024的目录、计划、复试规则、入围/成绩/拟录取及更正公告。网页文字可另存网页或打印PDF；保留原始文件名。</p><p>点击标题逐项打开；没有自动批量开窗或下载。链接可能失效，访问失败不等于学校未发布。勾选仅是个人记录，文件完整性另行验收。</p>'+''.join(cards)
    document+='''<script>const key='gradheat-manual-download-v1';let state={};try{state=JSON.parse(localStorage.getItem(key)||'{}')}catch(e){}function count(){document.getElementById('saved').textContent=Object.values(state).filter(Boolean).length+' 项已标记保存'}document.querySelectorAll('[data-id]').forEach(x=>{x.checked=!!state[x.dataset.id];x.addEventListener('change',()=>{state[x.dataset.id]=x.checked;try{localStorage.setItem(key,JSON.stringify(state))}catch(e){}count()})});count();document.getElementById('search').addEventListener('input',e=>{document.querySelectorAll('details').forEach(d=>{d.hidden=!d.dataset.school.includes(e.target.value.trim())})});document.getElementById('export').onclick=()=>{const b=new Blob([JSON.stringify({exported_at:new Date().toISOString(),scope:'user_checkmarks_not_file_verification',checks:state},null,2)],{type:'application/json'});const a=document.createElement('a');a.href=URL.createObjectURL(b);a.download='下载勾选进度.json';a.click();URL.revokeObjectURL(a.href)};</script></html>'''
    (DOWNLOADS/'下载导航.html').write_text(document,encoding='utf-8')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--verify-pages',action='store_true');build(p.parse_args().verify_pages)
