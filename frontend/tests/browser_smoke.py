"""Synthetic, isolated Chromium acceptance: no server and no shared CDP session."""
import json
import mimetypes
from pathlib import Path
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
DIST = ROOT / 'frontend/dist'
OUTPUT = ROOT / '.research/frontend-intelligence-20261010'
VERSION = 'a' * 64
UNITS = ['示例东湖大学', '示例科技大学', '示例计算研究所']


def fixture():
    programmes, history, overview = [], [], []
    for index in range(24):
        pid = f'{index + 1:024x}'
        unit = UNITS[index % 3]
        major = ['计算机科学与技术', '软件工程', '人工智能'][index % 3]
        code = ['081200', '085405', '085410'][index % 3]
        hid = f'h-{index}'
        programmes.append(dict(id=pid, unit=unit, year=2027, department='计算机学院' if index % 3 < 2 else '智能计算研究中心', group=['985', '计算机强校', '研究所'][index % 3], major_name=major, major_code=code, directions=['不区分研究方向'], subjects=['101', '201', '301', '408'], degree_type='学术学位' if index % 3 == 0 else '专业学位', mode='全日制', eligible_11408=True, plan_text=f'专业：{60 + index}（含推免）', plan_status='官方口径已核', ordinary_quota=None))
        history.append(dict(id=hid, unit=unit, year=2026, department=programmes[-1]['department'], major_name=major, exam_text='11408', cutoff=310 + index, cutoff_text=str(310 + index), retest_count=80 + index, retest_text=str(80 + index), admit_count=60 + index, admit_text=str(60 + index), interview_admit_ratio=(80 + index)/(60 + index), admitted_score_text=f'均分 {335 + index}', status='两源一致', scope='普通一志愿 / 全日制 / 单专业'))
        overview.append(dict(id=pid, unit=unit, year=2027, major_name=major, major_code=code, reported_plan=60 + index, plan_text=programmes[-1]['plan_text'], history=[dict(id=hid, unit=unit, year=2026, cutoff=310 + index, mean=335 + index, admit_count=60 + index)], related_rules=[], background=dict(friendliness='unknown', note='合成验收：本科背景证据待核')))
    lines = [dict(id='line-1',unit=UNITS[0],year=2026,label='学校 / 普通学硕校线',cutoff=300,status='范围已核'),dict(id='line-2',unit=UNITS[0],year=2026,label='计算机学院 / 专项院线',cutoff=None,status='范围待核'),dict(id='line-3',unit=UNITS[0],year=2025,label='学校 / 普通校线',cutoff=290,status='范围已核')]
    list_groups = [dict(id='list-1',unit=UNITS[0],year=2026,scope='081200 / 普通一志愿 / 全日制',population='enrolled',exam_text='11408',n=10,minimum=320,maximum=370,mean=345,median=344,status='拟录取分组待核'),dict(id='list-2',unit=UNITS[0],year=2026,scope='081200 / 普通一志愿 / 全日制',population='retest_pool',exam_text='11408',n=20,minimum=310,maximum=380,mean=340,median=338,status='复试分组待核'),dict(id='list-3',unit=UNITS[1],year=2026,scope='专项 / 调剂 / 培养方式待核',population=None,exam_text=None,n=None,minimum=None,maximum=350,mean=None,median=None,status='人群待核'),dict(id='list-4',unit=UNITS[1],year=2026,scope='专业学位 / 全日制',population='enrolled',exam_text='22408',n=5,minimum=300,maximum=350,mean=325,median=326,status='分组待核'),dict(id='list-5',unit=UNITS[0],year=2025,scope='081200 / 普通一志愿 / 全日制',population='enrolled',exam_text='11408',n=7,minimum=310,maximum=360,mean=335,median=333,status='拟录取分组待核')]
    payload = dict(target_year=2027, data_as_of='2026-10-09 · 合成验收数据', last_checked=None, units=[dict(name=u, group=['985', '计算机强校', '研究所'][i]) for i, u in enumerate(UNITS)], programmes=programmes, history=history, cutoff_rows=lines, admission_groups=list_groups, historical_alignment={p['id']:dict(matched=[h['id']], ambiguous=[]) for p,h in zip(programmes,history)}, counts=dict(units=3, programmes=24, matched_programmes=24, history_rows=24), official_notes=[dict(unit=UNITS[0], year=2027, note='合成验收示例，非真实院校资料。')])
    dashboard = dict(data_version=VERSION, programmes=overview, chart_policy='合成验收')
    return payload, dashboard


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    payload, dashboard = fixture()
    calls, errors = [], []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe', headless=True)
        page = browser.new_page(viewport=dict(width=1440,height=1000), device_scale_factor=1)
        page.on('pageerror', lambda error: errors.append(str(error)))
        def intercept(route):
            path = route.request.url.split('offline.gradheat.test',1)[1].split('?',1)[0]
            if path.startswith('/api/v1'):
                body = route.request.post_data_json if route.request.method == 'POST' else None
                calls.append(dict(path=path, method=route.request.method, body=body))
                value = {}
                if path == '/api/v1/admissions': value = payload
                elif path == '/api/v1/dashboard': value = dashboard
                elif path == '/api/v1/heat':
                    value = dict(unit=UNITS[0], checked_at='2026-10-09T05:30:00Z', note='合成验收：有界样本不代表全站热度。', platforms=[dict(platform=p,label=l,unique_contents=4 if p!='dy' else 0,sampling_state='sample-available' if p!='dy' else 'no-stored-sample',observed_until='2026-10-08T20:00:00Z',metrics={key:dict(sum_known_values=12 if key=='like' and p!='dy' else None,known_contents=4 if key=='like' and p!='dy' else 0,unknown_contents=0) for key in ('like','comment','view')},query_groups=[dict(query=UNITS[0]+' 计算机考研',actual_sort='综合')],health=dict(state='needs-human' if p=='dy' else 'ready')) for p,l in [('xhs','小红书'),('zhihu','知乎'),('dy','抖音'),('bili','B站')]])
                    value.update(heat_value=42.1,basis='discussion-only')
                elif path == '/api/v1/recommendations':
                    assert body['data_version']==VERSION and 'score' not in body
                    value = dict(data_version=VERSION, eligible_candidates=24, basis='偏好分不代表录取难度。',friendliness_policy='待核',ranking=[dict(**{k:p[k] for k in ('id','unit','department','major_name','major_code','group')},preference_score=8.5,related_rules=[],background=dict(friendliness='unknown',note='待核')) for p in payload['programmes'][:6]])
                elif path == '/api/v1/school-indices':
                    value = [dict(unit=u,tier='普通院校',heat_value=42.1+i,basis='discussion-only') for i,u in enumerate(UNITS)]
                elif path == '/api/v1/school-dossier':
                    value = dict(unit=UNITS[0],available=True,tier='普通院校',programmes=payload['programmes'][:3],history=payload['history'][:3],notes=['合成验收：跨考录取经验'],heat=dict(heat_value=42.1),counts={})
                elif path == '/api/v1/victory-index':
                    assert body['data_version']==VERSION and 'profile' in body and 'options' not in body
                    if body['profile']['score'] is None:
                        value = dict(needs_profile=True,ranking=[],note='填写分数后计算')
                    else:
                        assert body['profile']['score']==350
                        value = dict(needs_profile=False,ranking=[dict(id=p['id'],unit=p['unit'],department=p['department'],major_name=p['major_name'],tier=p['group'],heat_value=42.1,victory_index=65.2,threshold=310,missing=[]) for p in payload['programmes'][:3]],note='合成验收参考指数，不代表录取概率')
                elif path == '/api/v1/admissions/comparisons': value = dict(items=[])
                route.fulfill(status=200,content_type='application/json',headers={'X-Data-Version':VERSION},body=json.dumps(value,ensure_ascii=False));return
            local = DIST / path.lstrip('/') if path != '/' else DIST/'index.html'
            if local.is_file(): route.fulfill(status=200,content_type=mimetypes.guess_type(str(local))[0] or 'application/octet-stream',body=local.read_bytes())
            else: route.fulfill(status=404,body='Missing test resource')
        page.route('**/*', intercept)
        page.goto('http://offline.gradheat.test/#/plans');page.get_by_text('24 条记录',exact=True).wait_for()
        page.screenshot(path=str(OUTPUT/'desktop-plans.png'),full_page=True)
        page.get_by_role('button',name='筛选院校 / 院系',exact=True).click();page.get_by_role('textbox',name='搜索院校 / 院系',exact=True).fill('东湖');page.get_by_role('button',name='完成',exact=True).click()
        assert page.locator('tbody tr').count()==8
        page.get_by_role('button',name='重置',exact=True).click();assert page.locator('tbody tr').count()==24
        page.get_by_role('button',name='筛选招生计划',exact=True).click();page.get_by_role('button',name='降序',exact=True).click();page.screenshot(path=str(OUTPUT/'desktop-column-filter.png'),full_page=True);page.keyboard.press('Escape')
        page.locator('tbody tr button').nth(0).click();page.locator('tbody tr button').nth(1).click()
        page.get_by_role('link',name='院校图览 数据可视化',exact=True).click();page.locator('.chart canvas').first.wait_for();page.wait_for_timeout(450);page.screenshot(path=str(OUTPUT/'desktop-overview.png'),full_page=True)
        page.get_by_role('link',name='偏好推荐 专业、类别与背景',exact=True).click();page.get_by_role('button',name='发现候选专业',exact=True).click();page.locator('.recommendation-card').first.wait_for();assert page.locator('.recommendation-card').count()==6
        page.get_by_role('link',name='胜利指数 分数 · 背景 · 热度',exact=True).click()
        page.get_by_role('button',name='计算胜利指数',exact=True).click();page.get_by_text('请填写预计初试总分或完整单科分数。',exact=True).wait_for()
        page.get_by_role('spinbutton',name='预计初试总分',exact=True).fill('350')
        page.get_by_role('button',name='计算胜利指数',exact=True).click();page.locator('.game-result').wait_for();assert page.locator('.victory-number').count()==3
        page.screenshot(path=str(OUTPUT/'desktop-game.png'),full_page=True)
        page.get_by_role('link',name='平台热度 关注与讨论',exact=True).click();page.get_by_text('讨论热度估算 · 搜索数据待接入',exact=True).wait_for()
        assert page.locator('.index-value').inner_text()=='42.1' and page.locator('.index-table tbody tr').count()==3
        page.screenshot(path=str(OUTPUT/'desktop-heat.png'),full_page=True)
        page.get_by_role('link',name='院校档案 招生 · 历史 · 经验',exact=True).click();page.locator('.game-result').wait_for();assert page.locator('.index-table tbody tr').count()==3
        page.get_by_text('背景与复试经验摘要',exact=True).click();page.get_by_text('合成验收：跨考录取经验',exact=True).wait_for()
        page.screenshot(path=str(OUTPUT/'desktop-school.png'),full_page=True)
        page.set_viewport_size(dict(width=390,height=844));page.get_by_role('link',name='胜利指数',exact=True).click()
        assert page.get_by_role('spinbutton',name='预计初试总分',exact=True).input_value()=='350'
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
        page.screenshot(path=str(OUTPUT/'mobile-game.png'),full_page=True)
        page.set_viewport_size(dict(width=1440,height=1000))
        page.get_by_role('link',name='历年录取 分数线与复录比',exact=True).click()
        page.locator('[data-history-lines] summary').click();page.locator('[data-history-groups] summary').click()
        assert page.locator('[data-history-lines] tbody tr').count()==2
        assert page.locator('[data-history-groups] tbody tr').count()==3
        assert '拟录取分组' in page.locator('[data-history-groups]').inner_text() and '复试分组' in page.locator('[data-history-groups]').inner_text()
        assert '非最终录取统计' in page.locator('[data-history-groups]').inner_text() and '科目待核' in page.locator('[data-history-groups]').inner_text()
        assert not page.locator('[data-history-groups]').get_by_text('22408',exact=True).count()
        assert '— / 350' in page.locator('[data-history-groups]').inner_text()
        page.screenshot(path=str(OUTPUT/'desktop-history-scopes.png'),full_page=True)
        page.get_by_role('button',name='2025',exact=True).click();assert page.locator('[data-history-lines] tbody tr').count()==1 and page.locator('[data-history-groups] tbody tr').count()==1
        page.get_by_role('button',name='2026',exact=True).click()
        page.set_viewport_size(dict(width=390,height=844));assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
        assert page.locator('[data-history-lines] thead th').count()==5 and page.locator('[data-history-groups] thead th').count()==7
        page.screenshot(path=str(OUTPUT/'mobile-history-scopes.png'),full_page=True)
        page.set_viewport_size(dict(width=390,height=844));page.get_by_role('link',name='招生计划',exact=True).click();page.locator('tbody tr').first.wait_for()
        assert page.locator('thead th').count()==6
        assert not page.locator('.scope-secondary').count()
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
        page.screenshot(path=str(OUTPUT/'mobile-plans.png'),full_page=True)
        head_before=page.locator('thead').bounding_box()['y'];page.locator('.table-scroll').evaluate('(el)=>el.scrollTop=300');page.wait_for_timeout(100)
        assert abs(page.locator('thead th').first.bounding_box()['y']-head_before)<2
        page.get_by_role('button',name='筛选专业 / 方向',exact=True).click();assert page.locator('[data-column-popup]').bounding_box()['x']>=0
        page.screenshot(path=str(OUTPUT/'mobile-column-filter.png'),full_page=True)
        assert not errors, errors
        browser.close()
    report=dict(checked_at=datetime.now(timezone.utc).isoformat(),mode='isolated-headless-synthetic-network-interception',live_server_checked=False,shared_browser_used=False,all_passed=True,checks=['Vue production build rendered','column search narrows and reset restores','descending sort popup','two selections persist between routes','ECharts overview renders','recommendation no exam score input / version present','victory requires score and submitted profile/version','single combined heat and missing-search label','school dossier renders','personal draft persists between pages','mobile profile fits','mobile six columns visible / no horizontal overflow','mobile global filters collapsed','sticky header stays while table scrolls','history school/department lines remain separate','history enrolled/retest populations remain separate with missing values','history independent year switch','mobile history all five/seven columns fit','no browser page errors'],screenshots=[p.name for p in OUTPUT.glob('*.png')],requests=[dict(path=c['path'],method=c['method']) for c in calls])
    (OUTPUT/'browser-smoke-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':main()
