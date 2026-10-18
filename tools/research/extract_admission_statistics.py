"""Compute aggregates from explicit original roster columns, keeping pools split.

Results are extraction candidates pending original-page and completeness review.
Identifiers are used transiently for row deduplication and are not exported.
"""
from __future__ import annotations
import hashlib
import json
import re
import statistics
from collections import defaultdict, Counter
from pathlib import Path
from bs4 import BeautifulSoup
import pymupdf
import build_unit_dossiers as d
import extract_dossier_evidence as evidence

def clean(s):return re.sub(r'\s+','',str(s or ''))

def table_header(rows):
    for row in rows[:5]:
        c=[clean(x) for x in row]
        if any(re.search(r'初试(?:总分|成绩|总成绩)',x) for x in c) and any('考生' in x or '姓名' in x for x in c):return c
    return None

def deduplicate_records(records):
    """Only a complete identifier can establish that two rows are one person."""
    unique={}
    for row in records:
        if row['identifier_masked']:
            # Repeated masks can denote different applicants, even at equal scores.
            key=('row',row['locator'])
        else:
            key=('identifier',row['identifier_hash'])
            previous=unique.get(key)
            if previous and any(previous[field]!=row[field] for field in ('score','pool','special')):
                raise ValueError('Conflicting roster rows require original-page review')
        unique.setdefault(key,row)
    return list(unique.values())


def parse_table(rows, doc, tableloc):
    result=[]
    if not rows:return result
    header=None;start=0
    for i,row in enumerate(rows[:5]):
        cells=[clean(x) for x in row]
        if any(re.search(r'初试(?:总分|成绩|总成绩)',x) for x in cells) and any('考生' in x or '姓名' in x for x in cells):header=cells;start=i+1;break
    if not header:return result
    scorecols=[i for i,h in enumerate(header) if re.search(r'初试(?:总分|成绩|总成绩)',h)]
    idcols=[i for i,h in enumerate(header) if re.search(r'考生(?:编号|号)|准考证',h)]
    if len(scorecols)!=1 or len(idcols)!=1:return result
    si=scorecols[0];ii=idcols[0]
    groupcols=[i for i,h in enumerate(header) if re.search(r'专业|方向|学习方式|录取类型|录取类别|复试组|院系|学院|培养单位|招生单位',h) and not re.search(r'专业课|成绩|是否',h)]
    remarks=[i for i,h in enumerate(header) if '备注' in h or '专项' in h]
    flagcols=[i for i,h in enumerate(header) if re.fullmatch(r'是否(?:被)?(?:拟|建议)?录取|(?:拟)?录取(?:状态|结果)',h)]
    state={}
    for rn,row in enumerate(rows[start:],start):
        if len(row)!=len(header):continue
        c=[clean(x) for x in row]
        identifier=c[ii]
        if not re.fullmatch(r'[0-9*＊xX]{12,20}',identifier):continue
        if not re.fullmatch(r'[1-4]\d\d(?:\.0+)?|500',c[si]):continue
        if flagcols and not all(re.fullmatch(r'(?:是|(?:拟|建议|同意)?录取)(?:[（(][^）)]*[）)])?',c[i]) for i in flagcols):continue
        for i in groupcols:
            if c[i]:state[i]=c[i]
            elif i in state:c[i]=state[i]
        pool='；'.join(f'{header[i]}：{c[i] or "未注明"}' for i in groupcols) or '原文未分专业／类别'
        if groupcols and any('专业' in header[i] for i in groupcols) and not d.COMPUTING.search(pool) and not re.search(r'0812|0835|0839|0854|1405',pool):continue
        remarks_text='；'.join(c[i] for i in remarks if c[i])
        special=remarks_text if re.search(r'士兵|骨干|少干|专项|强军|单考|单独考试|少民|退役|加分|立功',remarks_text) else '强军计划（方向注明）' if '强军' in pool else '备注未标专项（仍需复核类别）'
        result.append(dict(identifier_hash=hashlib.sha256(identifier.encode()).hexdigest(),identifier_masked=not identifier.isdigit(),score=float(c[si]),pool=pool,special=special,locator=f'{tableloc} row[{rn}]',score_header=header[si]))
    return result

