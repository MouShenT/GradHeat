"""Locate non-personal facts in already retained original admissions tables."""
from __future__ import annotations
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from bs4 import BeautifulSoup
import build_unit_dossiers as d

def provider_html(path):
    x=d.read(path,{})
    result=x.get('result',{})
    blocks=result.get('content',[]) if isinstance(result,dict) else []
    for b in blocks:
        if b.get('type')!='text':continue
        try:
            data=json.loads(b['text'])
            if data.get('html') or data.get('rawHtml'):return data.get('html') or data.get('rawHtml')
        except (ValueError,TypeError):pass
    return ''

def rawhtml(doc):
    p=doc.get('raw_path')
    if not p or not Path(p).is_file():return ''
    p=Path(p)
    if p.suffix=='.json':return provider_html(p)
    if p.suffix!='.html':return ''
    import build_download_index as base
    return base.decode_html(p.read_bytes())

def grid(table):
    output=[];spans={}
    for tr in table.find_all('tr'):
        row=[];col=0
        def carried():
            nonlocal col
            while col in spans:
                value,n=spans[col];row.append(value)
                if n>1:spans[col]=(value,n-1)
                else:del spans[col]
                col+=1
        carried()
        for c in tr.find_all(['td','th'],recursive=False):
            carried();v=c.get_text(' ',strip=True)
            for _ in range(min(int(str(c.get('colspan',1)).strip() or 1),25)):
                row.append(v)
                n=min(int(str(c.get('rowspan',1)).strip() or 1),100)
                if n>1:spans[col]=(v,n-1)
                col+=1
        carried();output.append(row)
    return output

def starts_data(row):
    # A school-wide table can begin with philosophy or chemistry. Those rows
    # are data too; do not absorb their scores into the computing table header.
    if any(re.search(r'(?<!\d)(?:0[1-9]|1[0-6])\d{2}(?:[0-9A-Z]{2})?(?!\d)', re.sub(r'\s', '', c)) for c in row) or any(d.COMPUTING.search(c) for c in row):return True
    # Some first disciplines have only a name, without a code (e.g. telecom).
    # Multiple explicit numerical cells indicate data unless the row also
    # contains an actual column label, such as a maximum-score header.
    clean=[re.sub(r'\s','',c) for c in row]
    labels=r'专业(?:名称|代码)?|学科或专业|学科专业|报考专业|政治|英语|外语|总分|科目[一二三四]|业务课[一二12]|招生计划|录取人数'
    return sum(bool(re.fullmatch(r'\d{2,4}',c)) for c in clean)>=2 and not any(re.fullmatch(labels,c) for c in clean)

def computing_row(row):
    return any(d.COMPUTING.search(c) or re.search(r'0812|0835|0839|08540[45]|08541[012]', re.sub(r'\s', '', c)) for c in row)

