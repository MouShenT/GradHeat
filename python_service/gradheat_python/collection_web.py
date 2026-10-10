"""Local collection controls; large raw downloads never enter AMQP messages."""
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from .collection_plan import prepare_input,read_plan,load_state


class CollectionWeb:
    def __init__(self,root):self.root=root;self.browser_process=None

    def batch(self,batch_id):
        if not re.fullmatch(r'batch-[0-9]{8}-[a-f0-9]{12}',batch_id):raise ValueError('Invalid batch identifier')
        path=(self.root/'.research/autonomous-collection'/batch_id).resolve()
        if not path.is_relative_to((self.root/'.research/autonomous-collection').resolve()) or not path.is_dir():raise ValueError('Batch missing')
        return path

    def prepare(self,source):
        try:folder,plan=prepare_input(self.root,source)
        except (TypeError,KeyError,AttributeError):raise ValueError('Invalid collection input shape') from None
        return {'batch_id':folder.name,'plan_sha':plan['plan_sha'],'input_sha':plan['input_sha'],
            'planned_jobs':len(plan['jobs']),'platforms':sorted({j.get('platform',j['type']) for j in plan['jobs']})}

    def open_browser(self):
        if os.name!='nt':raise ValueError('Browser login belongs to Windows collector')
        if self.browser_process is not None and self.browser_process.poll() is None:
            return {'state':'opening','reused':True}
        folder=self.root/'.research/collection-web';folder.mkdir(parents=True,exist_ok=True)
        with (folder/'browser.private.log').open('ab') as log:
            self.browser_process=subprocess.Popen([sys.executable,'-X','utf8','-B',str(self.root/'tools/research/open_social_login.py')],
                cwd=self.root,stdin=subprocess.DEVNULL,stdout=log,stderr=log,
                creationflags=subprocess.CREATE_NO_WINDOW)
        return {'state':'opening','reused':False}

    def browser_status(self):
        sys.path.insert(0,str(self.root/'tools/research'))
        from open_social_login import browser_health
        from collect_social_sources import platform_health
        port=int(json.loads((self.root/'contracts/social-collection.json').read_text(encoding='utf-8'))['cdp_port'])
        return {'browser_available':browser_health(port),
            'opening':self.browser_process is not None and self.browser_process.poll() is None,
            'error_code':'browser-launch-failed' if self.browser_process is not None and self.browser_process.poll() not in (None,0) else None,
            'login_confirmed':False,'restricted_platforms':[p for p,h in platform_health().items() if h.get('state')=='needs-human']}

    def progress(self,batch_id):
        folder=self.batch(batch_id);plan=read_plan(folder);state=load_state(folder)
        rows=state['jobs'].values();counts={}
        for row in rows:counts[row['state']]=counts.get(row['state'],0)+1
        complete=counts.get('committed',0)
        # Separate raw storage from completeness; never return source URLs or local paths.
        return {'batch_id':batch_id,'plan_sha':plan['plan_sha'],'planned_jobs':len(plan['jobs']),
            'processed_jobs':sum(1 for r in rows if r['state']!='running'),'complete_jobs':complete,
            'incomplete_jobs':sum(1 for r in rows if r['state'] not in ('committed','running')),
            'unattempted_jobs':len(plan['jobs'])-len(state['jobs']), 'states':counts,
            'downloads':{'incomplete':(folder/'incomplete.json').is_file(),'handoff':(folder/'handoff.zip').is_file()},
            'needs_analysis':True}

    def download(self,batch_id,kind):
        if kind not in ('incomplete','handoff'):raise ValueError('Unknown download')
        folder=self.batch(batch_id);path=folder/('incomplete.json' if kind=='incomplete' else 'handoff.zip')
        if not path.is_file():raise ValueError('Output not ready')
        return path
