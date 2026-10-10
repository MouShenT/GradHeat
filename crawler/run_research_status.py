"""Read one MySQL research batch and export its review status without database writes."""
import argparse
from collections import Counter,defaultdict
from datetime import datetime,timezone
import json,re
from pathlib import Path
from gradheat.vm_db import connect_vm

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'.research/research-status'

def read_status(con,batch_id=None):
    # Pin one consistent snapshot and explicitly disallow writes in this transaction.
    with con.cursor() as cur:
        cur.execute('SET TRANSACTION READ ONLY')
        cur.execute('START TRANSACTION WITH CONSISTENT SNAPSHOT')
        if batch_id:
            cur.execute('SELECT batch_id,as_of_date,target_year,source_snapshot,state,manifest_json FROM research_import_batch WHERE batch_id=%s',(batch_id,))
        else:
            cur.execute('SELECT batch_id,as_of_date,target_year,source_snapshot,state,manifest_json FROM research_import_batch ORDER BY as_of_date DESC,created_at DESC,batch_id DESC LIMIT 1')
        selected=cur.fetchone()
        if not selected:raise RuntimeError('No imported research batch found')
        batch,as_of,year,snapshot,state,manifest_raw=selected;manifest=json.loads(manifest_raw)
        cur.execute('SELECT r.record_id,r.kind,r.unit_name,r.cohort,r.verification_state,r.eligible_11408,r.plan_raw,r.ordinary_quota,r.payload_json FROM research_record r JOIN research_batch_record b ON b.record_id=r.record_id WHERE b.batch_id=%s',(batch,))
        keys=['record_id','kind','unit','year','state','eligible','plan_raw','ordinary_quota','payload']
        records=[dict(zip(keys,r)) for r in cur.fetchall()]
        for r in records:r['payload']=json.loads(r['payload'])
        counts=dict(Counter(r['kind'] for r in records))
        if counts!=manifest['counts']:raise RuntimeError('Manifest and current batch differ')
        cur.execute('SELECT i.batch_id,i.as_of_date,i.manifest_json,COALESCE(b.n,0) FROM research_import_batch i LEFT JOIN (SELECT batch_id,COUNT(*) n FROM research_batch_record GROUP BY batch_id) b ON b.batch_id=i.batch_id ORDER BY i.as_of_date,i.created_at')
        batches=[dict(batch_id=b,as_of=str(t),records=n,manifest_records=json.loads(m)['records']) for b,t,m,n in cur.fetchall()]
        if any(b['records']!=b['manifest_records'] for b in batches):raise RuntimeError('Historical batch membership changed')
        cur.execute('SELECT COUNT(*) FROM research_record');version_count=cur.fetchone()[0]
    con.rollback()
    units={r['unit']:r['payload'] for r in records if r['kind']=='unit'};by_unit=defaultdict(list)
    for r in records:by_unit[r['unit']].append(r)
    programme=[r for r in records if r['kind']=='programme'];matched=[r for r in programme if r['eligible']==1]
    gaps=[r for r in records if r['kind']=='gap'];history=[r for r in records if r['kind']=='admission_statistics_candidate']
    status=dict(as_of=str(as_of),target_year=year,batch_id=batch,source_snapshot=snapshot,state=state,generated_at=datetime.now(timezone.utc).isoformat(),database_read_only=True,counts=counts,records=len(records),stored_record_versions=version_count,retained_batches=batches,subject_matched_groups=len(matched),subject_matched_units=len({r['unit'] for r in matched}),matched_groups_without_raw_plan=sum(r['plan_raw'] is None for r in matched),matched_groups_without_verified_ordinary_quota=sum(r['ordinary_quota'] is None for r in matched),missing_fields=len(gaps),units_with_missing_fields=len({r['unit'] for r in gaps}),missing_by_year_field=[dict(year=y,field=f,n=n) for (y,f),n in sorted(Counter((r['year'],r['payload']['field']) for r in gaps).items())],history_candidates=len(history),excluded_history_conflicts=sum(r['state']=='conflicted' for r in history),approved_ranking_pools=0,units=[])
    for name,u in sorted(units.items()):
        rows=by_unit[name];ps=[r for r in rows if r['kind']=='programme' and r['eligible']==1]
        claims=[r for r in rows if r['kind']=='checked_claim']
        status['units'].append(dict(unit=name,group=u['group'],dossier_path=u['path'],subject_matched_groups=len(ps),raw_plans_present=sum(r['plan_raw'] is not None for r in ps),ordinary_quotas_verified=sum(r['ordinary_quota'] is not None for r in ps),checked_claims=len(claims),history_candidate_groups=sum(r['kind']=='admission_statistics_candidate' for r in rows),missing_fields=sum(r['kind']=='gap' for r in rows),next_review='报考条件、共享计划/专项、2027复试排序范围' if ps else '补核2027科目；保持未知或已知不匹配'))
    return status

