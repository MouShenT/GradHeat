'use strict';
const $=id=>document.getElementById(id),escape=x=>String(x??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let data=null,view='plans',dataVersion=null,comparisonArchiveReady=false;
let selected=new Set();
try{selected=new Set(JSON.parse(localStorage.getItem('gradheat-admissions-selection')||'[]'));}catch{}
const number=x=>x==null?'—':typeof x==='number'?Number(x.toFixed(2)):x;
const ratio=x=>x==null?'—':`${x.toFixed(2)} : 1`;
const department=x=>String(x||'').replace(/^\d+\s*/,'').trim();
const col=(key,label,width,value,sort)=>({key,label,width,value,sort});
const combined=(...values)=>values.filter(x=>x!=null&&x!=='').join(' / ');
const planNumber=p=>{const m=String(p.plan_text||'').match(/\d+/g);return m?.length===1?Number(m[0]):p.plan_text;};
const fieldTag=(r,f)=>{
 const v=r.verification?.[f];if(!v)return '';
 if(v.state==='conflict')return '<small class="field-pending">官方数值冲突</small>';
 const matched=(v.parts||[]).filter(p=>['two-source-agreement','three-source-agreement'].includes(p.state));
 const agreement=v.state==='three-source-agreement'?'三源一致':'两源一致';
 if(['two-source-agreement','three-source-agreement'].includes(v.state))return `<small class="field-agreed">${f==='cutoff_text'||f==='cutoff'?'总分线':''}${agreement}</small>`;
 if(matched.length)return `<small class="field-agreed">部分信息${matched.every(p=>p.state==='three-source-agreement')?'三源一致':'两源一致'}</small>`;
 return '';
};
const statusTag=s=>`<span class="tag ${/[两三]源一致/.test(String(s))?'agreed':''}">${escape(s)}</span>`;
const tables={
 plan:new GradTable.ColumnTable($('plan-table'),[
  col('unit','院校 / 院系',19,p=>combined(p.unit,p.department,p.campus)),col('major','专业 / 方向',21,p=>combined(p.major_name,p.major_code,...(p.directions||[]))),
  col('degree','学位 / 方式',13,p=>combined(p.degree_type,p.mode)),col('subjects','考试科目',13,p=>p.subjects.join(' / ')),
  col('plan','招生计划',23,p=>p.plan_text,planNumber),col('compare','比较',11,p=>selected.has(p.id)?'已加入':'未加入')],render),
 history:new GradTable.ColumnTable($('history-table'),[
  col('unit','院校 / 院系',17,r=>combined(r.unit,r.department)),col('major','年度 / 专业',17,r=>combined(r.year,r.major_name,r.exam_text)),
  col('cutoff','复试线',8,r=>r.cutoff_text,r=>r.cutoff??r.cutoff_text),col('retest','复试人数',10,r=>r.retest_text,r=>r.retest_count??r.retest_text),
  col('admit','拟录取人数',10,r=>r.admit_text,r=>r.admit_count??r.admit_text),col('ratio','复录比',9,r=>ratio(r.interview_admit_ratio),r=>r.interview_admit_ratio),
  col('score','录取分数统计',15,r=>r.admitted_score_text),col('status','数据状态',14,r=>r.status)],render),
 line:new GradTable.ColumnTable($('line-table'),[col('unit','院校',24,r=>r.unit),col('year','年度',12,r=>r.year),col('scope','范围',34,r=>r.label),col('cutoff','复试线',15,r=>r.cutoff),col('status','状态',15,r=>r.status)],render),
 list:new GradTable.ColumnTable($('list-table'),[col('unit','院校 / 年度',18,r=>combined(r.unit,r.year)),col('scope','统计范围',27,r=>combined(r.scope,r.exam_text)),col('n','提取人数',11,r=>r.n),col('range','最低 / 最高',15,r=>combined(r.minimum,r.maximum),r=>r.minimum),col('average','均分 / 中位数',17,r=>combined(r.mean,r.median),r=>r.mean),col('status','状态',12,r=>r.status)],render)
};
document.querySelectorAll('[data-reset-table]').forEach(b=>b.addEventListener('click',()=>tables[b.dataset.resetTable].reset()));
function textmatch(row){return Object.values(row).filter(x=>typeof x==='string').join(' ').toLowerCase().includes($('search').value.trim().toLowerCase());}
function common(row){return (!$('unit').value||row.unit===$('unit').value)&&(!$('group').value||data.units.find(u=>u.name===row.unit)?.group===$('group').value)&&textmatch(row);}
function rows(){return data.programmes.filter(p=>common(p)&&(!$('mode').value||p.mode===$('mode').value)&&(!$('degree').value||p.degree_type===$('degree').value)&&($('eligibility').value==='all'||p.eligible_11408===true));}
function historical(row){return common(row)&&($('history-year').value==='all'||row.year===Number($('history-year').value));}
function subjectScope(row){return $('eligibility').value==='all'||/^11408$/.test((row.exam_text||'').trim());}
function saveSelection(){localStorage.setItem('gradheat-admissions-selection',JSON.stringify([...selected]));}
function setView(next){view=next;document.querySelectorAll('.view').forEach(n=>n.hidden=n.id!==next);document.querySelectorAll('[data-view]').forEach(n=>n.classList.toggle('active',n.dataset.view===next));const captions={visuals:["院校数据，一眼看清","计划与专业历史按统计范围分别展示。"],heat:["多平台关注情况","实时刷新已存样本，实际采样时间单独保留。"],recommend:["按专业、层次和本科背景条件筛选","无需分数；未知的双非友好证据保持待核。"],game:["看看拥挤选择如何变化","假设容量和需求由你填写，模拟不代表实际报考或录取。"],plans:['今年，哪些专业值得关注？','查看招生计划、考试科目和培养方式，加入比较清单。'],history:['把往年的录取情况看清楚','复试线、复试人数、拟录取人数与分数统计，按年度分别查看。'],compare:['放在一起，逐项比较','招生计划与对应的专业历史数据并排展示。'],preferences:['把候选院校，放进你的选择里','填写条件与偏好，查看权重变化是否影响选择，并保存本次结果。']};$('page-title').textContent=captions[next][0];$('subtitle').textContent=captions[next][1];document.querySelector('.filters').hidden=['compare','preferences','heat','recommend','game'].includes(next);window.scrollTo({top:0,behavior:'instant'});for(const id of ['degree','mode'])$(id).disabled=next==='history';render();window.dispatchEvent(new CustomEvent('gradheat-view',{detail:next}));}
function render(){
 if(!data)return;
 $('global-filter-summary').textContent=[$('eligibility').value==='matched'?'11408':'全部科目',$('unit').value||'全部单位',$('group').value,$('degree').value,$('mode').value,$('search').value?'关键词已筛选':''].filter(Boolean).join(' · ');
 const plans=tables.plan.rows(rows());$('plan-count').textContent=`${new Set(plans.map(p=>p.unit)).size} 个单位 · ${plans.length} 个专业`;
 $('plan-body').innerHTML=plans.map(p=>`<tr><td><strong>${escape(p.unit)}</strong><small>${escape(p.department||'院系待补')}</small>${p.campus?`<small>${escape(p.campus)}</small>`:''}</td><td><strong>${escape(p.major_name)}</strong><small>${escape(p.major_code)}</small><small>${escape(p.directions?.join(' / '))}</small></td><td>${escape(p.degree_type)}<small>${escape(p.mode)}</small></td><td>${escape(p.subjects.join(' / ')||'科目待补')}<small>${p.eligible_11408===true?'11408':p.eligible_11408===false?'其他科目组合':'科目待核'}</small></td><td>${escape(p.plan_text)}<small>普通统考名额：${number(p.ordinary_quota)}</small>${statusTag(p.plan_status)}${p.publication_stage?`<small>${escape(p.publication_stage)}</small>`:''}</td><td class="plan-actions"><button class="${selected.has(p.id)?'secondary':'primary'}" data-select="${p.id}">${selected.has(p.id)?'已加入':'加入比较'}</button></td></tr>`).join('');$('plan-empty').hidden=plans.length>0;
 const history=tables.history.rows(data.history.filter(r=>historical(r)&&subjectScope(r)));$('history-count').textContent=`${new Set(history.map(r=>r.unit)).size} 个单位 · ${history.length} 行历史统计${$('eligibility').value==='matched'?' · 仅明确11408的行':''}`;
 $('history-body').innerHTML=history.map(r=>`<tr><td><strong>${escape(r.unit)}</strong><small>${escape(r.department)}</small></td><td>${r.year}<small>${escape(r.major_name)}</small><small>${escape(r.exam_text)}</small></td><td>${escape(r.cutoff_text)}${fieldTag(r,"cutoff_text")}</td><td>${escape(r.retest_text)}${fieldTag(r,"retest_text")}</td><td>${escape(r.admit_text)}${fieldTag(r,"admit_text")}</td><td>${ratio(r.interview_admit_ratio)}</td><td>${escape(r.admitted_score_text)}${fieldTag(r,"admitted_score_text")}</td><td>${statusTag(r.status)}<small>${escape(r.scope)}</small></td></tr>`).join('');$('history-empty').hidden=history.length>0;
 const lines=tables.line.rows(data.cutoff_rows.filter(historical));
 $('line-body').innerHTML=lines.map(r=>`<tr><td>${escape(r.unit)}</td><td>${r.year}</td><td>${escape(r.label)}</td><td>${number(r.cutoff)}${fieldTag(r,'cutoff')}</td><td>${statusTag(r.status)}</td></tr>`).join('');
 const lists=tables.list.rows(data.admission_groups.filter(historical).filter(r=>$('eligibility').value==='all'||!r.exam_text||r.exam_text==='11408'));
 $('list-body').innerHTML=lists.map(r=>`<tr><td>${escape(r.unit)}<small>${r.year}</small></td><td>${escape(r.scope)}<small>${escape(r.exam_text||'考试科目待核')}</small></td><td>${number(r.n)}${fieldTag(r,'n')}</td><td>${number(r.minimum)} / ${number(r.maximum)}</td><td>${number(r.mean)} / ${number(r.median)}</td><td>${statusTag(r.status)}</td></tr>`).join('');
 const chosen=data.programmes.filter(p=>selected.has(p.id));$('selection-count').textContent=`比较清单：${chosen.length} 个专业`;$('compare-empty').hidden=chosen.length>0;$('open-compare').disabled=!chosen.length;
 $('open-preferences').disabled=!chosen.length;
 $('comparison-grid').innerHTML=chosen.map(p=>{
  const links=data.historical_alignment?.[p.id]||{matched:[],ambiguous:[]};
  const same=data.history.filter(r=>links.matched.includes(r.id)).sort((a,b)=>b.year-a.year);
  return `<article class="panel comparison-card"><h2>${escape(p.unit)}</h2><h3>${escape(p.major_name)}</h3><p>${escape(p.department)} · ${escape(p.major_code)}</p><dl><dt>招生年度</dt><dd>${p.year}</dd><dt>学位 / 方式</dt><dd>${escape(p.degree_type)} / ${escape(p.mode)}</dd><dt>初试科目</dt><dd>${escape(p.subjects.join(' / '))}</dd><dt>计划人数</dt><dd>${escape(p.plan_text)}<br>${statusTag(p.plan_status)}</dd><dt>普通统考</dt><dd>${number(p.ordinary_quota)}</dd><dt>校区</dt><dd>${escape(p.campus)}</dd></dl><h4>对应专业历史数据</h4>${same.length?same.map(r=>`<div class="historical-row"><strong>${r.year} · ${escape(r.major_name)}</strong><small>当年科目：${escape(r.exam_text||'待核')}</small><p>复试线 ${escape(r.cutoff_text)} ${fieldTag(r,'cutoff_text')} · 拟录取 ${escape(r.admit_text)} 人 ${fieldTag(r,'admit_text')}<br>复试 ${escape(r.retest_text)} 人 ${fieldTag(r,'retest_text')} · 复录比 ${ratio(r.interview_admit_ratio)}<br>录取分数 ${escape(r.admitted_score_text)} ${fieldTag(r,'admitted_score_text')}</p>${statusTag(r.status)}</div>`).join(''):'<p>暂无明确对应的历史专业数据。</p>'}${links.ambiguous.length?`<p class="prelim">另有 ${links.ambiguous.length} 条记录的院系或培养方式待确认。</p>`:''}<button class="text-button" data-select="${p.id}">移出比较</button></article>`;
 }).join('');
 const shown=view==='visuals'?(chosen.length?chosen:plans):['plans','recommend'].includes(view)?plans:view==='history'?[...history,...lines,...lists]:chosen;
 const visible=new Set(shown.map(r=>r.unit+'|'+r.year));
 if(['compare','preferences'].includes(view))for(const p of chosen)for(const r of data.history)if(data.historical_alignment?.[p.id]?.matched.includes(r.id))visible.add(r.unit+'|'+r.year);
 const notes=(data.official_notes||[]).filter(n=>visible.has(n.unit+'|'+n.year));
 $('official-note-block').hidden=!notes.length;$('official-notes').innerHTML=notes.map(n=>`<li>${escape(n.unit)} · ${n.year}：${escape(n.note)}</li>`).join('');
 Object.values(tables).forEach(t=>t.decorate());
 window.dispatchEvent(new Event('gradheat-selection'));
}
async function load(){try{const response=await fetch('/api/admissions');if(!response.ok)throw Error('数据暂时无法读取');data=await response.json();dataVersion=response.headers.get('X-Data-Version');comparisonArchiveReady=response.headers.get('X-Comparison-Archive')==='exact-bytes-v1';selected=new Set([...selected].filter(id=>data.programmes.some(p=>p.id===id)));saveSelection();$('updated').textContent=`资料更新 ${data.data_as_of}${data.last_checked?' · 最近检查 '+data.last_checked:''}`;$('coverage').innerHTML=`<span><strong>${data.counts.units}</strong>招生单位</span><span><strong>${data.counts.matched_programmes}</strong>11408 专业</span><span><strong>${data.counts.history_rows}</strong>历史记录</span>`;const unit=$('unit').value,group=$('group').value;$('unit').innerHTML='<option value="">全部单位</option>'+data.units.map(u=>`<option>${escape(u.name)}</option>`).join('');$('group').innerHTML='<option value="">全部类别</option>'+[...new Set(data.units.map(u=>u.group))].map(g=>`<option>${escape(g)}</option>`).join('');$('unit').value=unit;$('group').value=group;$('message').hidden=true;render();}catch(e){$('message').textContent=e.message;$('message').hidden=false;}}
document.querySelectorAll('[data-view]').forEach(n=>n.addEventListener('click',()=>setView(n.dataset.view)));
for(const id of ['search','unit','group','degree','mode','eligibility','history-year'])$(id).addEventListener(id==='search'?'input':'change',render);
document.body.addEventListener('click',e=>{const b=e.target.closest('[data-select]');if(!b)return;const id=b.dataset.select;if(selected.has(id))selected.delete(id);else{if(selected.size>=8){$('message').textContent='比较清单最多保留 8 个专业。';$('message').hidden=false;return;}selected.add(id);}saveSelection();render();});
$('clear-selection').addEventListener('click',()=>{selected.clear();saveSelection();render();});$('open-compare').addEventListener('click',()=>{setView('compare');window.scrollTo({top:0,behavior:'smooth'});});load();setInterval(load,60000);
$('open-preferences').addEventListener('click',()=>{setView('preferences');window.scrollTo({top:0,behavior:'smooth'});});

window.GradHeatUI={data:()=>data,version:()=>dataVersion,selected:()=>[...selected],filtered:rows,show:setView};

const narrowScreen=matchMedia('(max-width:550px)');if(narrowScreen.matches)document.querySelector('.global-filter-panel').open=false;narrowScreen.addEventListener('change',event=>{if(event.matches)document.querySelector('.global-filter-panel').open=false;});