def extract():
    units={u['name']:u for u in d.read(d.ROOT/'.research/manual-downloads/全量采集资料.json')['units']}
    facts=[];programs=[];dedup=set();counter=Counter()
    for entry in d.priority.load():
        u=units[entry['name']]
        secondary={y:d.secondary_rows(u,y) for y in (2026,2025)}
        for doc in d.docs_for(u):
            if doc.get('source_tier')!='primary' or not doc['retained'] or d.BLOCK.search(doc['title']):continue
            if d.source_score(doc,u,doc['year'])<14:continue
            html=rawhtml(doc)
            if html:
                soup=BeautifulSoup(html,'html.parser')
                for tn,t in enumerate(soup.find_all('table')):
                    rows=grid(t)
                    if not rows or len(rows)>300:continue
                    header=[];data_start=0
                    for i,row in enumerate(rows[:6]):
                        if starts_data(row):data_start=i;break
                        header.append(row);data_start=i+1
                    width=max((len(x) for x in header),default=0)
                    headings=['／'.join(dict.fromkeys(row[i] for row in header if i<len(row) and row[i])) for i in range(width)]
                    ht=' '.join(headings)
                    if not re.search(r'总分|分数线',ht) or re.search(r'考生|姓名|编号|初试成绩|复试成绩|录取总成绩',ht):continue
                    if doc['year'] not in (2026,2025):continue
                    for rn,row in enumerate(rows[data_start:],data_start):
                        if len(row)!=width or not computing_row(row):continue
                        nums=[i for i,v in enumerate(row) if re.fullmatch(r'\d{2,3}',re.sub(r'\s','',v)) and re.search(r'总分|科目|业务|政治|外语|英语|单科|分数',headings[i])]
                        if not nums:continue
                        label='；'.join(f'{headings[i]}：{v}' if headings[i] else v for i,v in enumerate(row) if i not in nums and v)
                        key=(u['name'],doc['year'],tuple(row),tuple(headings))
                        if key in dedup:continue
                        dedup.add(key)
                        total=[re.sub(r'\s','',row[i]) for i in nums if re.search(r'总分|分数线',headings[i]) and re.fullmatch(r'[2345]\d\d',re.sub(r'\s','',row[i]))]
                        comparison='尚未取得同口径第二来源'
                        if total:
                            matches=[]
                            for s in secondary[doc['year']]:
                                major=s['fields'].get('专业名称') or ''
                                root=re.sub(r'\s|（.*?）|\(.*?\)|\d','',major)
                                line=s['fields'].get('分数线') or ''
                                if root and (root in label or any(w in root and w in label for w in ['计算机科学与技术','计算机技术','软件工程','网络空间安全','人工智能','电子信息'])) and re.search(r'(?<!\d)'+re.escape(total[0])+r'(?!\d)',line):
                                    matches.append(s['source_url'])
                            if matches:comparison='总分与第三方同专业名称记录吻合；专项/院系范围及来源独立性待核'
                        facts.append(dict(unit=u['name'],year=doc['year'],source_title=doc['title'],label=label,headers=[headings[i] for i in nums],values=[row[i] for i in nums],source_url=doc['url'],source_artifact=doc.get('raw_path'),locator=f'HTML table[{tn}] row[{rn}]（从0计数；展开合并单元格）',comparison=comparison))
                counter['html_sources']+=1
            # Locate PDF program pages without claiming OCR numerics are verified.
            raw=doc.get('raw_path')
            if doc['year']==2027 and raw and Path(raw).suffix=='.pdf' and re.search(r'专业目录|招生专业|考试科目|招生简章',doc['title']):
                try:
                    import pymupdf
                    with pymupdf.open(raw) as pdf:
                        found=0
                        for pn,page in enumerate(pdf):
                            text=page.get_text()
                            if not d.COMPUTING.search(text) or ('408' not in text and '0812' not in text and '0854' not in text):continue
                            # Preserve line boundaries, page number and a small bounded context.
                            lines=text.splitlines();anchors=[i for i,s in enumerate(lines) if re.search(r'计算机科学与技术|计算机技术|软件工程|网络空间安全|人工智能',s)]
                            snippets=[]
                            for a in anchors[:3]:snippets.append('\n'.join(lines[max(0,a-2):min(len(lines),a+14)]))
                            if snippets:programs.append(dict(unit=u['name'],year=2027,title=doc['title'],source_url=doc['url'],source_artifact=raw,page=pn+1,excerpts=snippets,verification='原始PDF文本定位；列对齐和数值待回看原页'))
                            found+=1
                            if found>=8:break
                    counter['pdf_catalogues']+=1
                except Exception as e:counter['pdf_errors']+=1
    d.dump(d.WORK/'official-table-facts.json',facts);d.dump(d.WORK/'catalogue-page-evidence.json',programs)
    print(json.dumps(dict(table_rows=len(facts),table_units=len(set(f['unit'] for f in facts)),pdf_pages=len(programs),pdf_units=len(set(p['unit'] for p in programs)),counts=dict(counter)),ensure_ascii=False))

if __name__=='__main__':extract()
