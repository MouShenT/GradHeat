"""Make a reproducible, offline comparison draft; no probability or pool certification."""
import hashlib,html,json,re,sqlite3
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
import build_unit_dossiers as d

def digest(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def run():
    units=d.read(d.WORK/'summary.json');names={x['name'] for x in units}
    catalogues=[x for x in d.load_catalogues() if x['unit'] in names and x.get('cohort')==2027]
    grouped=[]
    for unit in units:
        for row in d.catalogue_rows(dict(name=unit['name']),catalogues):
            row=dict(row)
            degree=row.get('degree_type')
            if degree in ('xs','zy','1','2'):
                row['degree_type_raw']=degree
                row['degree_type']={'xs':'学术学位','zy':'专业学位','1':'学术学位','2':'专业学位'}[degree]
            if row.get('eligible_11408') is True:assert row.get('subjects')==d.TARGET and row.get('route') not in ('仅推免','不招统考')
            row['id']=digest(row)[:24];grouped.append(row)
    stats=d.read(d.WORK/'admission-statistics-candidates.json');claims=d.load_claims()
    gaps=d.read(d.WORK/'missing-fields.json');availability=d.read(d.WORK/'material-availability.json')
    # The conflicting ISCAS page is visible in its dossier but never silently
    # participates in a 2025 comparative data view.
    stats=[x for x in stats if not (x['unit']=='中国科学院软件研究所' and x['year']==2025)]
    evidence=[];seen=set();hashes={}
    def add_source(unit,url,artifact,sha,kind,locator):
        if not artifact or not sha:return
        path=Path(artifact)
        if str(path) not in hashes:hashes[str(path)]=hashlib.sha256(path.read_bytes()).hexdigest()
        assert hashes[str(path)]==sha,(unit,url)
        key=(unit,url,sha)
        if key not in seen:
            seen.add(key);evidence.append(dict(id=digest(key)[:24],unit=unit,url=url,artifact=str(path),sha256=sha,kind=kind,locator=locator))
    for row in grouped:add_source(row['unit'],row['source_url'],row['source_artifact'],row['source_sha256'],'catalogue',row.get('locators'))
    for row in stats:add_source(row['unit'],row['source_url'],row['source_artifact'],row['source_sha256'],'admission_candidate',row['locators'])
    for row in claims:
        for s in row['sources']:add_source(row['unit'],s['url'],s['artifact'],s['sha256'],'original_checked_claim',s['locator'])
    inputs=[d.WORK/x for x in ['summary.json','supplement-catalogue-rows.json','reviewed-claims.json','supplement-reviewed-claims.json','first-pool-reviewed-claims.json','admission-statistics-candidates.json','material-availability.json','missing-fields.json'] if (d.WORK/x).exists()]+[d.ROOT/'.research/manual-downloads/已提取11408专业.json',Path(__file__),Path(d.__file__)]
    channel_claims=d.ROOT/'.research/channel-supplement-20261003/checked-claims.json'
    if channel_claims.exists():inputs.append(channel_claims)
    round_claims=d.ROOT/'.research/gap-round2-20261003/checked-claims.json'
    if round_claims.exists():inputs.append(round_claims)
    news_claims=d.ROOT/'.research/news-check-20261004/checked-claims.json'
    if news_claims.exists():inputs.append(news_claims)
    inputs += [d.WORK/x for x in ('daily-catalogue-rows.json','daily-reviewed-claims.json') if (d.WORK/x).exists()]
    dependencies=[dict(path=str(p.resolve()),sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in inputs]
    counts=dict(units=len(units),programme_source_groups=len(grouped),subject_matched_groups=sum(x.get('eligible_11408') is True for x in grouped),subject_matched_units=len({x['unit'] for x in grouped if x.get('eligible_11408') is True}),historical_candidate_groups=len(stats),original_checked_claims=len(claims),missing_fields=len(gaps),evidence_versions=len(evidence),raw_hashes_checked=len(hashes),approved_ranking_pools=0)
    payload=dict(as_of=d.REPORT_DATE,target_year=2027,stage='comparison-draft',units=units,programmes=grouped,history_candidates=stats,checked_claims=claims,availability=availability,gaps=gaps,evidence=evidence,counts=counts)
    snapshot_id=digest(dict(payload=payload,dependencies=dependencies))[:20]
    out=d.ROOT/f'.research/comparison-draft-20261003/{snapshot_id}';out.mkdir(parents=True,exist_ok=True)
    db=out/'comparison.sqlite';data=out/'comparison.json'
    if not db.exists():
        d.dump(data,payload)
        with sqlite3.connect(db) as con:
            con.execute('PRAGMA foreign_keys=ON')
            con.executescript('CREATE TABLE units(name TEXT PRIMARY KEY, category TEXT, dossier_path TEXT); CREATE TABLE programmes(id TEXT PRIMARY KEY, unit TEXT REFERENCES units(name), cohort INTEGER, eligible INTEGER, major_code TEXT, mode TEXT, plan_raw TEXT, evidence_sha256 TEXT, data_json TEXT); CREATE TABLE history_candidates(id TEXT PRIMARY KEY, unit TEXT REFERENCES units(name), cohort INTEGER, data_json TEXT); CREATE TABLE checked_claims(id TEXT PRIMARY KEY, unit TEXT REFERENCES units(name), cohort INTEGER, data_json TEXT); CREATE TABLE evidence(id TEXT PRIMARY KEY, unit TEXT REFERENCES units(name), sha256 TEXT, url TEXT, data_json TEXT); CREATE TABLE availability(unit TEXT PRIMARY KEY REFERENCES units(name), data_json TEXT); CREATE TABLE gaps(id INTEGER PRIMARY KEY, unit TEXT REFERENCES units(name), cohort INTEGER, field TEXT, data_json TEXT);')
            con.executemany('INSERT INTO units VALUES(?,?,?)',[(x['name'],x['group'],x['path']) for x in units])
            for x in grouped:con.execute('INSERT INTO programmes VALUES(?,?,?,?,?,?,?,?,?)',(x['id'],x['unit'],2027,None if x.get('eligible_11408') is None else int(x['eligible_11408']),x['major_code'],x.get('mode'),str(x['planned_major_raw']) if x.get('planned_major_raw') is not None else None,x['source_sha256'],json.dumps(x,ensure_ascii=False)))
            for table,rows in [('history_candidates',stats),('checked_claims',claims)]:
                for x in rows:con.execute('INSERT INTO '+table+' VALUES(?,?,?,?)',(digest(x)[:24],x['unit'],x['year'],json.dumps(x,ensure_ascii=False)))
            con.executemany('INSERT INTO evidence VALUES(?,?,?,?,?)',[(x['id'],x['unit'],x['sha256'],x['url'],json.dumps(x,ensure_ascii=False)) for x in evidence])
            con.executemany('INSERT INTO availability VALUES(?,?)',[(x['unit'],json.dumps(x,ensure_ascii=False)) for x in availability])
            con.executemany('INSERT INTO gaps(unit,cohort,field,data_json) VALUES(?,?,?,?)',[(x['unit'],x['year'],x['field'],json.dumps(x,ensure_ascii=False)) for x in gaps])
        # Read-only validation of a real, mixed-quality batch.
        with sqlite3.connect(f'file:{db.as_posix()}?mode=ro',uri=True) as con:
            assert con.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
            assert not con.execute('PRAGMA foreign_key_check').fetchall()
            for table,n in [('units',68),('programmes',len(grouped)),('history_candidates',len(stats)),('checked_claims',len(claims)),('evidence',len(evidence)),('gaps',len(gaps))]:assert con.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]==n
            # Unknown quotas remain SQL NULL; negative subject examples stay
            # outside the matched set; shared 5-person plan is one source group.
            assert con.execute("SELECT count(*) FROM programmes WHERE unit='西北农林科技大学' AND major_code='081200' AND eligible=1 AND plan_raw='5'").fetchone()[0]==1
            assert con.execute("SELECT count(*) FROM programmes WHERE unit='中山大学' AND major_code IN ('081200','085404','085410') AND eligible=1").fetchone()[0]==0
            assert con.execute('SELECT count(*) FROM programmes WHERE plan_raw IS NULL').fetchone()[0]==sum(x.get('planned_major_raw') is None for x in grouped)
        page=out/'comparison.html'
        page.write_text(render_html(payload),encoding='utf8')
        manifest=dict(snapshot_id=snapshot_id,state='draft',generated_at=datetime.now(timezone.utc).isoformat(),target_year=2027,as_of=d.REPORT_DATE,analysis='source-group descriptive comparison',approved_release=False,dependencies=dependencies,counts=counts,validation=dict(raw_artifact_hashes='passed',sqlite_integrity='passed',references='passed',shared_quota='passed',unknown_quota='preserved',ranking_pool_audit='pending'),outputs=[dict(path=p.name,sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in [data,db,page]])
        d.dump(out/'manifest.json',manifest)
    else:
        manifest=d.read(out/'manifest.json')
        for x in manifest['outputs']:assert hashlib.sha256((out/x['path']).read_bytes()).hexdigest()==x['sha256']
    d.dump(d.WORK/'comparison-draft-pointer.json',dict(snapshot_id=snapshot_id,path=str(out),counts=counts))
    report=['# 2027择校资料对照草稿','',f'更新：{d.REPORT_DATE}。采集已推进到“按专业比较”阶段；这是可用的资料草稿，尚未发布择校排名或概率。','',f'覆盖68个优先单位；{counts["programme_source_groups"]}个2027专业来源分组，其中{counts["subject_matched_units"]}个单位的{counts["subject_matched_groups"]}组四科完整匹配11408。方向合并仅用于显示，共享名额没有按方向相加；来源分组尚不是独立竞争池。','',f'历史侧保留{len(claims)}条原件资料级核对，以及{len(stats)}组官方名单统计候选。名单批次、院系、学习方式、专项分别留存，不混为最终录取数；软件所2025年度冲突的候选已从此对照草稿排除，原档案保留。','',d.local_link(out/'comparison.html','打开离线筛选对照页')+' · '+d.local_link(db,'SQLite数据')+' · '+d.local_link(out/'manifest.json','快照依赖与校验')+' · '+d.local_link(data,'完整结构化JSON'),'','筛选页可选单位、分组、科目状态、学位类型和学习方式；展开单位可查看资料级核对及历史统计候选。目录人数、推免/专项口径、来源与缺失可见。没有个人条件时，只做科目筛选，不判断个人报考资格。','','已核对的关键差异：','','- 同济计算机学硕和软件工程专硕样本是11408；院系页面282是上一年实际人数，含推免和专项，未填作2027计划。','- 山东计算机学硕目录统考2人，总计划40、推免38；不同方向共享专业计划，专项字段另存。','- 西北农林计算机学硕11408、拟公开招考5人，明确不含拟推免；三个方向共享5人，计划仍可调整。','- 华东师大已查询的计算机相关样本均不匹配11408；中山670学院学硕仅推免、专硕数学二。未检查的其他院系保持未知。','','剩余缺失见[唯一汇总](units/缺失信息汇总.md)。查无结果或访问受阻均不写“官网未公布”；只有官方明确、对应当前时点的声明才可标记未公布。','','后续按此快照继续核验匹配专业的报考限制、复试排序范围、推免及专项扣除口径，形成首批可审核竞争池；缺口可以后续增量补入。未经竞争池及时间审核，不将本草稿写成已验收的descriptive release，也不计算录取概率。']
    if (d.WORK/'first-pool-candidates.json').exists():
        report += ['', '已完成[首批专业范围核对草稿](FIRST-POOL-REVIEW-20261003.md)：杭电6个项目分别关联2027目录／章程和2026院系规则，普通统考净名额、2027排序范围与个人资格保持未知。']
    (d.ROOT/'docs/COMPARISON-DRAFT-20261003.md').write_text('\n'.join(report)+'\n',encoding='utf8')
    print(json.dumps(dict(snapshot_id=snapshot_id,path=str(out),**counts),ensure_ascii=False))

def render_html(payload):
    # JSON is non-executable source data. Escape closing script tags; values
    # displayed in the UI are escaped before any HTML insertion.
    encoded=json.dumps(payload,ensure_ascii=False).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
    return '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>2027择校资料对照</title><style>
body{font:15px/1.65 system-ui,sans-serif;margin:0;background:#f3f5f8;color:#18243a}main{max-width:1400px;margin:auto;padding:28px}h1{font-size:28px;margin:0 0 10px}.note{color:#4d617b}nav{position:sticky;top:0;background:#fff;padding:14px;border:1px solid #d7e0ee;border-radius:10px;display:flex;gap:9px;flex-wrap:wrap;z-index:2}input,select{font:inherit;padding:6px;border:1px solid #c1ccdb;border-radius:5px}table{width:100%;min-width:1120px;table-layout:fixed;border-collapse:collapse;background:white;font-size:13px}td,th{text-align:left;vertical-align:top;padding:9px;border-bottom:1px solid #dce3ed}th{background:#e8eff8}th:nth-child(1){width:14%}th:nth-child(2){width:22%}th:nth-child(3){width:9%}th:nth-child(4){width:17%}th:nth-child(5){width:10%}th:nth-child(6){width:28%}td,small{overflow-wrap:anywhere}small{display:block;color:#60718a}a{color:#245da8}details{background:#fff;margin:12px 0;padding:12px;border-radius:8px}summary{cursor:pointer;font-weight:600}.good{color:#17694a}.muted{color:#68748b}.wrap{overflow:auto}footer{margin:24px 0;color:#52647d}</style><main><h1>2027择校资料对照</h1><p class="note">68个优先单位 · 101＋201＋301＋408 · 学硕和专硕<br>资料草稿：资格与竞争池未审核。缺失保持未知，来源分组不等于排名池，历史分数不转成录取概率。</p><nav><input id="search" placeholder="院校、专业或院系关键词"><select id="unit"><option value="">全部单位</option></select><select id="group"><option value="">全部分组</option><option>985</option><option>计算机强校</option><option>研究所</option></select><select id="elig"><option value="1">11408科目匹配</option><option value="all">全部科目状态</option><option value="0">已知不匹配</option><option value="unknown">科目未知</option></select><select id="degree"><option value="">全部学位</option><option>学术学位</option><option>专业学位</option></select><select id="mode"><option value="">全部学习方式</option><option>全日制</option><option>非全日制</option></select></nav><p id="count"></p><div class="wrap"><table><thead><tr><th>单位／院系</th><th>专业／方向</th><th>学位／方式</th><th>科目与初筛</th><th>目录人数原值</th><th>来源及口径</th></tr></thead><tbody id="programmes"></tbody></table></div><h2>单位资料与两年历史</h2><div id="history"></div><footer>同一专业各方向共享的人数不相加；不同年度、批次、专项和考试变化不合并。第三方与未复核名单候选保持标签。缺口后续增量补采。</footer></main><script type="application/json" id="data">'''+encoded+r'''</script><script>
const d=JSON.parse(document.querySelector('#data').textContent),$=id=>document.getElementById(id),esc=x=>String(x??'未知').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),url=x=>/^https?:\/\//.test(x)?esc(x):'#';
d.units.forEach(u=>$('unit').insertAdjacentHTML('beforeend',`<option>${esc(u.name)}</option>`));
function render(){let q=$('search').value.trim(),unit=$('unit').value,g=$('group').value,e=$('elig').value,degree=$('degree').value,mode=$('mode').value;
let units=d.units.filter(u=>(!unit||u.name===unit)&&(!g||u.group===g)),names=new Set(units.map(u=>u.name));
let rows=d.programmes.filter(r=>names.has(r.unit)&&(!q||[r.unit,r.department,r.major_name,r.major_code].join(' ').includes(q))&&(!degree||r.degree_type===degree)&&(!mode||r.mode===mode)&&(e==='all'||e==='1'&&r.eligible_11408===true||e==='0'&&r.eligible_11408===false||e==='unknown'&&r.eligible_11408==null));
$('count').textContent=`显示 ${rows.length} 个专业来源分组，涉及 ${new Set(rows.map(r=>r.unit)).size} 个单位。来源版本可能重复描述同一项目，不合计总招生人数。`;
$('programmes').innerHTML=rows.map(r=>`<tr><td>${esc(r.unit)}<small>${esc(r.department)}</small></td><td>${esc(r.major_code)} ${esc(r.major_name)}<small>${esc([...new Set(r.directions)].join('；'))}</small>${r.campus?'<small>校区：'+esc(r.campus)+'</small>':''}${r.comparison_pool_scope?'<small>来源范围：'+esc(r.comparison_pool_scope)+'</small>':''}</td><td>${esc(r.degree_type)}<small>${esc(r.mode)}</small></td><td>${esc((r.subjects||[]).join('+')||r.subjects_raw)}<small class="${r.eligible_11408===true?'good':'muted'}">${r.eligible_11408===true?'科目匹配；个人资格未审核':r.eligible_11408===false?'不匹配／非统考':'未知'}</small></td><td>${esc(r.planned_major_raw)}${(r.recommended_plan_raw??r.push_plan_original)!=null?'<small>推免原值：'+esc(r.recommended_plan_raw??r.push_plan_original)+'</small>':''}${(r.direction_details||[]).length?'<details><summary>方向人数原值</summary>'+r.direction_details.map(v=>'<small>'+esc(v.direction)+'：'+esc(v.plan_raw)+'</small>').join('')+'</details>':''}</td><td><a href="${url(r.source_url)}" target="_blank" rel="noopener noreferrer">官方原件</a><small>${esc(r.quota_definition)}${r.quota_scope?'；'+esc(r.quota_scope):''}${r.major_plan_scope?'；'+esc(r.major_plan_scope):''}</small>${(r.plan_sources||[]).map(s=>'<a target="_blank" rel="noopener noreferrer" href="'+url(s.url)+'">官方计划表</a>').join(' · ')}<details><summary>证据定位</summary><small>${esc(r.source_sha256)} · ${esc((r.locators||[]).join('；'))}</small></details></td></tr>`).join('');
$('history').innerHTML=units.filter(u=>!q||u.name.includes(q)||rows.some(r=>r.unit===u.name)).map(u=>{let gaps=d.gaps.filter(x=>x.unit===u.name),cs=d.checked_claims.filter(x=>x.unit===u.name),ss=d.history_candidates.filter(x=>x.unit===u.name);return `<details><summary>${esc(u.name)} · 原件核对 ${cs.length} · 名单候选 ${ss.length} · 缺失字段 ${gaps.length}</summary><p>缺失：${esc(gaps.map(x=>x.year+' '+x.field).join('；')||'当前分类已有至少部分资料，完整性未审核')}</p>${cs.map(x=>`<p><b>${x.year} ${esc(x.pool)}</b><br>${esc(x.claim)}<small>${esc(x.verification)}；${esc(x.limitation)}</small>${x.sources.map(s=>'<a target="_blank" rel="noopener noreferrer" href="'+url(s.url)+'">原件</a>').join(' · ')}</p>`).join('')}${ss.length?'<div class="wrap"><table><tr><th>年／名单原分组</th><th>备注</th><th>可解析公示行</th><th>初试最低—最高／均分</th><th>来源</th></tr>'+ss.map(x=>`<tr><td>${x.year} ${esc(x.pool)}</td><td>${esc(x.special)}</td><td>${x.n}</td><td>${x.minimum}—${x.maximum}／${x.mean.toFixed(2)}</td><td><a target="_blank" rel="noopener noreferrer" href="${url(x.source_url)}">未全量复核候选</a></td></tr>`).join('')+'</table></div>':''}</details>`}).join('');}
['search','unit','group','elig','degree','mode'].forEach(id=>['input','change'].forEach(event=>$(id).addEventListener(event,render)));render();
</script></html>'''

if __name__=='__main__':run()
