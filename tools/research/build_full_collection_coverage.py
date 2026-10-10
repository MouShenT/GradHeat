"""Inventory what was actually obtained, separately from verified admissions facts."""
import argparse
from collections import Counter,defaultdict
import hashlib
import json
from pathlib import Path
import re
import sys
import unicodedata

import build_unit_dossiers as dossier
from social_evidence import encode, now

ROOT=dossier.ROOT
GENERATED_MARKER='<!-- gradheat:generated-unit-coverage -->'


def normalize(name):
    return re.sub(r'\s+','',unicodedata.normalize('NFKC',name))


def build(as_of):
    folder=ROOT/('.research/full-collection-'+as_of.replace('-',''))
    plan=dossier.read(folder/'plan.json')
    public_pointer=dossier.read(ROOT/'.research/admissions-data/latest.json')
    public=dossier.read(public_pointer['path'])
    manual=dossier.read(ROOT/'.research/manual-downloads/全量采集资料.json')['units']
    preferred={normalize(u['name']):u['name'] for u in manual}
    units={}
    for name in plan['units']:
        key=normalize(name)
        units.setdefault(key,dict(name=preferred.get(key,name),labels=[]))['labels'].append(name)
    infos={normalize(u['name']):u for u in plan['corpus']['units']}
    catalogues=defaultdict(list);histories=defaultdict(list)
    for row in public['programmes']:catalogues[normalize(row['unit'])].append(row)
    for row in public['history']:histories[normalize(row['unit'])].append(row)
    state=dossier.read(folder/'state.json',{})
    social=defaultdict(list)
    for job in state.values():social[normalize(job['unit'])].append(job)
    originals=defaultdict(list)
    for info in plan['corpus']['units']:
        for row in dossier.docs_for(info):
            if row.get('source_tier')!='primary' or dossier.source_score(row,info,row['year'])<=0:continue
            originals[normalize(info['name'])].append(row)
    seen={(r['unit'],r['url']) for rows in originals.values() for r in rows if r.get('unit')}
    # Fresh run metadata, including partial runs, is useful for access gaps.
    for batch in (ROOT/'.research/daily-update').glob(as_of.replace('-','')+'-*'):
        for row in dossier.read(batch/'sources.json',[]):
            if row.get('year') not in (2027,2026,2025):continue
            originals[normalize(row['unit'])].append(row)
    observations=[];gaps=[];index=[]
    existing=dossier.read(dossier.WORK/'summary.json',[])
    existing_paths={normalize(r['name']):Path(r['path']) for r in existing if isinstance(r,dict) and r.get('path')}
    # Some earlier summary formats wrap the list; use the actual existing MD.
    for path in (ROOT/'docs/units').glob('*/*.md'):existing_paths.setdefault(normalize(path.stem),path)
    for key,info in units.items():
        name=info['name'];cat=catalogues[key];history=histories[key];jobs=social[key]
        rows=list({(r['url'],r.get('sha256') or r.get('source_sha256')):r for r in originals[key]}.values())
        available={year:sum(r.get('year')==year and (r.get('retained') or r.get('status') in ('html-saved','file-saved','provider-passage-saved')) for r in rows) for year in (2027,2026,2025)}
        counts=Counter(j['state'] for j in jobs)
        record=dict(unit=name,aliases=info['labels'],as_of=as_of,official_retained_documents=available,
            catalogue_groups=len(cat),exam_matched_groups=sum(r.get('eligible_11408') is True for r in cat),
            history_rows={year:sum(r['year']==year for r in history) for year in (2026,2025)},
            social_job_states=dict(counts),social_snapshots=sum(j.get('snapshots',0) for j in jobs),
            media_missing=sum(j.get('media_missing',0) for j in jobs),
            verification_state='field-specific; raw collection does not prove a fact',
            official_publication_state='not-inferred-from-search-or-access-failure')
        observations.append(record)
        if not cat:gaps.append(dict(unit=name,year=2027,item='科目及分专业招生计划',reason='尚未形成目录逐行数据；未取得不等于未公布'))
        elif not any(r.get('plan_text') for r in cat):gaps.append(dict(unit=name,year=2027,item='分专业招生计划',reason='目录对象已有记录，人数仍未取得'))
        for year in (2026,2025):
            candidates=[r for r in history if r['year']==year]
            if not any(r.get('cutoff') is not None for r in candidates):gaps.append(dict(unit=name,year=year,item='相关专业复试线',reason='尚无同年度专业总分线记录'))
            if not any(r.get('admit_count') is not None or r.get('admitted_score_text') for r in candidates):gaps.append(dict(unit=name,year=year,item='录取人数及分数统计',reason='尚无同年度专业录取统计；有原件的仍需核正文与完整性'))
        path=existing_paths.get(key)
        # Refresh our coverage templates as new batches arrive. Keep the richer
        # priority dossiers and documents written by the user intact.
        generated = path is not None and GENERATED_MARKER in path.read_text(encoding='utf-8')
        legacy_generated = path is not None and path.parent == ROOT/'docs/units/其他招生单位' and (
            '本单位仍是候选对象；目录逐行确认和范围审核分别记录。' in path.read_text(encoding='utf-8')
            and '资料覆盖更新：' in path.read_text(encoding='utf-8'))
        if path is None or generated or legacy_generated:
            path=ROOT/'docs/units/其他招生单位'/(re.sub(r'[<>:"/\\|?*]','_',name)+'.md')
            md=[f'# {name}','',GENERATED_MARKER,'',f'面向2027入学，11408指101＋201＋301＋408，学硕和专硕均保留。本单位仍是候选对象；目录逐行确认和范围审核分别记录。','',f'资料覆盖更新：{now()}。','', '## 2027招生专业和计划','']
            if cat:
                md += ['| 院系 | 专业 | 学位／方式 | 科目 | 计划原文 | 状态 |','|---|---|---|---|---|---|']
                for r in cat:md.append('| '+' | '.join(dossier.cell(x) for x in [r.get('department'),str(r.get('major_code',''))+' '+str(r.get('major_name','')),str(r.get('degree_type',''))+'／'+str(r.get('mode','')),'+'.join(r.get('subjects',[])),r.get('plan_text'),r.get('plan_status')])+' |')
            else:md.append('尚未形成可列出的2027逐行目录，保留为待核候选。')
            md += ['', '## 2026和2025录取情况','', '| 年度 | 院系／专业 | 科目 | 复试线 | 复试人数 | 拟录取人数 | 录取分数 | 状态 |','|---|---|---|---|---|---|---|---|']
            for r in history:md.append('| '+' | '.join(dossier.cell(x) for x in [r['year'],str(r.get('department',''))+'／'+str(r.get('major_name','')),r.get('exam_text'),r.get('cutoff_text'),r.get('retest_text'),r.get('admit_text'),r.get('admitted_score_text'),r.get('status')])+' |')
            md += ['', '## 采集范围','',f'已留存官网资料数量：2027={available[2027]}，2026={available[2026]}，2025={available[2025]}。数量表示取得文档，不能证明专业范围或全部招生信息已验收。',f'社交查询状态：{dict(counts)}；已保存内容快照{record["social_snapshots"]}条。有限关键词样本不代表全站热度。','', '缺失信息见唯一的[缺失信息汇总](../缺失信息汇总.md)。未取得、访问失败、原文未注明以及官方明确未公布必须区别。来源与原件仍在后台证据库。','']
            path.parent.mkdir(parents=True,exist_ok=True);path.write_text('\n'.join(md),encoding='utf-8')
        index.append(dict(unit=name,path=str(path),**{k:v for k,v in record.items() if k!='unit'}))
    collected=dossier.read(folder/'summary.json',{})
    report=dict(as_of=as_of,checked_at=now(),candidate_labels=len(plan['units']),normalized_units=len(units),
        alias_duplicates=len(plan['units'])-len(units),public_version=public_pointer['version_id'],
        source_jobs=len(state),social_snapshots=sum(x['social_snapshots'] for x in observations),gaps=len(gaps),
        fully_collected=bool(collected.get('available_materials_complete',False)),all_information_verified=False,units=observations)
    dossier.dump(folder/'coverage.json',report);dossier.dump(folder/'coverage-gaps.json',gaps);dossier.dump(folder/'unit-files.json',index)
    # Append to the single existing gap document rather than creating per-unit
    # gap files or overwriting the priority institutions' detailed audit.
    gap_path=ROOT/'docs/units/缺失信息汇总.md'
    prior=gap_path.read_text(encoding='utf-8') if gap_path.exists() else '# 缺失信息汇总\n'
    marker=f'\n## 全量候选补充覆盖（{as_of}）'
    prior=prior.split(marker)[0]
    appendix=[marker,'',f'{len(plan["units"])}个候选名称规范化后为{len(units)}个对象；括号字符差异合并。候选范围不等于已确认符合2027年11408的招生单位。本表列未取得或未形成同年度数据的项目，不把未检索到解释为官方未公布。','', '| 单位 | 年度 | 缺失资料 | 原因 |','|---|---|---|---|']
    for g in gaps:appendix.append('| '+' | '.join(dossier.cell(g[k]) for k in ('unit','year','item','reason'))+' |')
    gap_path.write_text(prior+'\n'.join(appendix)+'\n',encoding='utf-8')
    return report


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--as-of',required=True);parser.add_argument('--vm',action='store_true');args=parser.parse_args()
    report=build(args.as_of)
    if args.vm:
        sys.path.insert(0,str(ROOT/'crawler'))
        from gradheat.vm_db import connect_vm
        from gradheat.material_store import archive
        folder=ROOT/('.research/full-collection-'+args.as_of.replace('-',''))
        with connect_vm(folder/'coverage-ingest') as con:
            with con.cursor() as cur:
                cur.execute("SELECT GET_LOCK('gradheat_material_archive',60)")
                if cur.fetchone()[0]!=1:raise RuntimeError('Archive busy; coverage preserved')
            try:stored=archive(con,[(folder/x,'collection-coverage') for x in ('coverage.json','coverage-gaps.json','unit-files.json','plan.json','expanded-corpus.json')],ROOT)
            finally:
                with con.cursor() as cur:cur.execute("SELECT RELEASE_LOCK('gradheat_material_archive')")
            run_id='coverage-'+hashlib.sha256(encode(report).encode()).hexdigest()[:24]
            with con.cursor() as cur:
                cur.execute('INSERT IGNORE INTO collection_run(run_id,started_at,summary_json) VALUES(%s,%s,%s)',(run_id,report['checked_at'],encode({k:v for k,v in report.items() if k!='units'})))
                for item in report['units']:
                    oid=hashlib.sha256(encode(dict(run_id=run_id,item=item)).encode()).hexdigest()
                    cur.execute('INSERT IGNORE INTO collection_observation(observation_id,run_id,unit_name,url,sha256,state,payload_json) VALUES(%s,%s,%s,%s,%s,%s,%s)',
                        (oid,run_id,item['unit'],'gradheat-internal:coverage',None,'coverage-incomplete',encode(item)))
            con.commit()
        report['database']=stored
    print(encode({k:v for k,v in report.items() if k!='units'}))


if __name__=='__main__':main()
