"""Bounded, cached reads of committed public samples; never trigger a crawl."""
from collections import defaultdict
from datetime import datetime,timezone
import hashlib,json,sys,threading,time
from pathlib import Path
from .reviewed_inputs import read_reviewed_json

PLATFORMS={'xhs':'小红书','zhihu':'知乎','dy':'抖音','bili':'B站'}
METRICS={'xhs':{'like':'liked_count','comment':'comment_count','favorite':'collected_count','view':None},
    'zhihu':{'like':'voteup_count','comment':'comment_count','favorite':None,'view':None},
    'dy':{'like':'digg_count','comment':'comment_count','favorite':'collect_count','view':None},
    'bili':{'like':'like','comment':'reply','favorite':'favorite','view':'view'}}


def summarize(docs,unit,health,checked_at,truncated=False):
    result=[]
    for platform,label in PLATFORMS.items():
        unique={}
        for doc in sorted(docs,key=lambda d:d.get('observed_at') or ''):
            if doc.get('platform')==platform and str(doc.get('query') or '').startswith(unit+' '):
                unique[doc['content_id']]=doc
        rows=list(unique.values());metrics={}
        for metric,key in METRICS[platform].items():
            values=[(d.get('metrics') or {}).get(key) if key else None for d in rows]
            known=[v for v in values if isinstance(v,int) and not isinstance(v,bool) and v>=0]
            metrics[metric]=dict(sum_known_values=sum(known) if known else None,known_contents=len(known),unknown_contents=len(rows)-len(known))
        result.append(dict(platform=platform,label=label,unique_contents=len(rows),sampling_state='sample-available' if rows else 'no-stored-sample',
            metrics=metrics,observed_until=max((d.get('observed_at') or '' for d in rows),default=None),
            query_groups=[dict(query=q,actual_sort=s) for q,s in sorted({(d.get('query'),d.get('query_sort')) for d in docs
                if d.get('platform')==platform and str(d.get('query') or '').startswith(unit+' ')},key=str)],
            health=health.get(platform,{'state':'unknown'}),trend=None))
    return dict(unit=unit,checked_at=checked_at,platforms=result,truncated=truncated,read_state='mysql-read',
        whole_platform_total=None,trend=None,applicant_count=None,admission_probability=None,
        note='实时刷新已存样本；样本数与互动不代表全站热度。无样本不等于热度为零，不同查询/排序不计算增长。')


class HeatStore:
    def __init__(self,root):self.root=Path(root).resolve();self.cache={};self.lock=threading.RLock()

    def health(self):
        result={}
        for platform in PLATFORMS:
            path=self.root/'.research/social/platform-health'/f'{platform}.json'
            try:
                item=json.loads(path.read_text(encoding='utf-8'))
                result[platform]={k:item.get(k) for k in ('state','checked_at')}
            except (OSError,ValueError):result[platform]={'state':'unknown','checked_at':None}
        return result

    def read(self,unit):
        with self.lock:
            cached=self.cache.get(unit)
            if cached and time.monotonic()-cached[0]<60:
                health=self.health()
                return dict(cached[1],health_checked_at=datetime.now(timezone.utc).isoformat(),platforms=[dict(p,health=health.get(p['platform'])) for p in cached[1]['platforms']])
            sys.path.insert(0,str(self.root/'crawler'))
            from gradheat.vm_db import connect_vm
            from gradheat.material_store import encode
            try:
                docs=[]
                with connect_vm(self.root/'.research/workbench-heat/private') as con:
                    with con.cursor() as cur:
                        cur.execute("SELECT run_id FROM social_collection_run WHERE JSON_CONTAINS(JSON_EXTRACT(summary_json,'$.selected_units'),JSON_QUOTE(%s)) ORDER BY started_at DESC LIMIT 200",(unit,))
                        runs=[row[0] for row in cur.fetchall()]
                        if runs:
                            cur.execute('SELECT snapshot_id,payload_json FROM social_content_snapshot WHERE run_id IN ('+','.join(['%s']*len(runs))+') ORDER BY observed_at DESC LIMIT 1000',tuple(runs))
                            rows=cur.fetchall()
                            for sid,raw in rows:
                                doc=json.loads(raw)
                                if doc.get('id')!=sid or doc.get('run_id') not in runs or hashlib.sha256(encode({k:v for k,v in doc.items() if k!='id'}).encode()).hexdigest()!=sid:raise ValueError('Snapshot integrity mismatch')
                                docs.append(doc)
                        else:rows=[]
                    con.rollback()
                data=summarize(docs,unit,self.health(),datetime.now(timezone.utc).isoformat(),len(runs)==200 or len(rows)==1000)
                self.cache[unit]=(time.monotonic(),data);return data
            except Exception as error:
                if cached:return dict(cached[1],read_state='using-last-verified-cache',refresh_error=type(error).__name__)
                package=read_reviewed_json(self.root,'.research/agent-social-summary-20261009/public-input-20261009T052721Z.json')
                if package:
                    for item in package.get('units',[]):
                        if item['unit']==unit:
                            platforms=[]
                            for p in item.get('platforms',[]):
                                platforms.append({k:p.get(k) for k in ('platform','label','sampling_state','unique_contents','metrics','observed_until','trend')}|{'health':self.health().get(p['platform']),
                                    'query_groups':[{k:q.get(k) for k in ('query','actual_sort')} for q in p.get('query_groups',[])]})
                            return dict(unit=unit,platforms=platforms,read_state='previous-verified-sample',checked_at=package['generated_at'],note='使用此前已核样本，本次连接未刷新；采样时间按各平台原值。')
                return dict(unit=unit,platforms=[],read_state='unavailable',refresh_error=type(error).__name__,note='样本读取暂不可用，不记热度为零。')
