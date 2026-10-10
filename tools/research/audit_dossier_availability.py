"""Separate absent information from the assistant's remaining review work.

An available item means at least one relevant pool has material, never that the
entire institution passed a completeness or competition-pool audit. Expected
quotas and an expired roster announcement are not admission results.
"""
from __future__ import annotations
import re
from pathlib import Path
import build_unit_dossiers as d

HISTORY_FIELDS = ('复试分数线', '录取人数', '录取分数统计')
CATALOGUE_FIELDS = ('专业目录', '招生人数')

# Original passages inspected during the availability audit. Assertions below
# require the retained version and a literal passage; a URL/title alone fails.
ORIGINAL_CHECKS = [
    ('天津大学', 2027, '/1521/5821.htm', ['专业目录'], ['085400', '408']),
    ('上海交通大学', 2027, '/post/3772', ['专业目录', '招生人数'], ['033计算机学院', '总招生计划：377']),
    ('深圳大学', 2027, '/1006/15196.htm', ['专业目录', '招生人数'], ['081200计算机科学与技术', '80']),
    ('华中师范大学', 2027, '/1008/14183.htm', ['专业目录'], ['081200', '201英语（一）', '301数学（一）', '408']),
    ('西安微电子技术研究所', 2027, 'sch/viewBulletin--infoId-3545937604,', ['专业目录', '招生人数'], ['0812', '408', '12']),
    ('华南理工大学', 2027, '/2026/0911/c30108a635058/page.htm', ['招生人数'], ['081200', '招生计划初定5个']),
    ('中国科学院空天信息创新研究院', 2026, 't20260325_8171856', ['复试分数线'], ['电子信息', '≥300']),
    ('中国科学院上海微系统与信息技术研究所', 2026, 't20260323_8168547', ['复试分数线'], ['085400', '≥264']),
    ('中国科学院上海微系统与信息技术研究所', 2025, 't20250320_7561587', ['复试分数线'], ['085400', '≥270']),
    ('华东师范大学', 2026, '399e6790-cafb-4e1a-9b32-e3f13aee36b8.pdf', ['复试分数线'], ['计算机科学与技术学院', '085404']),
    ('南方科技大学', 2026, '/graduate/3754.html', ['复试分数线'], ['复试分数线']),
    ('中国农业大学', 2025, '276ebe38fe4945efbcf851ea20826742.pdf', ['录取人数', '录取分数统计'], ['拟录取专业名称', '计算机']),
    ('大连理工大学', 2025, '95156E4486A4AC4A182F921DCFDF76F6', ['录取人数', '录取分数统计'], ['软件工程', '初试成绩', '拟录取']),
    ('电子科技大学', 2025, '2AD54C9785DFCBE97CCE0592CBE', ['录取人数', '录取分数统计'], ['学院代码', '初试', '004']),
    # Two retained partial rosters include computing degree codes. They supply
    # result material, but are not substituted for all SCCE admission pools.
    ('北京科技大学', 2025, '623876986db64632ba9d1e6ed75f6706.pdf', ['录取人数'], ['085404', '全国统考']),
]


def numeric(value):
    return bool(value and re.search(r'\d', str(value)) and not re.search(r'预计|预期|暂无|N诺|国家线', str(value)))


def actual_count(value):
    return numeric(value) and not re.search(r'计划|【|均分|最低分|最高分', str(value))


