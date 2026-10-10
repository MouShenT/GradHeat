"""Synthetic collection UI acceptance in own isolated headless browser."""
from datetime import datetime,timezone
import io,json,mimetypes,zipfile
from pathlib import Path
from playwright.sync_api import sync_playwright
from browser_smoke import fixture,VERSION

ROOT=Path(__file__).resolve().parents[2]
OUTPUT=ROOT/'.research/collection-ui-acceptance';BATCH='batch-20261010-'+'a'*12


def main():
    OUTPUT.mkdir(parents=True,exist_ok=True);payload,dashboard=fixture();opened=False;created=None;calls=[];errors=[];checks=[]
    def check(name,value):
        checks.append({'name':name,'passed':bool(value)})
        if not value:raise AssertionError(name)
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True,executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe')
        context=browser.new_context(viewport={'width':1440,'height':1100},accept_downloads=True)
        page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
        def route(r):
            nonlocal opened,created
            path=r.request.url.split('collection.gradheat.test',1)[1].split('?',1)[0]
            if not path.startswith('/api/v1'):
                target=ROOT/'frontend/dist'/('index.html' if path=='/' else path.lstrip('/'))
                r.fulfill(status=200,body=target.read_bytes(),content_type=mimetypes.guess_type(target.name)[0] or 'text/javascript');return
            body=r.request.post_data_json if r.request.method=='POST' else None;calls.append({'path':path,'body':body})
            if path.endswith('/collection/browser'):
                if body is not None:opened=True
                data={'browser_available':opened,'opening':False,'state':'opening'}
            elif path.endswith('/collection/prepare'):data={'batch_id':BATCH,'plan_sha':'b'*64,'platforms':['xhs','zhihu','dy','bili','official','github']}
            elif path=='/api/v1/tasks':created=body;data={'task_id':body['request_id'],'status':'queued'}
            elif path.endswith('/download/incomplete'):
                r.fulfill(status=200,body=json.dumps({'schema_version':1,'tasks':[{'platform':'xhs','query':'合成补采'}]}),headers={'Content-Type':'application/json','Content-Disposition':'attachment; filename="incomplete.json"'});return
            elif path.startswith('/api/v1/tasks/'):data={'task_id':created['request_id'],'status':'succeeded'}
            elif path.endswith('/collection/'+BATCH):data={'batch_id':BATCH,'planned_jobs':6,'processed_jobs':6,'complete_jobs':4,'incomplete_jobs':2,'unattempted_jobs':0,'states':{'committed':4,'needs-human':1,'failed':1},'downloads':{'incomplete':True,'handoff':True}}
            elif path=='/api/v1/admissions':data=payload
            elif path=='/api/v1/dashboard':data=dashboard
            else:data={}
            r.fulfill(status=200,body=json.dumps(data,ensure_ascii=False),headers={'Content-Type':'application/json','X-Data-Version':VERSION})
        context.route('**/*',route)
        try:
            page.goto('https://collection.gradheat.test/#/tasks');page.get_by_role('heading',name='把资料采集交给程序').wait_for()
            check('start-disabled-before-login-and-file',page.get_by_role('button',name='开始爬取',exact=True).is_disabled())
            page.get_by_role('button',name='爬取 · 打开浏览器').click();page.get_by_text('浏览器已连接',exact=True).wait_for()
            check('browser-opening-button-calls-java',any(c['path'].endswith('/collection/browser') and c['body']=={} for c in calls))
            page.get_by_label('我已登录，确认平台可以搜索').check()
            upload=page.get_by_label('选择采集 JSON 文件')
            upload.set_input_files({'name':'bad.json','mimeType':'application/json','buffer':b'{bad'})
            page.get_by_role('alert').filter(has_text='JSON 格式').wait_for();check('malformed-file-cannot-start',page.get_by_role('button',name='开始爬取',exact=True).is_disabled())
            tasks=[{'platform':p,'query':'合成查询 '+p} for p in ('official','xhs','zhihu','dy','bili','github')]
            upload.set_input_files({'name':'queries.json','mimeType':'application/json','buffer':json.dumps({'tasks':tasks}).encode()})
            page.get_by_text('6 个检索任务',exact=True).wait_for();page.get_by_role('button',name='开始爬取',exact=True).click()
            page.get_by_role('link',name='下载未完成 JSON').wait_for()
            check('mq-command-has-reference-not-input',created['scope'].get('batch_id')==BATCH and 'tasks' not in created['scope'])
            check('confirmation-authorizes-platform-recheck',set(created['scope']['retry_platforms'])=={'xhs','zhihu','dy','bili'})
            page.screenshot(path=str(OUTPUT/'desktop.png'),full_page=True)
            # Chromium cannot reliably save a download from an intercepted fake
            # origin. Verify the link and response here; live download is separate.
            href=page.get_by_role('link',name='下载未完成 JSON').get_attribute('href')
            data=page.evaluate('async url => (await fetch(url)).json()',href)
            check('incomplete-download-route-contains-retry-input',len(data['tasks'])==1)
            page.set_viewport_size({'width':390,'height':844});page.screenshot(path=str(OUTPUT/'mobile.png'),full_page=True)
            check('mobile-no-horizontal-overflow',page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'))
            page.reload();page.get_by_role('link',name='下载未完成 JSON').wait_for();check('progress-restored-after-page-reload',page.get_by_text('本轮采集已结束',exact=True).is_visible())
            check('no-browser-errors',not errors)
        finally:context.close();browser.close()
    report={'checked_at':datetime.now(timezone.utc).isoformat(),'mode':'synthetic-own-headless-browser','checks':checks,'errors':errors}
    (OUTPUT/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'passed':sum(c['passed'] for c in checks),'total':len(checks)}))


if __name__=='__main__':main()
