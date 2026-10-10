"""Live Vue→Java→RabbitMQ→Python collection acceptance on a running local app.

One public official homepage only; retains its task audit/original bytes and
does not publish admissions or change saved personal comparisons.
"""
from datetime import datetime,timezone
import hashlib,json
from pathlib import Path
import sys,time,urllib.request,zipfile
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'crawler'))
from gradheat.material_store import readback
from gradheat.vm_db import connect_vm


def get(path):
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open('http://127.0.0.1:18729/api/v1'+path,timeout=12) as r:return json.load(r)


def main():
    folder=ROOT/'.research/collection-live-acceptance'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    folder.mkdir(parents=True);checks=[]
    def check(name,value):
        checks.append({'name':name,'passed':bool(value)})
        if not value:raise AssertionError(name)
    head=get('/version');comparisons=len(get('/admissions/comparisons').get('items',[]))
    source={'schema_version':1,'settings':{'execution':{'default_hours':.1},'official':{'max_pages_per_unit':1,'max_depth':0}},
        'tasks':[{'platform':'official','unit':'清华大学','urls':['https://yz.tsinghua.edu.cn/'],'domains':['tsinghua.edu.cn']}]}
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True,executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe')
        context=browser.new_context(viewport={'width':1440,'height':1000},accept_downloads=True);page=context.new_page();errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        try:
            page.goto('http://127.0.0.1:18729/#/tasks');page.get_by_text('浏览器已连接',exact=True).wait_for()
            check('live-vue-collection-page',page.get_by_role('heading',name='把资料采集交给程序').is_visible())
            # This test has no social query and does not authorize resetting platform gates.
            page.get_by_label('我已登录，确认平台可以搜索').check()
            page.get_by_label('选择采集 JSON 文件').set_input_files({'name':'bounded-official-test.json','mimeType':'application/json','buffer':json.dumps(source,ensure_ascii=False).encode()})
            page.get_by_role('button',name='开始爬取',exact=True).click()
            page.get_by_text('本轮采集已结束',exact=True).wait_for(timeout=120000)
            saved=page.evaluate('JSON.parse(localStorage.getItem("gradheat-collection"))')
            task=get('/tasks/'+saved['taskId']);progress=get('/collection/'+saved['batchId'])
            check('java-rabbit-python-terminal-task',task['status']=='succeeded')
            check('real-official-material-complete',progress['complete_jobs']==1 and progress['incomplete_jobs']==0)
            check('public-progress-hides-originals',not any(k in json.dumps(progress) for k in ('source_url','raw_html','local_path')))
            page.screenshot(path=str(folder/'desktop.png'),full_page=True)
            for kind,label in [('incomplete','下载未完成 JSON'),('handoff','下载原材料包')]:
                with page.expect_download() as pending:page.get_by_role('link',name=label).click()
                downloaded=pending.value;downloaded.save_as(folder/('incomplete.json' if kind=='incomplete' else 'handoff.zip'))
                check('live-browser-download-'+kind,downloaded.failure() is None)
            check('no-incomplete-task',json.loads((folder/'incomplete.json').read_text(encoding='utf-8'))['tasks']==[])
            with zipfile.ZipFile(folder/'handoff.zip') as z:
                records=json.loads(z.read('public-materials.json'));unique={r['sha256']:r for r in records}
                with connect_vm(folder/'private') as con:
                    for sha,row in unique.items():
                        data=z.read(row['path_in_package']);check('package-sha-'+sha[:8],hashlib.sha256(data).hexdigest()==sha)
                        with con.cursor() as cur:actual,size,chunks=readback(cur,sha)
                        check('mysql-byte-readback-'+sha[:8],actual==sha and size==len(data))
            check('head-unchanged',get('/version')==head)
            check('personal-comparisons-unchanged',len(get('/admissions/comparisons').get('items',[]))==comparisons)
            check('no-live-browser-script-errors',not errors)
        finally:context.close();browser.close()
    report={'checked_at':datetime.now(timezone.utc).isoformat(),'mode':'live-java-rabbit-python-mysql-and-browser',
        'task_id':task['task_id'],'batch_id':saved['batchId'],'checks':checks,'errors':errors}
    (folder/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'passed':sum(c['passed'] for c in checks),'total':len(checks),'report':str(folder/'verification.json')}))


if __name__=='__main__':main()
