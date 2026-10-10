"""Recover public sources using Windows' verified certificate store.

No insecure TLS option, authentication, or challenge bypass is used. Failed
requests observations remain in their original cache; new bytes are hashed.
"""
from collections import Counter
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import re
import subprocess
from urllib.parse import urljoin
from bs4 import BeautifulSoup
import build_download_index as base
import build_unit_dossiers as d
import refresh_dossier_sources as r
import collect_gap_round2 as batch

BATCH = batch.BATCH

def verified_curl(task):
    key = hashlib.sha256((task['unit']+'\n'+task['url']).encode()).hexdigest()
    temp = BATCH/'tls-temp'/(key+'.part')
    temp.parent.mkdir(parents=True, exist_ok=True)
    rec = {k:v for k,v in task.items() if k!='unit_info'}
    rec.update(retrieved_at=datetime.now(timezone.utc).isoformat(),
               transport='curl-schannel-system-trust', source_tier='primary',
               status='fetch-failed')
    try:
        proc = subprocess.run(['curl.exe','--fail','--location','--silent',
            '--show-error','--max-time','25','--max-filesize','15000000',
            '--user-agent','Mozilla/5.0','--output',str(temp),
            '--write-out','%{http_code}\n%{url_effective}\n%{content_type}\n%{ssl_verify_result}',
            task['url']],capture_output=True,timeout=30)
        # Windows curl diagnostics may use the system codepage even when the
        # Python parent runs in UTF-8 mode. Keep pipes as bytes so a localized
        # error cannot crash an otherwise resumable multi-school batch.
        fields = (proc.stdout or b'').decode('utf-8',errors='replace').splitlines()
        if proc.returncode or len(fields)!=4:
            rec['error'] = (proc.stderr or b'').decode('utf-8',errors='replace')[:400]
            return rec
        status, final, content_type, tls = fields
        rec.update(http_status=int(status), final_url=final, content_type=content_type,
                   tls_verify_result=int(tls))
        if status!='200' or tls!='0' or not r.allowed(final,task['unit_info']):
            rec['status']='response-rejected'
            return rec
        data=temp.read_bytes(); sha=hashlib.sha256(data).hexdigest()
        ext='.pdf' if data.startswith(b'%PDF') else '.html' if 'html' in content_type else '.bin'
        path=BATCH/'live-raw'/(key+'-'+sha[:12]+ext)
        path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
        rec.update(raw_path=str(path),sha256=sha,bytes=len(data),retained=True,
                   status='html-saved' if ext=='.html' else 'file-saved')
        if ext=='.html':
            soup=BeautifulSoup(base.decode_html(data),'html.parser')
            title=soup.title.get_text(' ',strip=True) if soup.title else ''
            rec['live_title']=title
            if re.search(r'验证码|安全验证|访问太频繁|Access Denied',title,re.I):
                rec.update(status='verification-page',retained=False)
            elif re.search(r'WebVPN',title,re.I):
                rec.update(status='access-gateway',retained=False)
            else:
                main=soup.select_one('.v_news_content, #vsb_content, .TRS_Editor, .wp_articlecontent, article, main') or soup.body or soup
                tp=path.with_suffix('.txt');tp.write_text(main.get_text('\n',strip=True),encoding='utf8');rec['text_path']=str(tp)
        elif ext=='.pdf':
            import pymupdf
            with pymupdf.open(path) as pdf:
                text='\n'.join(p.get_text() for p in pdf);rec['pages']=len(pdf)
            tp=path.with_suffix('.txt');tp.write_text(text,encoding='utf8');rec['text_path']=str(tp)
        return rec
    except (OSError,subprocess.TimeoutExpired) as exc:
        rec['error'] = type(exc).__name__
        return rec
    finally:
        temp.unlink(missing_ok=True)

def run():
    corpus={u['name']:u for u in d.read(d.ROOT/'.research/manual-downloads/全量采集资料.json')['units']}
    current={(x['unit'],x['url']):x for x in d.read(BATCH/'sources.json')}
    queue={}
    for key,x in current.items():
        if 'SSLError' in x.get('error',''):
            queue[key]={k:x.get(k) for k in ['unit','url','title','year','discovered_on']}
    for x in d.read(BATCH/'tls-observed-tasks.json',[]):queue[(x['unit'],x['url'])]=x
    observations=[];seen=set();old_work=d.WORK;d.WORK=BATCH
    try:
        for depth in range(3):
            tasks=[x for k,x in queue.items() if k not in seen]
            if not tasks:break
            for task in tasks:
                key=(task['unit'],task['url']);seen.add(key)
                task=dict(task,unit_info=corpus[task['unit']])
                rec=verified_curl(task) if key in current and 'SSLError' in current[key].get('error','') else r.fetch(task)
                if 'SSLError' in rec.get('error',''):rec=verified_curl(task)
                rec['source_tier']='primary';observations.append(rec)
                if rec.get('status') in ('html-saved','file-saved') or key not in current:current[key]=rec
                print(task['unit'],rec['status'],task['url'],flush=True)
                if depth<2:
                    for t in batch.follow(rec,corpus[task['unit']]):
                        tk=(t['unit'],t['url'])
                        if tk not in current:queue.setdefault(tk,t)
        d.dump(BATCH/'tls-recovery-observations.json',observations)
        d.dump(BATCH/'sources.json',list(current.values()))
    finally:d.WORK=old_work
    merged={(x['unit'],x['url']):x for x in d.read(old_work/'live-sources.json')}
    for key,x in current.items():
        if x.get('status') in ('html-saved','file-saved') or key not in merged:merged[key]=x
    d.dump(old_work/'live-sources.json',list(merged.values()))
    print(dict(observations=len(observations),states=dict(Counter(x['status'] for x in observations))))

if __name__=='__main__':run()