def markdown(x):
    lines=['# 研究数据总览','',f"核查日期：{x['as_of']}。只读查询真实MySQL，固定批次 `{x['batch_id']}`。",'',f"当前批次{len(x['units'])}单位、{x['records']:,}条研究记录；{x['subject_matched_units']}单位的{x['subject_matched_groups']}个专业来源分组匹配11408。来源分组尚未审核为独立竞争池。",'',f"尚未取得信息：{x['units_with_missing_fields']}单位、{x['missing_fields']}项，详细内容只维护[唯一缺失汇总](<D:/aaopenclow-share/Graduate_school_selection/docs/units/缺失信息汇总.md>)。匹配组中{x['matched_groups_without_raw_plan']}组未取得原始人数；普通统考净名额已核对的为{x['subject_matched_groups']-x['matched_groups_without_verified_ordinary_quota']}组。目录原值不是净名额。",'',f"历年名单统计候选{x['history_candidates']}组，其中{x['excluded_history_conflicts']}组年度冲突从对照排除。原件核对{ x['counts'].get('checked_claim',0)}条；第三方资料单独保留。",'',f"库内保存{len(x['retained_batches'])}个批次、{x['stored_record_versions']:,}条内容版本；只统计所选批次的记录关联，没有把历史版本再相加。各批次关联数量与其原清单一致。",'','## 项目推进位置','','资料采集 → 原件核对 → MySQL研究批次 → 可筛选专业对照已接通。接下来按匹配专业核对报考条件、净名额和2027复试排序范围，再建立竞争池；当前保持描述草稿，不发布概率或强弱排序。','','## 当前逐校状态','','| 单位 | 分组 | 科目匹配来源组 | 有原始人数的组 | 原件核对条数 | 缺失字段数 | 下步核对 |','|---|---|---|---|---|---|---|']
    for u in sorted(x['units'],key=lambda u:(-u['subject_matched_groups'],u['unit'])):
        lines.append(f"| [{u['unit']}](<{Path(u['dossier_path']).as_posix()}>) | {u['group']} | {u['subject_matched_groups']} | {u['raw_plans_present']} | {u['checked_claims']} | {u['missing_fields']} | {u['next_review']} |")
    return '\n'.join(lines)+'\n'

def run():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--vm',action='store_true',required=True);parser.add_argument('--batch');args=parser.parse_args()
    if args.batch and not re.fullmatch(r'[0-9a-f]{64}',args.batch):parser.error('--batch requires a complete SHA-256 batch id')
    with connect_vm(OUT) as con:status=read_status(con,args.batch)
    folder=OUT/status['batch_id'];folder.mkdir(parents=True,exist_ok=True)
    (folder/'status.json').write_text(json.dumps(status,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    (folder/'status.md').write_text(markdown(status),encoding='utf8')
    (OUT/'latest.json').write_text(json.dumps(dict(batch_id=status['batch_id'],path=str(folder)),ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps({k:v for k,v in status.items() if k!='units'},ensure_ascii=False,indent=2))
    print(str(folder/'status.md'))

if __name__=='__main__':run()
