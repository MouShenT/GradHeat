'use strict';
(function(root){
 const text=x=>String(x??'').trim();
 const escape=x=>text(x).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const collator=new Intl.Collator('zh-CN',{numeric:true,sensitivity:'base'});
 function apply(rows,columns,state){
  const entries=rows.map((row,index)=>({row,index})).filter(({row})=>columns.every(c=>{
   const f=state.filters[c.key],v=text(c.value(row));
   return !f||(!f.search||v.toLowerCase().includes(f.search.toLowerCase()))&&(!f.values||f.values.includes(v));
  }));
  const c=columns.find(c=>c.key===state.sort?.key);
  if(c)entries.sort((a,b)=>{
   const av=c.sort?c.sort(a.row):c.value(a.row),bv=c.sort?c.sort(b.row):c.value(b.row);
   const an=av==null||text(av)===''||text(av)==='—',bn=bv==null||text(bv)===''||text(bv)==='—';
   if(an!==bn)return an?1:-1;
   let cmp=an?0:typeof av==='number'&&typeof bv==='number'?av-bv:collator.compare(text(av),text(bv));
   return cmp*(state.sort.direction==='desc'?-1:1)||a.index-b.index;
  });
  return entries.map(x=>x.row);
 }
 class ColumnTable{
  constructor(table,columns,changed){
   this.table=table;this.columns=columns;this.changed=changed;this.state={filters:{},sort:null};this.base=[];
   const icon='<svg class="column-filter-icon" viewBox="0 0 20 20" aria-hidden="true"><path d="M3 5h14l-5.5 6v4.5l-3 1V11z" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/></svg>';
   table.querySelector('thead').innerHTML='<tr>'+columns.map(c=>`<th scope="col" data-key="${c.key}"><button class="column-trigger" type="button" data-tool="menu" aria-haspopup="dialog" aria-expanded="false" aria-label="${escape(c.label)}：搜索、筛选和排序" title="搜索、筛选和排序"><span class="column-label"><span class="column-title">${escape(c.label)}</span><span class="column-state" hidden></span></span>${icon}</button></th>`).join('')+'</tr>';
   table.querySelector('thead').addEventListener('click',e=>{
    const b=e.target.closest('[data-tool]');if(!b)return;
    const key=b.closest('th').dataset.key;
    this.open(key,b);
   });
  }
  rows(base){this.base=base;return apply(base,this.columns,this.state);}
  reset(){this.state={filters:{},sort:null};this.changed();this.decorate();}
  decorate(){this.table.querySelectorAll('th').forEach(th=>{
   const key=th.dataset.key,f=this.state.filters[key];
   th.classList.toggle('column-filtered',!!f&&(!!f.search||f.values!==null));
   const active=this.state.sort?.key===key;th.setAttribute('aria-sort',active?(this.state.sort.direction==='asc'?'ascending':'descending'):'none');
   const hint=th.querySelector('.column-state'),parts=[];
   if(f?.search||f?.values!=null)parts.push(f?.values!=null?`已选${f.values.length}项`:'已筛选');
   if(active)parts.push(this.state.sort.direction==='asc'?'↑ 升序':'↓ 降序');
   hint.textContent=parts.join(' · ');hint.hidden=!parts.length;
   th.querySelector('.column-trigger').classList.toggle('active',!!parts.length);
  });}
  open(key,anchor){
   const c=this.columns.find(c=>c.key===key),saved=this.state.filters[key]||{search:'',values:null};
   const choices=[...new Set(this.base.map(r=>text(c.value(r))))].sort(collator.compare);
   document.querySelectorAll('.column-popover').forEach(p=>p.hidePopover());
   const d=document.createElement('div');d.className='column-popover';d.setAttribute('popover','auto');d.setAttribute('role','dialog');d.setAttribute('aria-label',c.label+'：搜索、筛选和排序');
   d.innerHTML=`<div class="column-panel-top"><div><p class="column-panel-kicker">调整这一列</p><h2>${escape(c.label)}</h2></div><button type="button" class="column-close" data-close aria-label="关闭">×</button></div><div class="column-order" aria-label="排序方式"><button type="button" data-order="none">默认顺序</button><button type="button" data-order="asc">↑ 升序</button><button type="button" data-order="desc">↓ 降序</button></div><label class="column-search">搜索这一列<input type="search" value="${escape(saved.search)}" placeholder="输入关键词查找"></label><div class="column-choice-heading"><span data-choice-count></span><div><button type="button" data-all>全选</button><button type="button" data-none>清空</button></div></div><div class="column-values">${choices.map((v,i)=>`<label><input type="checkbox" data-choice="${i}" ${saved.values===null||saved.values.includes(v)?'checked':''}><span>${escape(v||'未填写')}</span></label>`).join('')}</div><p class="column-no-values" hidden>没有匹配的选项</p><div class="column-panel-footer"><button type="button" class="text-button" data-reset>恢复本列</button><button type="button" class="primary" data-apply>应用条件</button></div>`;
   document.body.append(d);anchor.setAttribute('aria-expanded','true');
   d.addEventListener('toggle',event=>{if(event.newState==='closed'){anchor.setAttribute('aria-expanded','false');d.remove();}});
   d.querySelector('[data-close]').onclick=()=>{d.hidePopover();anchor.focus();};
   const boxes=[...d.querySelectorAll('[data-choice]')];
   let order=this.state.sort?.key===key?this.state.sort.direction:'none',orderChanged=false;
   const orders=[...d.querySelectorAll('[data-order]')];
   function paintOrder(){orders.forEach(b=>{b.classList.toggle('active',b.dataset.order===order);b.setAttribute('aria-pressed',String(b.dataset.order===order));});}
   orders.forEach(b=>b.onclick=()=>{order=b.dataset.order;orderChanged=true;paintOrder();});paintOrder();
   const search=d.querySelector('input[type=search]');
   const count=()=>d.querySelector('[data-choice-count]').textContent=`已选 ${boxes.filter(b=>b.checked).length} / ${choices.length} 项`;
   const narrow=()=>{boxes.forEach(b=>b.closest('label').hidden=!choices[Number(b.dataset.choice)].toLowerCase().includes(search.value.trim().toLowerCase()));d.querySelector('.column-no-values').hidden=boxes.some(b=>!b.closest('label').hidden);};
   search.oninput=narrow;boxes.forEach(b=>b.onchange=count);count();narrow();
   d.querySelector('[data-all]').onclick=()=>{boxes.filter(b=>!b.closest('label').hidden).forEach(b=>b.checked=true);count();};
   d.querySelector('[data-none]').onclick=()=>{boxes.filter(b=>!b.closest('label').hidden).forEach(b=>b.checked=false);count();};
   d.querySelector('[data-reset]').onclick=()=>{delete this.state.filters[key];if(this.state.sort?.key===key)this.state.sort=null;this.changed();this.decorate();d.hidePopover();anchor.focus();};
   d.querySelector('[data-apply]').onclick=()=>{
    const checked=boxes.filter(b=>b.checked).map(b=>choices[Number(b.dataset.choice)]);
    this.state.filters[key]={search:search.value.trim(),values:checked.length===choices.length?null:checked};
    if(orderChanged){if(order!=='none')this.state.sort={key,direction:order};else if(this.state.sort?.key===key)this.state.sort=null;}
    this.changed();this.decorate();d.hidePopover();anchor.focus();
   };
   d.showPopover();
   const rect=anchor.getBoundingClientRect(),width=d.offsetWidth,height=d.offsetHeight;
   d.style.left=Math.max(12,Math.min(rect.left,innerWidth-width-12))+'px';
   d.style.top=Math.max(12,Math.min(rect.bottom+8,innerHeight-height-12))+'px';
   search.focus();
  }
 }
 const exported={apply,ColumnTable};if(typeof module!=='undefined'&&module.exports)module.exports=exported;else root.GradTable=exported;
})(globalThis);
