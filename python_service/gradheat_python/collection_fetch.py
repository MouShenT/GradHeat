"""Public, bounded acquisition with immutable per-request checkpoints."""
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import time
from urllib.parse import urljoin, urlsplit, urlunsplit
import requests
from bs4 import BeautifulSoup
from .collection_plan import write_json


def allowed_url(url, domains, *, resolve=True):
    p=urlsplit(url)
    if p.scheme not in ('http','https') or not p.hostname or p.username or p.password or p.port not in (None,80,443):
        raise ValueError('Only public HTTP URLs are accepted')
    host=p.hostname.lower()
    if not any(host==d or host.endswith('.'+d) for d in domains):
        raise ValueError('URL outside approved institution domains')
    if re.search(r'(?:^|&)(?:token|sign|signature|password|cookie|authorization)=',p.query,re.I):
        raise ValueError('Session URLs are not collection sources')
    if resolve:
        addresses=socket.getaddrinfo(host,p.port or (443 if p.scheme=='https' else 80),type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
            raise ValueError('Source resolves to a private address')
    return urlunsplit((p.scheme,p.netloc,p.path,p.query,''))


def browser_public(url, domains, limit):
    # A new unauthenticated context; never connects to the shared login browser.
    from playwright.sync_api import sync_playwright
    executable=os.getenv('GRADHEAT_PUBLIC_CHROME')
    if not executable and os.name=='nt':
        executable=r'C:\Program Files\Google\Chrome\Application\chrome.exe'
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True,**({'executable_path':executable} if executable else {}))
        context=browser.new_context(accept_downloads=False)
        try:
            def route(req):
                try: allowed_url(req.request.url,domains)
                except (ValueError,OSError): req.abort();return
                req.continue_()
            context.route('**/*',route)
            page=context.new_page();page.goto(url,wait_until='domcontentloaded',timeout=30000)
            page.wait_for_timeout(1500)
            allowed_url(page.url,domains)
            content=page.content().encode('utf-8')
            if len(content)>limit: raise ValueError('Rendered page over byte budget')
            return content,page.url,'text/html; charset=utf-8'
        finally:
            context.close();browser.close()


def fetch(url, domains, folder, policy):
    url=allowed_url(url,domains)
    key=hashlib.sha256(url.encode()).hexdigest()
    meta=folder/(key+'.json')
    marker=folder/(key+'.request')
    if meta.exists():
        item=json.loads(meta.read_text(encoding='utf-8'))
        if item.get('raw_path'):
            raw=Path(item['raw_path']).resolve()
            if not raw.is_relative_to(folder.resolve()) or not raw.is_file() or hashlib.sha256(raw.read_bytes()).hexdigest()!=item['sha256']:
                raise ValueError('Frozen acquisition original changed')
        return item
    if marker.exists():
        return {'url':url,'state':'interrupted-request','requires_review':True,'request_history':'unknown'}
    folder.mkdir(parents=True,exist_ok=True)
    marker.write_text('Public request started; missing receipt is not permission to refetch.',encoding='utf-8')
    result={'url':url,'observed_at':__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(),
        'route':'public-http','issuer_verified':False}
    try:
        current=url;raw=None;content_type=''
        for n in range(6):
            allowed_url(current,domains)
            with requests.get(current,timeout=(8,policy['timeout_seconds']),stream=True,allow_redirects=False,
                    headers={'User-Agent':'GradHeat-Research/1.0 (public admissions collection)'}) as r:
                if r.status_code in (301,302,303,307,308):
                    current=urljoin(current,r.headers.get('Location',''));continue
                if r.status_code in (403,412) and policy.get('browser_fallback'):
                    raw,current,content_type=browser_public(current,domains,policy['max_file_bytes'])
                    result['route']='isolated-public-browser';break
                if r.status_code in (401,403,412,429):
                    result.update(state='needs-human',http_status=r.status_code);break
                r.raise_for_status();content_type=r.headers.get('Content-Type','')
                chunks=[];size=0
                for chunk in r.iter_content(65536):
                    size+=len(chunk)
                    if size>policy['max_file_bytes']: raise ValueError('Original over byte budget')
                    chunks.append(chunk)
                raw=b''.join(chunks);break
        if raw is None:
            if 'state' not in result: result['state']='redirect-budget-exhausted'
        else:
            result.update(final_url=current,content_type=content_type)
            is_html='html' in content_type.lower() or raw.lstrip().lower().startswith((b'<!doctype html',b'<html'))
            text='';links=[]
            if is_html:
                soup=BeautifulSoup(raw,'html.parser')
                title=soup.title.get_text(' ',strip=True) if soup.title else ''
                if re.search(r'验证码|安全验证|访问太频繁|Access Denied|WebVPN|统一身份认证|用户登录|账号登录|登录系统',title,re.I):
                    result.update(state='needs-human',title=title);write_json(meta,result);return result
                body=soup.get_text(' ',strip=True)
                if len(body)<1000 and re.search(r'请完成.*验证|拖动.*滑块|verify_check|安全检测',body,re.I):
                    result.update(state='needs-human',title=title);write_json(meta,result);return result
                result['title']=title
                for hidden in soup(['script','style']):hidden.decompose()
                text=soup.get_text('\n',strip=True)
                if len(text.strip())<40:
                    result.update(content_valid=False,reason='empty-or-shell-html')
                for a in soup.select('a[href]'):
                    try: linked=allowed_url(urljoin(current,a['href']),domains,resolve=False)
                    except ValueError: continue
                    label=a.get_text(' ',strip=True)
                    if any(term in label for term in policy['link_terms']) or re.search(r'\.(pdf|docx?|xlsx?|zip)(?:\?|$)',linked,re.I) or re.search(r'下一页|下页|next',label,re.I):
                        links.append({'url':linked,'label':label})
                content=soup.select_one('article,.v_news_content,#vsb_content,.TRS_Editor,.wp_articlecontent') or soup
                for media in content.select('img[src],iframe[src],embed[src],object[data]'):
                    try:linked=allowed_url(urljoin(current,media.get('src') or media.get('data')),domains,resolve=False)
                    except (ValueError,TypeError):continue
                    if re.search(r'\.(pdf|png|jpe?g|webp|gif)(?:\?|$)',linked,re.I):
                        links.append({'url':linked,'label':'公开原页内嵌资料/图片，待后续核对'})
            sha=hashlib.sha256(raw).hexdigest()
            suffix='.html' if is_html else '.pdf' if raw.startswith(b'%PDF') else Path(urlsplit(current).path).suffix.lower()
            if suffix not in ('.pdf','.html','.doc','.docx','.xls','.xlsx','.zip','.png','.jpg','.jpeg','.webp','.gif','.txt'):
                suffix='.bin'
            path=folder/(sha+suffix);path.write_bytes(raw)
            result.update(state='fetched' if raw and result.get('content_valid',True) else 'invalid-content',raw_path=str(path),sha256=sha,byte_size=len(raw),links=links[:500])
            if suffix=='.zip' and not raw.startswith((b'PK\x03\x04',b'PK\x05\x06')):result.update(state='invalid-content',reason='invalid-archive-format')
            if suffix=='.pdf':
                try:
                    import pymupdf
                    with pymupdf.open(path) as pdf:
                        result['pages']=len(pdf)
                        text='\n'.join(pdf[n].get_text() for n in range(min(len(pdf),200)))
                        result['transcription_truncated']=len(pdf)>200
                        result['images_need_review']=len(text.strip())<50
                except Exception as e:result['transcription_error']=type(e).__name__
            if text:
                tp=folder/(sha+'.txt');tp.write_text(text[:800000],encoding='utf-8')
                result.update(text_path=str(tp),transcription_truncated=result.get('transcription_truncated',False) or len(text)>800000)
            elif suffix!='.html':result['unparsed_original']=True
    except Exception as e:
        result.update(state='failed',error_type=type(e).__name__)
        if isinstance(e,ValueError) and str(e) in ('Original over byte budget','Rendered page over byte budget'):
            result['reason']='file-too-large'
    write_json(meta,result)
    return result


