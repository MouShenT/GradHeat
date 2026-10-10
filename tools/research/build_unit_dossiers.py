"""Build one evidence-aware dossier per priority institution, plus one gap ledger.

Availability, original table extraction, secondary reports and reviewed claims
remain distinct. Personal admission records are never copied into public docs.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit, unquote

from bs4 import BeautifulSoup
import collect_priority_sources as priority

ROOT = priority.ROOT
WORK = ROOT / '.research/unit-dossiers-20261001'
OUT = ROOT / 'docs/units'
TARGET = ['101', '201', '301', '408']
REPORT_DATE = '2026-10-04'
COMPUTING = re.compile(r'计算机|软件|人工智能|网络空间|网络与信息安全|智能科学|数据科学|大数据|数字媒体')
BLOCK = re.compile(r'博士|推免|推荐免试|免试攻读|直博|强基|国优|夏令营|导师资格|硕导名单|导师一览|思想政治|诚信复试|政审|调档|党组织|体检|港澳台|留学生|本科招生|本科生招生|高考')

@lru_cache(maxsize=32)
def _read_version(p, modified_ns, size):
    return json.loads(Path(p).read_text(encoding='utf-8'))

def read(p, default=None):
    p = Path(p)
    if not p.exists(): return default
    stat = p.stat()
    return _read_version(str(p), stat.st_mtime_ns, stat.st_size)

def dump(p, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding='utf-8')

def textfile(p):
    if not p or not Path(p).is_file(): return ''
    return Path(p).read_text(encoding='utf-8', errors='replace')

def cell(v):
    return str(v if v is not None else '—').replace('|', '／').replace('\n', ' ').replace('\r', ' ').strip() or '—'

def local_link(p, title='本地留存'):
    return f'[{title}](<{Path(p).as_posix()}>)'

def link(d):
    return f'[{cell(d["title"])}]({d["url"]})'

def belongs_to_unit(doc, unit):
    """Shared portals require an institution identity, not only a hostname."""
    url = unquote(doc['url'])
    host = urlsplit(url).hostname or ''
    if host.endswith('chsi.com.cn'):
        identity = re.search(r'schId-(\d+)', unquote(unit.get('portal') or unit.get('chsi') or ''))
        document_identity = re.search(r'schId-(\d+)', url)
        if identity and document_identity:
            return identity.group(1) == document_identity.group(1)
        if '/kyzx/' in url:
            title = doc.get('title', '')
            body = textfile(doc.get('text_path') or doc.get('local_text'))[:1600]
            return unit['name'] in title or unit['name'] in body
    if host.endswith('ucas.ac.cn'):
        if '/ZhaoshengDanwei/' in url: return False  # All-unit navigation, not this unit's annual catalogue.
        if '/ShowArticle/' in url and not re.search(r'硕士|研究生', doc.get('title', '')): return False
    return True

def classify_retained_source(record):
    """Do not replace a retained attachment with a CAPTCHA HTML response."""
    record=dict(record)
    path=record.get('raw_path')
    if not path or Path(path).suffix.lower()!='.html':return record
    expected=bool(re.search(r'DownloadAttachUrl|download\.jsp|\.(?:pdf|docx?|xlsx?)(?:$|[?#])',record.get('url',''),re.I)
        or re.search(r'\.(?:pdf|docx?|xlsx?)\b',record.get('title',''),re.I))
    body=textfile(record.get('text_path')).strip()
    verification=(expected and '请输入验证码' in body and '下载附件' in body) or (
        len(body)<200 and bool(re.search(r'^请输入验证码(?:下载附件)?$',re.sub(r'\s+','',body))))
    if verification:record.update(retained=False,status='verification-page',content_readable=False,
        derived_access_review='attachment CAPTCHA response is not the attachment')
    elif expected:record.update(retained=False,status='unexpected-html',content_readable=False,
        derived_access_review='expected binary attachment, received HTML')
    return record


def docs_for(unit):
    found = {}
    for d in unit['documents'] + unit.get('supplement_documents', []):
        if not belongs_to_unit(d, unit): continue
        f = d.get('collection_file') or {}
        path = f.get('text_artifact') or d.get('local_text')
        raw = f.get('artifact')
        explicit = re.findall(r'(?<!\d)(20\d{2})\s*年', d['title'])
        if len(set(explicit)) == 1 and int(explicit[0]) != d.get('year'):
            d = dict(d, year=int(explicit[0]), year_corrected_from='题名明确年度优先于父页继承年度')
        if d.get('year') not in (2027, 2026, 2025):
            # Some attachment titles are only their filename. Use an explicit
            # year in the PDF heading, never a date in unrelated body content.
            heading = textfile(path)[:350] if raw and Path(raw).suffix == '.pdf' else ''
            m = re.search(r'202[567]\s*年', heading)
            if not m or not re.search(r'硕士|研究生|招生', heading): continue
            d = dict(d, year=int(m.group()[:4]), year_inferred_from='原始PDF正文标题')
        access = d.get('collection_access') or d.get('priority_access') or d.get('access') or {}
        rec = dict(d, text_path=path, raw_path=raw or access.get('artifact'), retained=bool(path and Path(path).is_file()) or bool(raw and Path(raw).is_file()))
        rec=classify_retained_source(rec)
        previous = found.get(d['url'])
        if previous is None or (rec['retained'] and not previous['retained']): found[d['url']] = rec
    for d in read(WORK / 'live-sources.json', []) + read(WORK / 'secondary-recovery-sources.json', []):
        # Only exact-unit observations are accepted below. Skip other units
        # before inspecting their saved Chsi article bodies.
        if d.get('unit') != unit['name']: continue
        if not belongs_to_unit(d, unit): continue
        explicit = re.findall(r'(?<!\d)(20\d{2})\s*年', d['title'])
        if len(set(explicit)) == 1:
            d = dict(d, year=int(explicit[0]))
        if d['unit'] == unit['name'] and d.get('year') in (2027, 2026, 2025):
            rec = dict(d, retained=d.get('status') in ('html-saved', 'file-saved'), source_tier=d.get('source_tier', 'primary'))
            rec=classify_retained_source(rec)
            previous=found.get(d['url'])
            if previous and previous['retained'] and not rec['retained']:
                found[d['url']]=dict(previous,latest_access={'status':rec.get('status'),'retrieved_at':d.get('retrieved_at')})
            else:found[d['url']] = rec
    return list(found.values())

def source_score(d, unit, year):
    t = d['title']
    if BLOCK.search(t) or BLOCK.search(d.get('live_title','')): return -100
    score = 0
    if COMPUTING.search(t): score += 25
    if unit['group'] == '研究所': score += 10
    if re.search(r'硕士.*拟录取|拟录取.*硕士|硕士.*录取名单', t): score += 18
    if re.search(r'成绩|分数线|复试.*细则|复试.*办法', t): score += 6
    if year == 2027 and re.search(r'专业目录|招生计划|招生简章|招生章程|考试科目', t): score += 25
    if d.get('source_tier') == 'primary': score += 8
    if d['retained']: score += 5
    if any(w in t for w in ['音乐', '政治', '经济', '管理学院', '动物', '建筑', '医学', '法学', '生命', '外国语']): score -= 35
    if not COMPUTING.search(t) and re.search(r'学院|学部', t) and unit['group'] != '研究所': score -= 15
    return score

def secondary_rows(unit, year):
    rows = []
    tables = read(ROOT / '.research/gapfill-20261001/secondary-tables' / (unit['key'] + '.json'), [])
    institute_filter = None
    if not tables and unit['group'] == '研究所' and unit.get('ucas_name'):
        tables = read(ROOT / '.research/gapfill-20261001/secondary-tables/367929.json', [])
        institute_filter = unit['ucas_name']
    for table in tables:
        if table['year'] != year: continue
        department = '原表未注明院系'
        header = None
        for n, raw in enumerate(table['rows']):
            if len(raw) == 1:
                if len(raw[0]) < 65 and re.search(r'学院|学部|研究院|研究所|中心|系|校区|书院', raw[0]): department = raw[0]
                continue
            if any('专业名称' in x for x in raw): header = raw; continue
            if header is None or len(raw) < 2 or len(raw) > len(header): continue
            if institute_filter is not None and department != institute_filter: continue
            if not COMPUTING.search(raw[0] + department) and not re.search(r'408|0812|0835|0839|0854', ' '.join(raw[:2])): continue
            aligned = len(raw) == len(header)
            fields = {h: (None if v.strip() in ('N诺', 'N诺暂无数据', '', '暂无', '暂无数据') else v.strip()) for h, v in zip(header if aligned else header[:2], raw if aligned else raw[:2])}
            # Do not overwrite duplicate column labels: retain the cells too.
            rows.append(dict(year=year, department=department, fields=fields, headers=header, raw=raw, aligned=aligned, source_url=table['source_url'], source_artifact=table['source_artifact'], source_sha256=table['source_sha256'], locator=f'table[{table["table"]}] row[{n}]', verification='第三方原表逐格留存；未以此替代官方事实'))
    return rows

def catalogue_rows(unit, catalogues):
    rows = [r for r in catalogues if r['unit'] == unit['name'] and r.get('cohort') == 2027 and (COMPUTING.search(r.get('major_name', '')) or r.get('eligible_11408') is True)]
    # A repeated direction is not a new quota. Preserve each original plan scope.
    grouped = {}
    for r in rows:
        key = (r.get('department', ''), r.get('major_code'), r.get('mode'), tuple(r.get('subjects') or []), r.get('planned_major_raw'), r['source_url'], r.get('campus'), r.get('comparison_pool_scope'))
        if key not in grouped: grouped[key] = dict(r, directions=[], locators=[], direction_details=[])
        grouped[key]['directions'].append(r.get('direction', '未注明'))
        grouped[key]['locators'].append(r.get('locator', ''))
        if r.get('direction_plan_raw') is not None:
            grouped[key]['direction_details'].append(dict(direction=r.get('direction'),plan_raw=r['direction_plan_raw']))
    return list(grouped.values())

def search_records(unit):
    result = []
    for p in sorted((WORK / 'search').glob('*.json')):
        x = read(p, {})
        if unit['name'] in x.get('units', x.get('queries', [])):
            result.append(dict(file=str(p), queries=x.get('queries'), retrieved_at=x.get('retrieved_at')))
    return result

def load_catalogues():
    return read(ROOT / '.research/manual-downloads/已提取11408专业.json')['all_rows'] + read(WORK/'supplement-catalogue-rows.json', []) + read(WORK/'daily-catalogue-rows.json', [])

def load_claims():
    return read(WORK/'reviewed-claims.json', []) + read(WORK/'supplement-reviewed-claims.json', []) + read(WORK/'first-pool-reviewed-claims.json', []) + read(ROOT/'.research/channel-supplement-20261003/checked-claims.json', []) + read(ROOT/'.research/gap-round2-20261003/checked-claims.json', []) + read(ROOT/'.research/news-check-20261004/checked-claims.json', []) + read(WORK/'daily-reviewed-claims.json', [])

def build():
    corpus = {u['name']: u for u in read(ROOT / '.research/manual-downloads/全量采集资料.json')['units']}
    catalogues = load_catalogues()
    reviewed = load_claims()
    tablefacts = read(WORK / 'official-table-facts.json', [])
    statistics = read(WORK / 'admission-statistics-candidates.json', [])
    pdfpages = read(WORK / 'catalogue-page-evidence.json', [])
    summary, missing, all_data = [], [], []
    for entry in priority.load():
        u = corpus[entry['name']]
        group = '985' if entry['group'] == '985' else '计算机强校' if entry['group'] != '研究所' else '研究所'
        path = OUT / group / (u['name'] + '.md')
        docs = docs_for(u)
        cat = catalogue_rows(u, catalogues)
        secondary = {y: secondary_rows(u, y) for y in (2026, 2025)}
        claims = [c for c in reviewed if c['unit'] == u['name']]
        native = [c for c in tablefacts if c['unit'] == u['name']]
        aggregates = [c for c in statistics if c['unit'] == u['name']]
        pages = [c for c in pdfpages if c['unit'] == u['name']]
        searches = search_records(u)
        md = [f'# {u["name"]}', '', f'分组：{group}。面向 **2027 年入学**；回看 **2026、2025 年招生录取**。学硕、专硕均保留，11408 指 101＋201＋301＋408。', '', f'更新日期：{REPORT_DATE}。下文区分已核对事实、官网提取候选及第三方统计；尚未取得的信息见唯一缺失总表，已有资料的核对由助手完成。', '', '## 2027 招生专业与计划', '', '目录人数按原文展示；相同专业下多个方向共享的人数不重复相加。未明确推免、专项及院系范围的计划不能直接当作普通统考名额。', '']
        if cat:
            md += ['| 院系／培养单位 | 专业 | 方向 | 学习方式 | 科目代码 | 11408 初筛 | 计划原值 | 来源与口径 |', '|---|---|---|---|---|---|---|---|']
            for r in cat:
                subjects = '+'.join(r.get('subjects') or []) or '存在备选科目；见原表'
                eligible = '符合科目组合' if r.get('eligible_11408') is True else '不符合／待确认'
                scope = r.get('quota_definition', '原表未明确口径')
                md.append('| ' + ' | '.join(map(cell, [r.get('department') or u['name'], f'{r.get("major_code", "")} {r.get("major_name", "")}', '；'.join(dict.fromkeys(r['directions'])), r.get('mode'), subjects, eligible, r.get('planned_major_raw'), f'[官方原表]({r["source_url"]})；{scope}'])) + ' |')
            md += ['', '以上为已留存目录的提取候选，范围可能只有查询首屏；不表示已核验全校全部院系或最终统考计划。逐行定位和原件哈希保存在本轮证据账本。', '']
        else:
            md += ['尚未形成完整的 2027 目录逐行数据。已经核对的公告或计划按下方事实表展示；其他官网资料仍需核对计算机相关专业行与计划口径，不能用往年或推免目录代填。', '']
        if pages:
            md += ['### 已定位的目录原件页', '', '这些是原始PDF中已定位的相关页，列对齐与人数仍待逐页复核；本表不把OCR或文本定位视为科目、计划已经确认。', '', '| 官方原件 | 已定位页码 |', '|---|---|']
            byurl = defaultdict(list)
            for r in pages: byurl[r['source_url']].append(r['page'])
            for url, pn in byurl.items(): md.append(f'| [目录原件]({url}) | {"、".join(map(str, sorted(set(pn))))} |')
            md += ['']
        for year in (2027, 2026, 2025):
            if year != 2027: md += [f'## {year} 录取情况', '']
            cs = [c for c in claims if c['year'] == year]
            ns = [c for c in native if c['year'] == year]
            if cs:
                md += ['### 已核对的事实', '', '| 范围 | 信息 | 核验与限制 | 证据 |', '|---|---|---|---|']
                for c in cs:
                    md.append('| ' + ' | '.join(map(cell, [c['pool'], c['claim'], c['verification'] + '；' + c.get('limitation', ''), '；'.join(f'[来源{i+1}]({s["url"]})' for i,s in enumerate(c['sources']))])) + ' |')
                md += ['']
            if year != 2027:
                gs = [c for c in aggregates if c['year'] == year]
                if gs:
                    md += ['### 名单复算候选（尚未全量复核）', '', '以下来自官网原件的明确初试成绩列，按原文专业、方向、学习方式及备注分组。人数是**该份公示中可解析的行数**，不保证最终实际录取数；不同批次、重复公示和递补不自动相加。均分保留两位小数。前文“已核对的事实”才表示完成相应原页复核。', '', '| 原文分组 | 备注／专项识别 | 公示可解析人数 | 初试最低／最高 | 初试均分／中位数 | 公示来源 |', '|---|---|---|---|---|---|']
                    for c in gs:
                        md.append('| ' + ' | '.join(map(cell, [c['pool'], c['special'], c['n'], f'{c["minimum"]:g}／{c["maximum"]:g}', f'{c["mean"]:.2f}／{c["median"]:g}', f'[{cell(c["source_title"])}]({c["source_url"]})'])) + ' |')
                    md += ['']
                    if u['name'] == '中国科学院软件研究所' and year == 2025:
                        md += ['**年度冲突：这份官网页面标题为2025，但正文公示期写2024；上述提取候选暂不作为已确认的2025录取事实。**', '']
            if ns:
                md += ['### 官网原文表格', '', '以下字段由留存官网 HTML 的明确表头定位，尚需完成专业、普通／专项及修订版本的逐项复核；一致标记仅表示同字段与第三方值吻合。', '', '| 原文专业／类别 | 表头 | 原文对应单元格 | 交叉核对 | 官网 |', '|---|---|---|---|---|']
                for c in ns:
                    md.append('| ' + ' | '.join(map(cell, [c['label'], '；'.join(c['headers']), '；'.join(c['values']), c.get('comparison', '尚未取得同口径第二来源'), f'[原文]({c["source_url"]})'])) + ' |')
                md += ['']
            if year in secondary:
                ss = secondary[year]
                if ss:
                    md += ['### 第三方统计，供核对', '', '保留原表数字及其表头，未公开计算过程的均分／分数范围尚未复算。“预计招生人数”不计作实际录取；“＋调剂／专项”不并入普通一志愿。N诺占位内容显示为缺失。', '', '| 院系／项目 | 专业 | 当年科目 | 复试线 | 入复试人数 | 入复试总分统计 | 人数字段原名与值 | 拟录取分数原报值 |', '|---|---|---|---|---|---|---|---|']
                    for r in ss:
                        f = r['fields']; countlabels = [h for h in r['headers'] if h in ('预计招生人数', '拟录取人数', '录取人数', '招生人数')]
                        count = '；'.join(f'{h}：{f.get(h) or "—"}' for h in countlabels)
                        md.append('| ' + ' | '.join(map(cell, [r['department'], f.get('专业名称'), f.get('初试科目') or f.get('专业课'), f.get('分数线'), f.get('复试人数'), f.get('进复试总分均分') or f.get('进批总分均分') or f.get('复试总分均分'), count, f.get('拟录取分数')])) + ' |')
                    md += ['', '来源：' + '；'.join(f'[N诺原表]({url})' for url in dict.fromkeys(r['source_url'] for r in ss)) + '。第三方统计保留为待核证据，不能把同一公告的多次转载当独立验证。', '']
                    short = [r for r in ss if not r.get('aligned', True) and len(r['raw']) > 2]
                    if short:
                        md += ['原表有合并／缺少单元格的短行，以下保留其内容，不强行归入人数或均分列：', '']
                        md += [f'- {cell(r["department"])}／{cell(r["raw"][0])}：' + '；'.join(cell(v) for v in r['raw'][2:]) for r in short]
                        md += ['']
                elif not cs and not ns:
                    md += ['尚未取得可展示的同年度计算机相关录取统计。已找到的名单／公告列于下面，仍须核对专业范围并解析；没有数据不代表未招生。', '']
            ranked = sorted((d for d in docs if d['year'] == year and d.get('source_tier') == 'primary'), key=lambda d: source_score(d,u,year), reverse=True)
            selected = [d for d in ranked if source_score(d,u,year) >= 14][:10]
            md += [f'### {year} 官方资料入口', '']
            if selected:
                for d in selected:
                    state = '已留存，内容及年度范围待逐项核验' if d['retained'] else '已定位链接，未取得完整正文'
                    md.append(f'- {link(d)}：{state}。' + (local_link(d.get('text_path') or d.get('raw_path')) if d['retained'] and (d.get('text_path') or d.get('raw_path')) else ''))
            else: md += ['尚未找到能够据此核验上述字段的官方全文入口。']
            md += ['']
            # Gaps are field-level, not closed just because an attachment exists.
            if year == 2027:
                missing.append(dict(unit=u['name'],group=group,year=year,field='招生计划',detail='普通统考净名额、推免占用、专项及院系/方向范围未完整核验' if cat or cs else '目录专业行、11408科目与普通统考名额待核验',status='部分公告/计划已复核' if cs else '部分目录已提取' if cat else '已定位原件相关页，待逐行核验' if pages else '未形成逐行数据',path=str(path)))
            else:
                done = {f for c in cs if c.get('unit_coverage_complete') for f in c.get('covers', [])}
                for field in ('复试分数线', '录取人数', '录取分数统计', '录取口径与完整性'):
                    if field in done: continue
                    status = '部分范围已复核，其他范围待核' if any(field in c.get('covers', []) for c in cs) else '有官网分数表，专业/专项范围待核' if ns and field == '复试分数线' else '有官网名单复算候选，完整性待核' if gs and field in ('录取人数','录取分数统计','录取口径与完整性') else '有第三方统计，官方口径待核' if ss else '待提取或寻找'
                    missing.append(dict(unit=u['name'],group=group,year=year,field=field,detail='按院系、专业、学习方式分开；核对一志愿/调剂/推免/专项及递补版本',status=status,path=str(path)))
        first_pools = [p for p in read(WORK/'first-pool-candidates.json', []) if p['unit'] == u['name']]
        if first_pools:
            md += ['## 首批专业范围核对', '', f'已拆开{len(first_pools)}个2027科目匹配项目，分别关联2027章程和2026本院系排序细则。2026规则不能直接转用到2027；普通统考净名额、专项排序范围和个人资格仍未知，当前没有已批准的竞争池。详见[首批核对草稿](../../FIRST-POOL-REVIEW-20261003.md)及' + local_link(WORK/'first-pool-candidates.json', '结构化候选') + '。', '']
        md += ['## 核验记录与使用边界', '', f'本轮线上检索记录：{len(searches)} 批。原始响应及查询时间留存于本轮证据账本；检索无命中不能证明学校未公布。', '', '录取人数和分数统计须来自完整、同口径名单；只取得拟录取者成绩，不能据此算全体复试淘汰率。2025、2026 如使用不同考试科目，历史分数不作直接可比。', '', '证据账本：' + local_link(WORK/'dossiers.json', '本单位提取与查询记录（按unit检索）') + '；' + local_link(WORK/'reviewed-claims.json', '复核事实、定位与原件哈希') + '；' + local_link(WORK/'admission-statistics-candidates.json', '名单复算候选与页码定位') + '。', '', '缺失字段统一列于 [缺失信息汇总](../缺失信息汇总.md)，每个单位不再另建缺失文档。完整原件索引见 [下载导航](../../../DOWNLOAD-NAVIGATOR.md)。', '']
        # Correct relative path from docs/units/<group> to docs/DOWNLOAD-NAVIGATOR.
        md[-2] = md[-2].replace('../../../DOWNLOAD', '../../DOWNLOAD')
        path.parent.mkdir(parents=True, exist_ok=True);path.write_text('\n'.join(md),encoding='utf-8')
        summary.append(dict(name=u['name'],group=group,path=str(path),catalogue_rows=len(cat),secondary2026=len(secondary[2026]),secondary2025=len(secondary[2025]),reviewed_claims=len(claims),official_table_rows=len(native),admission_statistics_groups=len(aggregates),catalogue_pdf_pages=len(pages),search_batches=len(searches)))
        all_data.append(dict(unit=u['name'],group=group,catalogue=cat,secondary=secondary,reviewed_claims=claims,official_tables=native,admission_statistics_candidates=aggregates,catalogue_page_candidates=pages,searches=searches))
    # Keep verification and scope work in the assistant's internal queue.
    # Public gaps mean absent information, not unfinished assistant review.
    dump(WORK / 'review-queue.json', missing)
    import audit_dossier_availability
    missing = audit_dossier_availability.audit(corpus, catalogues, reviewed, tablefacts, statistics, pdfpages)
    dump(WORK / 'dossiers.json',all_data);dump(WORK / 'summary.json',summary);dump(WORK / 'missing-fields.json',missing)
    index = ['# 重点招生单位资料', '', f'更新：{REPORT_DATE}。按现有优先名单整理：39 所 985、19 所计算机强校候选、10 个研究所，共 68 个单位。候选分组用于采集顺序，不构成学校实力排序；尚不满足 11408 的单位也保留证据。中国科学院大学总目录可能含下方研究所的相同项目，不能再次相加为全国总人数。', '', '年度口径：2027 招生计划，2026 和 2025 录取情况。每个单位一份 Markdown；全体缺失字段只有 [一份汇总](缺失信息汇总.md)。数字状态在各文档中标明，资料留存不等于事实核验。', '', '| 单位 | 分组 | 2027 目录提取组／PDF定位页 | 2026／2025 第三方专业行 | 已复核事实 | 官网表格／名单复算候选 |', '|---|---|---|---|---|---|']
    for s in summary:
        rel=Path(s['path']).relative_to(OUT).as_posix()
        index.append(f'| [{s["name"]}]({rel}) | {s["group"]} | {s["catalogue_rows"]}／{s["catalogue_pdf_pages"]} | {s["secondary2026"]}／{s["secondary2025"]} | {s["reviewed_claims"]} | {s["official_table_rows"]}／{s["admission_statistics_groups"]} |')
    (OUT/'README.md').write_text('\n'.join(index)+'\n',encoding='utf-8')
    counts = Counter((m['year'], m['field']) for m in missing)
    gaps = ['# 缺失信息汇总', '', f'更新：{REPORT_DATE}。只列当前尚未取得的信息；已有原件但尚待解析或复核，由助手处理，不算缺失。', '', '2027：' + '、'.join(f'{field}缺{counts[(2027,field)]}个单位' for field in ('专业目录','招生人数')) + '。2026：' + '、'.join(f'{field}缺{counts[(2026,field)]}个单位' for field in ('复试分数线','录取人数','录取分数统计')) + '。2025：' + '、'.join(f'{field}缺{counts[(2025,field)]}个单位' for field in ('复试分数线','录取人数','录取分数统计')) + '。', '', '“—”表示已取得至少部分相关信息，可能来自第三方，不表示全校全部专业已齐备。招生人数不等于扣除推免、专项后的普通统考名额；完整专业范围和口径继续由助手核对。**仅凭未搜到或403/404，不能标为官网未公布；目前没有经核实的未公布结论。**', '', '| 单位 | 2027缺失信息 | 2026缺失信息 | 2025缺失信息 | 取得情况 |', '|---|---|---|---|---|']
    for s in summary:
        if not any(m['unit']==s['name'] for m in missing): continue
        rel=Path(s['path']).relative_to(OUT).as_posix()
        parts=[]
        for year in (2027,2026,2025):
            ms=[m for m in missing if m['unit']==s['name'] and m['year']==year]
            parts.append('、'.join(m['field'] for m in ms) or '—')
        states='；'.join(dict.fromkeys(m['status'] for m in missing if m['unit']==s['name']))
        gaps.append('| '+ ' | '.join([f'[{s["name"]}]({rel})']+[cell(p) for p in parts]+[cell(states)])+' |')
    (OUT/'缺失信息汇总.md').write_text('\n'.join(gaps)+'\n',encoding='utf-8')
    print(json.dumps(dict(units=len(summary),catalogue_units=sum(s['catalogue_rows']>0 for s in summary),secondary2026_units=sum(s['secondary2026']>0 for s in summary),secondary2025_units=sum(s['secondary2025']>0 for s in summary),reviewed_claims=sum(s['reviewed_claims'] for s in summary),official_table_rows=sum(s['official_table_rows'] for s in summary),missing_fields=len(missing)),ensure_ascii=False))

if __name__ == '__main__':
    build()