def run():
    units={u['name']:u for u in d.read(d.ROOT/'.research/manual-downloads/全量采集资料.json')['units']}
    output=[];seen=set();table_seen=set();counter=Counter()
    for entry in d.priority.load():
        u=units[entry['name']]
        selected=[]
        for doc in d.docs_for(u):
            if doc['year'] not in (2026,2025) or doc.get('source_tier')!='primary' or not doc['retained'] or d.BLOCK.search(doc['title']):continue
            text=d.textfile(doc.get('text_path'))
            heading=text[:1500]
            if not re.search(r'拟录取|是否拟录取|建议录取',doc['title']+' '+heading):continue
            if not re.search(r'硕士',doc['title']+' '+heading):continue
            if not d.COMPUTING.search(doc['title']+' '+heading) and u['group']!='研究所':continue
            raw=doc.get('raw_path')
            if not raw or not Path(raw).is_file():continue
            digest=hashlib.sha256(Path(raw).read_bytes()).hexdigest()
            if (u['name'],digest) in seen:continue
            seen.add((u['name'],digest));selected.append((doc,digest))
        # Extract all eligible small original rosters; large whole-university
        # files stay in the retained corpus for a dedicated schema review.
        for doc,digest in selected:
            raw=Path(doc['raw_path']);records=[]
            try:
                if raw.suffix in ('.html','.json'):
                    soup=BeautifulSoup(evidence.rawhtml(doc),'html.parser')
                    for tn,t in enumerate(soup.find_all('table')):records+=parse_table(evidence.grid(t),doc,f'HTML table[{tn}]')
                    counter['html']+=1
                elif raw.suffix=='.pdf':
                    with pymupdf.open(raw) as pdf:
                        if len(pdf)>35:counter['large_pdf_deferred']+=1;continue
                        inherited_header=None
                        for pn,page in enumerate(pdf):
                            for tn,t in enumerate(page.find_tables().tables):
                                rows=t.extract();head=table_header(rows)
                                if head:inherited_header=head
                                elif inherited_header and rows and len(rows[0])==len(inherited_header):
                                    # Continuation requires a plausible identifier at the
                                    # same column; unrelated same-width tables are rejected.
                                    ids=[i for i,h in enumerate(inherited_header) if re.search(r'考生(?:编号|号)|准考证',h)]
                                    if len(ids)==1 and re.fullmatch(r'[0-9*＊xX]{12,20}',clean(rows[0][ids[0]])):
                                        rows=[inherited_header]+rows;counter['continued_tables']+=1
                                records+=parse_table(rows,doc,f'PDF page[{pn+1}] table[{tn}]')
                    counter['pdf']+=1
                else:continue
            except Exception as ex:
                counter['parse_errors']+=1;continue
            try:
                dedup=deduplicate_records(records)
            except ValueError:
                counter['conflicting_rosters_deferred']+=1;continue
            if not dedup:continue
            signature=hashlib.sha256(json.dumps(sorted((r['identifier_hash'],r['score'],r['pool'],r['special'],r['locator'] if r['identifier_masked'] else '') for r in dedup)).encode()).hexdigest()
            if (u['name'],doc['year'],signature) in table_seen:counter['equivalent_rosters']+=1;continue
            table_seen.add((u['name'],doc['year'],signature))
            # Match truncated continuation labels only within this source and
            # the same explicit professional/direction code, keeping modes.
            labels={}
            for r in dedup:
                bits=r['pool'].split('；');key=[]
                for bit in bits:
                    if '：' not in bit:key.append(('原文范围',bit,''));continue
                    h,v=bit.split('：',1)
                    m=re.match(r'(\d{6}|\d{2})(?!\d)',v)
                    key.append((h,m.group() if m else v,'非全日制' if '非全日' in v else '全日制' if '全日' in v else ''))
                k=tuple(key)
                if len(r['pool'])>len(labels.get(k,'')):labels[k]=r['pool']
                r['_label_key']=k
            for r in dedup:r['pool']=labels[r['_label_key']]
            grouped=defaultdict(list)
            for r in dedup:grouped[(r['pool'],r['special'])].append(r)
            for (pool,special),rs in grouped.items():
                scores=[r['score'] for r in rs]
                masked=sum(r['identifier_masked'] for r in rs)
                output.append(dict(unit=u['name'],year=doc['year'],source_title=doc['title'],source_url=doc['url'],source_artifact=str(raw),source_sha256=digest,pool=pool,special=special,n=len(rs),count_definition='observed-rows' if masked else 'distinct-visible-identifiers',masked_identifier_rows=masked,minimum=min(scores),maximum=max(scores),mean=round(statistics.mean(scores),2),median=statistics.median(scores),score_header=rs[0]['score_header'],locators=[r['locator'] for r in rs],verification='明确初试分数字段逐行提取；完整编号一致行去重，脱敏编号保留观测行而不认证人数；完整性/修订/专业范围仍待原页复核',source_document_candidate_count=len(dedup)))
        print(json.dumps({'unit':u['name'],'sources':len(selected),'groups_so_far':len(output)},ensure_ascii=False),flush=True)
    d.dump(d.WORK/'admission-statistics-candidates.json',output)
    print(json.dumps({'groups':len(output),'units':len(set(x['unit'] for x in output)),'counts':dict(counter)},ensure_ascii=False),flush=True)

if __name__=='__main__':run()
