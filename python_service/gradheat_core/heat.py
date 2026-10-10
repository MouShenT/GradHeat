"""Bounded, cached reads of committed public samples; never trigger a crawl."""

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