def official(unit, folder, policy, keywords, deadline):
    manifest=folder/'manifest.json'
    if manifest.exists():
        return json.loads(manifest.read_text(encoding='utf-8'))
    folder.mkdir(parents=True,exist_ok=True)
    progress=folder/'progress.json'
    if progress.exists():
        checkpoint=json.loads(progress.read_text(encoding='utf-8'));queue=checkpoint['queue'];seen=set(checkpoint['seen']);rows=checkpoint['documents']
    else:
        queue=[{'url':u,'depth':0} for u in unit['urls']];seen=set();rows=[]
    limits=dict(policy,link_terms=keywords['official_link_terms'])
    while queue and len(rows)<policy['max_pages_per_unit'] and time.monotonic()<deadline:
        task=queue.pop(0);url=task['url']
        if url in seen:continue
        try:
            item=fetch(url,unit['domains'],folder/'raw',limits)
        except (ValueError,OSError) as e:
            item={'url':url,'state':'not-requested-invalid-source','error_type':type(e).__name__}
        seen.add(url);rows.append(dict(item,unit=unit['name'],depth=task['depth']))
        if item.get('state')=='needs-human':
            # Continue independent URLs without repeatedly hitting a gated host.
            blocked=(urlsplit(url).hostname or '').lower()
            gated=[q for q in queue if (urlsplit(q['url']).hostname or '').lower()==blocked]
            queue=[q for q in queue if q not in gated]
            for q in gated:
                seen.add(q['url']);rows.append({'url':q['url'],'state':'not-requested-site-blocked','unit':unit['name'],'depth':q['depth']})
        if item.get('state')=='fetched' and task['depth']<policy['max_depth']:
            queue.extend({'url':link['url'],'depth':task['depth']+1} for link in item.get('links',[]) if link['url'] not in seen)
        write_json(progress,{'queue':queue,'seen':sorted(seen),'documents':rows})
        time.sleep(policy['host_interval_seconds'])
    failed=any(r.get('state')!='fetched' for r in rows)
    result={'unit':unit['name'],'state':'needs-human' if any(r.get('state')=='needs-human' for r in rows) else 'collected' if not queue and not failed else 'partial','documents':rows,
        'scope_complete':not queue and not failed,'page_budget_reached':bool(queue) and len(rows)>=policy['max_pages_per_unit'],
        'deadline_reached':bool(queue) and time.monotonic()>=deadline}
    if not unit['urls']:result.update(state='missing-entry-url',scope_complete=False)
    if not result['deadline_reached']:write_json(manifest,result)
    return result
