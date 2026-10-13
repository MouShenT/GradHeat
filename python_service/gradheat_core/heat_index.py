"""Observed discussion and user searches on a bounded, comparable scale."""
from collections import defaultdict
from datetime import datetime, timezone, timedelta
import math

from .intelligence import date_value, number, VERSION


def daily_series(signal):
    values = {}
    for row in signal.get('daily', []):
        day = date_value(row.get('date')); value = number(row.get('value'))
        if day and value is not None and value >= 0:
            values[day.date()] = value
    return values


def heat_index(docs, signals, as_of):
    now = date_value(as_of) or datetime.now(timezone.utc)
    latest = {}
    for doc in sorted(docs, key=lambda x: x.get('observed_at') or ''):
        latest[(doc.get('platform'), doc.get('content_id') or doc.get('id'))] = doc
    mass = defaultdict(float)
    mapping = {'xhs': [('liked_count', 1), ('comment_count', 2), ('collected_count', 2)],
               'zhihu': [('voteup_count', 1), ('comment_count', 2)],
               'dy': [('digg_count', 1), ('comment_count', 2), ('collect_count', 2)],
               'bili': [('like', 1), ('reply', 2), ('favorite', 2), ('view', .04)]}
    for doc in latest.values():
        platform = doc.get('platform')
        if platform not in mapping: continue
        published = date_value(doc.get('published_at'))
        if published and published > now + timedelta(days=1): continue
        recency = .5 if published is None else math.exp(-max(0, (now-published).total_seconds()/86400)/90)
        metrics = doc.get('metrics') or {}
        interaction = sum(w*math.log1p(max(0, number(metrics.get(k)) or 0)) for k,w in mapping[platform])
        weight = number(doc.get('attribution_weight', 1))
        mass[platform] += max(0, min(1, weight if weight is not None else 0))*recency*(1+min(12,interaction)/4)
    platform_scores = {p:100*(1-math.exp(-m/35)) for p,m in mass.items()}
    social = sum(platform_scores.values())/len(platform_scores) if platform_scores else None
    # Latest comparable window per keyword/device. Overlapping repeated runs add no heat.
    observed = {}
    for signal in signals:
        if signal.get('kind') not in ('search-index', 'search-volume'): continue
        value,scale = number(signal.get('value')),number(signal.get('reference_scale'))
        start,end = date_value(signal.get('window_start')),date_value(signal.get('window_end'))
        coverage = number(signal.get('coverage',1))
        if value is None or scale is None or value<0 or scale<=0 or coverage is None or not 0<coverage<=1: continue
        if not signal.get('provider') or not signal.get('source_url') or not signal.get('keyword'): continue
        if not start or not end or start>end or (end-start).days>366 or not 0<=(now-end).total_seconds()/86400<=90: continue
        device=signal.get('device','all')
        if device in ('total','PC+移动'): device='all'
        key=(signal['provider'],signal['keyword'],signal.get('region','全国'),device)
        old=observed.get(key)
        order=(signal['window_end'],signal.get('observed_at') or '')
        if old is None or order>(old['window_end'],old.get('observed_at') or ''): observed[key]=signal
    # A provider's total already includes pc/mobile: never add them a second time.
    groups=defaultdict(list)
    for key,signal in observed.items(): groups[key[:3]].append(signal)
    search_scores=[];coverages=[];momentums=[]
    for group in groups.values():
        total=[s for s in group if s.get('device','all') in ('all','total','PC+移动')]
        chosen=total[:1] or group
        value=sum(s['value'] for s in chosen);scale=chosen[0]['reference_scale']
        if any(s['reference_scale']!=scale or s['window_start']!=chosen[0]['window_start'] or s['window_end']!=chosen[0]['window_end'] for s in chosen): continue
        coverage=min(s.get('coverage',1) for s in chosen)
        age=max(0,(now-date_value(chosen[0]['window_end'])).total_seconds()/86400)
        fresh=math.exp(-age/90)
        score=100*(1-math.exp(-value/scale))*fresh
        # Missing daily cells stay missing. Trend needs 5 observed days in each week.
        sequences=[daily_series(s) for s in chosen]
        days=set.intersection(*(set(d) for d in sequences)) if sequences else set()
        daily={day:sum(s[day] for s in sequences) for day in days}
        end=date_value(chosen[0]['window_end']).date()
        recent=[v for d,v in daily.items() if 0<=(end-d).days<7]
        previous=[v for d,v in daily.items() if 7<=(end-d).days<14]
        momentum=0
        if len(recent)>=5 and len(previous)>=5:
            current,prior=sum(recent)/len(recent),sum(previous)/len(previous)
            momentum=5*math.tanh(math.log((current+1)/(prior+1)))
            score=max(0,min(100,score+momentum*fresh))
            momentums.append(momentum)
        search_scores.append((score,coverage));coverages.append(coverage*fresh)
    search=sum(v*w for v,w in search_scores)/sum(w for _,w in search_scores) if search_scores else None
    score=.65*social+.35*search if social is not None and search is not None else social if social is not None else search
    confidence=(.65*min(1,sum(mass.values())/35)+.35*sum(coverages)/len(coverages)) if social is not None and search is not None else .65*min(1,sum(mass.values())/35) if social is not None else .35*sum(coverages)/len(coverages) if search is not None else 0
    return dict(heat_value=round(score,1) if score is not None else None,
                basis='discussion-and-search' if social is not None and search is not None else 'discussion-only' if social is not None else 'search-only' if search is not None else 'unavailable',
                discussion_value=round(social,1) if social is not None else None,search_value=round(search,1) if search is not None else None,
                unique_contents=len(latest),available_platforms=sorted(platform_scores),search_observations=len(search_scores),
                search_coverage=round(sum(coverages)/len(coverages),4) if coverages else None,
                search_momentum=round(sum(momentums)/len(momentums),2) if momentums else None,
                confidence_index=round(100*confidence,1),missing=['user-search-data'] if search is None else [],model=VERSION,as_of=as_of)
