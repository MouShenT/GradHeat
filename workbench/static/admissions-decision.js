'use strict';
(()=>{
 const dimensions={research:'研究兴趣',location:'城市与生活',cost:'费用可承受度',career:'就业与发展',training:'培养方式适配'};
 const draftKey='gradheat-preference-draft-v1';
 let draft={weights:{},candidates:{}}, renderedIds='', contextVersion=null, busy=false, revision=0;
 try{draft={...draft,...JSON.parse(localStorage.getItem(draftKey)||'{}')};}catch{}
 draft.weights||={};draft.candidates||={};
 const form=$('preference-form'), status=$('preference-status');
 $('comparison-title').value=draft.title||'我的2027择校比较';
 $('profile-notes').value=draft.notes||'';
 for(const [name,values] of [['accepted-degree',draft.degrees],['accepted-mode',draft.modes]])if(Array.isArray(values))document.querySelectorAll(`[name="${name}"]`).forEach(n=>n.checked=values.includes(n.value));
 $('preference-weights').innerHTML=Object.entries(dimensions).map(([d,label])=>`<label>${label}<input type="number" min="0" max="10" step="0.1" required data-weight="${d}" value="${escape(draft.weights[d]??1)}"></label>`).join('');
 function retain(){
  draft.title=$('comparison-title').value;draft.notes=$('profile-notes').value;
  draft.degrees=[...document.querySelectorAll('[name="accepted-degree"]:checked')].map(n=>n.value);
  draft.modes=[...document.querySelectorAll('[name="accepted-mode"]:checked')].map(n=>n.value);
  document.querySelectorAll('[data-weight]').forEach(n=>draft.weights[n.dataset.weight]=n.value);
  for(const box of document.querySelectorAll('[data-preference-id]')){
   const p=draft.candidates[box.dataset.preferenceId]||={ratings:{}};
   p.eligibility=box.querySelector('[data-eligibility]').value;p.notes=box.querySelector('[data-candidate-notes]').value;
   for(const [d] of Object.entries(dimensions))p.ratings[d]={low:box.querySelector(`[data-low="${d}"]`).value,high:box.querySelector(`[data-high="${d}"]`).value,basis:box.querySelector(`[data-basis="${d}"]`).value};
  }
  try{localStorage.setItem(draftKey,JSON.stringify(draft));}catch{status.textContent='浏览器暂时无法保留填写内容，请及时保存。';}
 }
 function renderInputs(){
  if(!data)return;
  const chosen=data.programmes.filter(p=>selected.has(p.id)), ids=chosen.map(p=>p.id).join('|');
  if(contextVersion!==dataVersion){revision++;if(contextVersion&& !$('preference-results').hidden){$('preference-results').hidden=true;status.textContent='招生资料已更新，填写内容已保留，请重新计算。';}contextVersion=dataVersion;}
  if(ids!==renderedIds){
   revision++;
   if(renderedIds)retain();renderedIds=ids;$('preference-results').hidden=true;
   $('preference-candidates').innerHTML=chosen.map(p=>{
    const v=draft.candidates[p.id]||{ratings:{}};
    return `<article class="panel" data-preference-id="${p.id}"><h2>${escape(p.unit)} · ${escape(p.major_name)}</h2><p>${escape(p.department)} · ${escape(p.major_code)} · ${escape(p.degree_type)} / ${escape(p.mode)}</p><label>个人报考资格<select data-eligibility><option value="unknown" ${!v.eligibility||v.eligibility==='unknown'?'selected':''}>尚未确认</option><option value="self_reported_pass" ${v.eligibility==='self_reported_pass'?'selected':''}>我已核对，符合条件</option><option value="self_reported_fail" ${v.eligibility==='self_reported_fail'?'selected':''}>不符合条件</option></select></label><div class="preference-ratings">${Object.entries(dimensions).map(([d,label])=>{
     const r=v.ratings?.[d]||{};
     return `<fieldset><legend>${label}</legend><div class="rating-bounds"><label>下限<input type="number" min="0" max="10" step="0.1" data-low="${d}" value="${escape(r.low??'')}" placeholder="留空"></label><label>上限<input type="number" min="0" max="10" step="0.1" data-high="${d}" value="${escape(r.high??'')}" placeholder="留空"></label></div><label>判断依据<input data-basis="${d}" maxlength="600" value="${escape(r.basis||'')}" placeholder="例如：方向契合程度或预算"></label></fieldset>`;
    }).join('')}</div><label>专业备注<textarea rows="2" data-candidate-notes maxlength="2000">${escape(v.notes||'')}</textarea></label></article>`;
   }).join('');
  }
  $('preference-empty').hidden=chosen.length>0;
  $('calculate-preferences').disabled=busy||!chosen.length;
  $('save-preferences').disabled=busy||!chosen.length||!comparisonArchiveReady;
 }
 function requestInput(){
  retain();if(!form.reportValidity())throw Error('请检查输入：权重和评分范围为0—10。');
  if(!draft.modes.length||!draft.degrees.length)throw Error('请至少选择一种学习方式和学位类型。');
  const weights=Object.fromEntries(Object.keys(dimensions).map(d=>[d,Number(draft.weights[d])]));
  if(!Object.values(weights).some(n=>n>0))throw Error('至少一项权重需要大于0。');
  const candidates=[...selected].map(id=>{
   const c=draft.candidates[id]||{}, ratings={};
   for(const [d,label] of Object.entries(dimensions)){
    const r=c.ratings?.[d];if(!r||r.low===''&&r.high==='')continue;
    if(r.low===''||r.high==='')throw Error(`${label}请同时填写上下限，或都留空。`);
    const low=Number(r.low),high=Number(r.high);if(low>high)throw Error(`${label}的下限不能高于上限。`);
    ratings[d]={low,high,basis:r.basis||''};
   }
   return {programme_id:id,personal_eligibility:c.eligibility||'unknown',ratings,notes:c.notes||''};
  });
  return {title:draft.title.trim(),data_version:dataVersion,profile:{target_year:2027,modes:draft.modes,degrees:draft.degrees,notes:draft.notes},weights,candidates};
 }
 async function api(path,body){
  const response=await fetch(path,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{});
  const value=await response.json();if(!response.ok)throw Error(typeof value.detail==='string'?value.detail:'填写内容不符合要求，请检查后重试。');return value;
 }
 function renderResults(r,saved=false){
  const labels=Object.fromEntries(r.cards.map(c=>[c.id,c.programme.unit+' · '+c.programme.major_name]));
  const names=ids=>ids.map(i=>labels[i]).join('；')||'目前不能确定';
  $('preference-results').hidden=false;
  $('preference-results').innerHTML=`<h2>${saved?'已保存的比较':'本次偏好比较'}</h2><p>${escape(r.input.title)} · 资料截至 ${escape(r.data_as_of)}</p><p>${escape(r.interpretation)}</p><div class="score-grid">${r.cards.map(c=>{
   const s=r.baseline.intervals[c.id];
   return `<article class="score-card"><h3>${escape(labels[c.id])}</h3><p>${escape(c.programme.department)} · ${escape(c.programme.degree_type)}</p><div class="score">${s?`${number(s.low)}—${number(s.high)}`:'已排除'}${s?'<small> / 10</small>':''}</div><p>${escape([...c.blocked_reasons,...c.qualification_pending].join('；')||'用户自报报考条件满足')}</p>${s?`<p>已填写偏好权重：${Math.round(s.specified_weight*100)}%${s.unknown_dimensions.length?'；未填写：'+s.unknown_dimensions.map(d=>dimensions[d]).join('、'):''}</p><span class="tag ${r.baseline.certain_best.includes(c.id)?'agreed':''}">${r.baseline.certain_best.includes(c.id)?'本次偏好范围内最优':r.baseline.potential_best.includes(c.id)?'本次偏好范围内可能最优':'本次偏好范围内非最优'}</span>`:''}</article>`;
  }).join('')}</div><h3 class="sensitivity-title">改变看重点，结果是否稳定？</h3><p>在本轮权重变化中均为确定最优：${escape(names(r.stable_certain_best))}</p><details><summary>查看各项权重变化</summary><ul>${r.sensitivity.map(s=>`<li>${dimensions[s.dimension]} × ${s.factor}：可能最优 ${escape(names(s.potential_best))}；确定最优 ${escape(names(s.certain_best))}</li>`).join('')}</ul></details><details><summary>本次计算的说明</summary><ul>${r.assumptions.map(s=>`<li>${escape(s)}</li>`).join('')}</ul></details>`;
 }
 async function calculate(save){
  if(save&&!comparisonArchiveReady){status.textContent='当前页面尚未连接结果存储，请打开最新工作台。';return;}
  let input;try{input=requestInput();}catch(e){status.textContent=e.message;return;}
  const submittedRevision=revision;
  busy=true;renderInputs();status.textContent=save?'正在保存到信息库…':'正在比较…';
  try{
   if(save){const stored=await api('/api/admissions/comparisons',input);const row=await api('/api/admissions/comparisons/'+stored.comparison_id);renderResults(row.result,true);status.textContent=revision!==submittedRevision?'已保存提交时的内容；当前填写或资料已变化，请重新计算。':stored.reused?'相同内容已保存，已打开记录。':'已保存，后续资料更新不会改变这份结果。';await readSaved();}
   else{const result=await api('/api/admissions/compare',input);if(revision!==submittedRevision){status.textContent='填写内容或资料已变化，请重新计算。';return;}renderResults(result);status.textContent='已计算；你可以继续调整权重或评分，也可以保存这次结果。';}
  }catch(e){status.textContent=e.message;}finally{busy=false;renderInputs();}
 }
 async function readSaved(){
  const area=$('comparison-sessions');area.textContent='正在读取…';
  try{const rows=(await api('/api/admissions/comparisons')).items;area.innerHTML=rows.length?rows.map(r=>`<article class="saved-comparison"><div><strong>${escape(r.title)}</strong><small>${escape(new Date(r.created_at).toLocaleString('zh-CN'))} · ${r.candidate_count} 个专业</small></div><div><button class="text-button" type="button" data-saved-comparison="${r.comparison_id}">查看</button><a href="/api/admissions/comparisons/${r.comparison_id}/export?format=md">导出报告</a><a href="/api/admissions/comparisons/${r.comparison_id}/export?format=json">导出数据</a></div></article>`).join(''):'<p>还没有保存记录，填写后点击“保存本次比较”。</p>';}
  catch(e){area.textContent=e.message;}
 }
 form.addEventListener('input',()=>{revision++;retain();$('preference-results').hidden=true;status.textContent='填写内容已保留，修改后请重新计算。';});
 form.addEventListener('submit',e=>{e.preventDefault();calculate(false);});
 $('save-preferences').addEventListener('click',()=>calculate(true));
 $('refresh-comparisons').addEventListener('click',readSaved);
 $('comparison-sessions').addEventListener('click',async e=>{const b=e.target.closest('[data-saved-comparison]');if(!b)return;try{renderResults((await api('/api/admissions/comparisons/'+b.dataset.savedComparison)).result,true);status.textContent='正在查看保存时的资料与评分；当前填写内容保留。';$('preference-results').scrollIntoView({behavior:'smooth'});}catch(err){status.textContent=err.message;}});
 window.addEventListener('gradheat-selection',renderInputs);renderInputs();
})();
