<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from 'vue'
import { api } from '../api'
import { state } from '../state'
import type { Programme, DataRow } from '../types'
interface Fact {
  year: number; department: string; major_code: string; major_name: string; mode: string; route: string; population: string
  campus?: string; cutoff_kind?: string; excerpt?: string; url?: string
  values: { cutoff?: number; ordinary_quota?: number; admitted_mean?: number; admitted_minimum?: number; admitted_count?: number; initial_weight?: number; interview_weight?: number; machine_test_weight?: number }
}
interface CommunitySource { title: string; url: string; score_url: string; pages: {title: string; url: string}[]; scores: {year: number; degree_type: string; major_name: string; exam_text: string; cutoff: number; plan: string; special: boolean; score_limits: Record<string,number>}[] }
interface Dossier { available: boolean; unit: string; tier: string; programmes: Programme[]; history: DataRow[]; decision_facts?: Fact[]; community_sources?: CommunitySource[]; notes: string[]; heat: { heat_value: number | null }; counts: Record<string,number> }
const names=ref<string[]>(state.data?.units.map(u=>u.name)||[]), unit=ref(state.unit || '北京邮电大学')
const school=ref<Dossier|null>(null), error=ref('')
let revision=0, timer: ReturnType<typeof setInterval> | undefined
const percent=(value?: number) => value == null ? '—' : `${(value*100).toFixed(1)}%`
async function refresh() {
  const current=++revision
  try {
    const {data}=await api<Dossier>(`/school-dossier?unit=${encodeURIComponent(unit.value)}`)
    if(current===revision) { school.value=data; error.value='' }
  } catch(e) { if(current===revision)error.value=e instanceof Error?e.message:'院校资料暂不可用' }
}
watch(unit,()=>{school.value=null;refresh()})
watch(()=>state.version,()=>refresh())
onMounted(()=>{
  api<{unit:string}[]>('/school-indices').then(r=>{names.value=r.data.map(u=>u.unit)}).catch(()=>{})
  refresh()
  timer=setInterval(()=>{if(document.visibilityState==='visible')refresh()},60000)
})
onUnmounted(()=>{revision++;if(timer)clearInterval(timer)})
</script>
<template>
  <section class="card heat-heading">
    <div><span class="eyebrow">SCHOOL DATABASE</span><h2>院校档案</h2><p>招生名额、历史分数和复试信息随各院校档案更新。</p></div>
    <select v-model="unit" aria-label="院校档案招生单位"><option v-for="name in names" :key="name">{{name}}</option></select>
  </section>
  <p v-if="error" class="error-banner">{{error}}</p>
  <section v-if="school?.available" class="card game-result">
    <h2>{{school.unit}} <span class="mini-pill">{{school.tier}}</span></h2>
    <p>热度值 <strong>{{school.heat.heat_value ?? '—'}}</strong></p>
    <div class="index-table"><table>
      <thead><tr><th>院系 / 专业</th><th>考试科目</th><th>本年度普通统考名额</th><th>历史分数参考</th></tr></thead>
      <tbody><tr v-for="p in school.programmes" :key="p.id">
        <td>{{p.department}}<small>{{p.major_name}} · {{p.major_code}} · {{p.mode}}</small><small v-if="p.scope">{{p.scope}}</small></td>
        <td>{{p.subjects.join(' / ')}}</td>
        <td><strong>{{p.decision_inputs?.ordinary_quota ?? '—'}}</strong><small>{{p.plan_text||'名额待补齐'}}</small><small v-if="p.decision_inputs?.ordinary_quota == null && p.decision_inputs?.capacity_proxy != null">容量参考：{{p.decision_inputs.capacity_year}} 年 {{p.decision_inputs.capacity_proxy}} 人</small></td>
        <td v-if="p.decision_inputs?.threshold != null">{{p.decision_inputs.threshold_year}} 年{{p.decision_inputs.threshold_basis==='official-school-minimum' ? '校级最低要求' : '复试线'}} {{p.decision_inputs.threshold}}<small v-if="p.decision_inputs.threshold_basis==='official-school-minimum'">入围还需看院系名额和排名</small><small v-if="p.decision_inputs.admitted_scores?.mean != null">{{p.decision_inputs.admitted_scores.year}} 年{{p.decision_inputs.admitted_scores.population==='observed-sample' ? '名单样本' : '录取'}}均分 {{p.decision_inputs.admitted_scores.mean}}</small><small v-if="p.decision_inputs.retest_weights?.interview_weight != null">{{p.decision_inputs.retest_weights_year}} 年复试权重 {{percent(p.decision_inputs.retest_weights.interview_weight)}}</small></td>
        <td v-else>—</td>
      </tr></tbody>
    </table></div>
    <p v-if="!school.programmes.length" class="muted">已建立院校档案，专业资料正在整理。</p>
    <details v-if="school.decision_facts?.length" class="form-section" open>
      <summary>已整理的官方基础数据（{{school.decision_facts.length}} 条）</summary>
      <p class="muted">按原文年度、专业和学习方式分别记录；历史名额供参考。名单样本数量不作为招生名额。</p>
      <div class="index-table"><table>
        <thead><tr><th>年度 / 专业</th><th>普通统考名额</th><th>分数要求</th><th>成绩与复试</th></tr></thead>
        <tbody><tr v-for="(f,i) in school.decision_facts" :key="i">
          <td>{{f.year}} · {{f.major_name}}<small>{{f.department}} · {{f.major_code}} · {{f.mode}}</small><small v-if="f.campus">{{f.campus}}</small><small v-if="f.route !== 'first-choice'">{{f.route === 'transfer' ? '调剂' : '推免'}}</small><small v-if="f.population==='observed-sample'">已取得名单样本</small><details v-if="f.excerpt || f.url"><summary>范围与来源</summary><p>{{f.excerpt}}</p><a v-if="f.url" :href="f.url" target="_blank" rel="noopener noreferrer">查看原文 ↗</a></details></td>
          <td>{{f.values.ordinary_quota ?? '—'}}</td><td>{{f.values.cutoff ?? '—'}}<small v-if="f.cutoff_kind==='school-minimum'">校级最低要求</small></td>
          <td><small v-if="f.values.admitted_mean != null">均分 {{f.values.admitted_mean}} · 最低 {{f.values.admitted_minimum ?? '—'}}</small><small v-if="f.values.interview_weight != null">复试 {{percent(f.values.interview_weight)}} · 初试 {{percent(f.values.initial_weight)}}</small><small v-if="f.values.machine_test_weight != null">机试占复试 {{percent(f.values.machine_test_weight)}}</small></td>
        </tr></tbody>
      </table></div>
    </details>
    <section v-if="school.community_sources?.length" class="form-section">
      <h3>择校专题站</h3>
      <div v-for="source in school.community_sources" :key="source.url">
        <p><a :href="source.url" target="_blank" rel="noopener noreferrer">{{source.title}}</a> <span class="mini-pill">社区整理</span></p>
        <p class="muted"><a v-for="page in source.pages" :key="page.url" :href="page.url" target="_blank" rel="noopener noreferrer">{{page.title}} ↗ </a></p>
        <details v-if="source.scores.length"><summary>分数资料（{{source.scores.length}} 条）</summary>
          <div class="index-table"><table><thead><tr><th>年度 / 专业</th><th>计划</th><th>科目组合</th><th>复试线</th><th>单科线</th></tr></thead><tbody>
            <tr v-for="(row,i) in source.scores" :key="i"><td>{{row.year}} · {{row.degree_type}}<small>{{row.major_name==='-' ? '该学位类别通用线' : row.major_name}}</small></td><td>{{row.plan}}</td><td>{{row.exam_text}}</td><td>{{row.cutoff}}</td><td>{{['politics','english','mathematics','computer'].map(k=>row.score_limits[k] ?? '—').join(' / ')}}</td></tr>
          </tbody></table></div>
          <p class="muted">普通计划与专项分别保留。<a :href="source.score_url" target="_blank" rel="noopener noreferrer">查看来源</a></p>
        </details>
      </div>
    </section>
    <details v-if="school.notes.length" class="form-section"><summary>背景与复试经验摘要</summary><p v-for="note in school.notes" :key="note">{{note}}</p><small class="muted">经验摘要供参考；具体报考条件以对应年度招生规则为准。</small></details>
    <p class="muted">已整理 {{school.history.length}} 条历年记录。<RouterLink to="/history">查看历年录取</RouterLink></p>
  </section>
  <p v-else-if="school" class="muted">院校档案正在建立。</p>
</template>