def audit(corpus, catalogues, claims, tablefacts, statistics, pdfpages):
    ledger = []
    missing = []
    for entry in d.priority.load():
        unit = corpus[entry['name']]
        group = '985' if entry['group'] == '985' else '研究所' if entry['group'] == '研究所' else '计算机强校'
        path = d.OUT / group / (unit['name'] + '.md')
        available = {2027: {}, 2026: {}, 2025: {}}

        def add(year, field, kind, url, artifact=None, locator=None, scope=None):
            if artifact and not Path(artifact).is_file():
                raise AssertionError((unit['name'], url, artifact))
            rec = dict(kind=kind, url=url, artifact=artifact, locator=locator, scope=scope)
            if rec not in available[year].setdefault(field, []):
                available[year][field].append(rec)

        # Catalogue material may exist even when the display's subject filter
        # excludes all rows (e.g. Fudan's reorganised programmes).
        cat = [r for r in catalogues if r['unit'] == unit['name'] and r.get('cohort') == 2027]
        for r in cat:
            add(2027, '专业目录', 'official_catalogue_record', r['source_url'], r['source_artifact'], r.get('locator'), r.get('department'))
            if numeric(r.get('planned_major_raw')):
                add(2027, '招生人数', 'official_catalogue_record', r['source_url'], r['source_artifact'], r.get('locator'), r.get('department'))

        for c in claims:
            if c['unit'] != unit['name']: continue
            fields = ['招生人数'] if c['year'] == 2027 and '招生计划' in c.get('covers', []) else c.get('covers', [])
            if c['year'] == 2027 and '11408' in c.get('covers', []): fields = fields + ['专业目录']
            for field in fields:
                if field not in CATALOGUE_FIELDS + HISTORY_FIELDS: continue
                for s in c['sources']:
                    add(c['year'], field, 'reviewed_original_claim', s['url'], s['artifact'], s.get('locator'), c['pool'])

        # A parsed roster is already available material; remaining manual
        # review is recorded separately and does not mean another download.
        for c in statistics:
            if c['unit'] != unit['name']: continue
            if unit['name'] == '中国科学院软件研究所' and c['year'] == 2025: continue  # Conflicting source year.
            for field in ('录取人数', '录取分数统计'):
                add(c['year'], field, 'retained_official_roster', c['source_url'], c['source_artifact'], c.get('locators'), c['pool'])
        for c in tablefacts:
            if c['unit'] == unit['name']:
                add(c['year'], '复试分数线', 'retained_official_table', c['source_url'], c.get('source_artifact'), c.get('locator'), c['label'])

        for year in (2026, 2025):
            for r in d.secondary_rows(unit, year):
                # Short rows keep the first three columns in their original
                # position. Combined final cells are handled explicitly.
                raw = r['raw']
                line = r['fields'].get('分数线') if r['aligned'] else raw[2] if len(raw) > 2 else None
                if numeric(line) and '最低分' not in str(line):
                    add(year, '复试分数线', 'secondary_numeric_report', r['source_url'], r['source_artifact'], r['locator'], r['department'])
                if r['aligned']:
                    f = r['fields']
                    if any(actual_count(f.get(k)) for k in ('拟录取人数', '录取人数')):
                        add(year, '录取人数', 'secondary_numeric_report', r['source_url'], r['source_artifact'], r['locator'], r['department'])
                    if numeric(f.get('拟录取分数')):
                        add(year, '录取分数统计', 'secondary_numeric_report', r['source_url'], r['source_artifact'], r['locator'], r['department'])
                elif len(raw) > 3:
                    combined = raw[-1]
                    # SIA's cell has mechanical/control results, not CS.
                    if unit['name'] == '中国科学院沈阳自动化研究所': continue
                    if re.search(r'(?:学硕|专硕|专项)\d+人|(?:第一批)?录取\s*(?:学硕|专硕)', combined):
                        add(year, '录取人数', 'secondary_combined_report', r['source_url'], r['source_artifact'], r['locator'], r['department'])
                        if re.search(r'\d{3}\s*【\d{3}[-—－]\d{3}】', combined):
                            add(year, '录取分数统计', 'secondary_combined_report', r['source_url'], r['source_artifact'], r['locator'], r['department'])

        docs = d.docs_for(unit)
        for name, year, needle, fields, passages in ORIGINAL_CHECKS:
            if name != unit['name']: continue
            matches = [doc for doc in docs if doc['year'] == year and doc['retained'] and needle in doc['url']]
            valid = []
            for doc in matches:
                body = re.sub(r'\s+', '', d.textfile(doc.get('text_path')))
                if all(re.sub(r'\s+', '', p) in body for p in passages): valid.append(doc)
            if not valid: raise AssertionError(('Inspected source changed', name, year, needle))
            doc = valid[0]
            for field in fields:
                add(year, field, 'inspected_original_material', doc['url'], doc.get('raw_path') or doc.get('text_path'), 'literal passages: ' + ' / '.join(passages), '原件已取得；完整专业范围另行核对')

        # Retained full PDF catalogues. A soldiers-only directory is excluded.
        for p in pdfpages:
            if p['unit'] != unit['name'] or unit['name'] not in ('西安电子科技大学', '南京理工大学'): continue
            if '专业目录' not in p['title']: continue
            add(2027, '专业目录', 'retained_official_catalogue_pdf', p['source_url'], p['source_artifact'], f'page {p["page"]}')
            add(2027, '招生人数', 'retained_official_catalogue_pdf', p['source_url'], p['source_artifact'], f'page {p["page"]}', '已检查目录含招生人数列；净名额仍须核对')

        # The OUC XLS contains subjects, but no admissions-quota column.
        if unit['name'] == '中国海洋大学':
            import xlrd
            for doc in docs:
                if doc['year'] != 2027 or not doc['retained'] or not doc['url'].endswith('.xls') or '专业目录' not in doc['title']: continue
                book = xlrd.open_workbook(doc['raw_path'])
                sheet = book.sheet_by_index(0)
                assert '初试考试科目' in sheet.row_values(0)
                assert any('081200计算机科学与技术' in sheet.row_values(n) for n in range(sheet.nrows))
                add(2027, '专业目录', 'inspected_official_spreadsheet', doc['url'], doc['raw_path'], 'Sheet1; computing programme rows')
        if unit['name'] == '东南大学':
            import xlrd
            for doc in docs:
                if doc['year'] != 2026 or not doc['retained'] or not doc['url'].endswith('.xls') or '拟录取' not in doc['title']: continue
                sheet = xlrd.open_workbook(doc['raw_path']).sheet_by_index(0)
                headers = sheet.row_values(0)
                assert '录取专业码' in headers
                col = headers.index('录取专业码')
                assert any(str(sheet.cell_value(n, col)).startswith(('0812', '085404', '0835', '0839')) for n in range(1, sheet.nrows))
                add(2026, '录取人数', 'inspected_official_spreadsheet', doc['url'], doc['raw_path'], 'Sheet1; admissions rows; no initial-score column')

        for year, fields in ((2027, CATALOGUE_FIELDS), (2026, HISTORY_FIELDS), (2025, HISTORY_FIELDS)):
            for field in fields:
                if field not in available[year]:
                    pattern=r'目录|考试科目' if field=='专业目录' else r'目录|招生计划' if field=='招生人数' else r'分数线|复试.*(?:办法|细则|通知)' if field=='复试分数线' else r'拟录取|录取名单|招生统计'
                    candidates=[x for x in docs if x.get('year')==year and x.get('source_tier')=='primary' and re.search(pattern,x['title']) and d.source_score(x,unit,year)>=14]
                    reasons={'verification-page':'验证或拦截','access-gateway':'访问入口提示页','http-error':'访问失败','fetch-failed':'连接失败','unexpected-html':'附件返回网页'}
                    states=list(dict.fromkeys(reasons[x['status']] for x in candidates if x.get('status') in reasons))
                    status='已定位入口，'+('／'.join(states)) if states else '已留存公告或目录外壳，尚未取得对应数值/专业行' if candidates else '尚未找到可核验的对应信息'
                    missing.append(dict(unit=unit['name'], group=group, year=year, field=field, status=status, publication_status='unconfirmed', source_urls=list(dict.fromkeys(x['url'] for x in candidates)), path=str(path)))
        ledger.append(dict(unit=unit['name'], group=group, checked_at=d.REPORT_DATE, availability=available, unit_coverage_complete=False))
    d.dump(d.WORK / 'material-availability.json', ledger)
    return missing
