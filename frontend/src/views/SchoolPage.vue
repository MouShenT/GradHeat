<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { api } from '../api'
import { state } from '../state'
import type { Programme, DataRow } from '../types'
interface Dossier { available: boolean; unit: string; tier: string; programmes: Programme[]; history: DataRow[]; notes: string[]; heat: {heat_value: number | null}; counts: Record<string,number> }
const names=ref<string[]>(state.data?.units.map(u=>u.name)||[]), unit=ref(state.unit || '北京邮电大学'), school=ref<Dossier|null>(null), error=ref('')
let revision=0
async function refresh(){const current=++revision;error.value='';try{const {data}=await api<Dossier>(`/school-dossier?unit=${encodeURIComponent(unit.value)}`);if(current===revision)school.value=data}catch(e){if(current===revision)error.value=e instanceof Error?e.message:'院校资料暂不可用'}}
watch(unit,()=>{school.value=null;refresh()})
onMounted(()=>{api<{unit:string}[]>('/school-indices').then(r=>{names.value=r.data.map(u=>u.unit)}).catch(()=>{});refresh()})
</script>
<template><section class="card heat-heading"><div><span class="eyebrow">SCHOOL DATABASE</span><h2>院校档案</h2><p>每所院校的招生、历史和经验信息归在一起。</p></div><select v-model="unit" aria-label="院校档案招生单位"><option v-for="name in names" :key="name">{{name}}</option></select></section><p v-if="error" class="error-banner">{{error}}</p><section v-if="school?.available" class="card game-result"><h2>{{school.unit}} <span class="mini-pill">{{school.tier}}</span></h2><p>热度值 <strong>{{school.heat.heat_value ?? '—'}}</strong></p><div class="index-table"><table><thead><tr><th>院系 / 专业</th><th>考试科目</th><th>招生计划</th></tr></thead><tbody><tr v-for="p in school.programmes" :key="p.id"><td>{{p.department}}<small>{{p.major_name}} · {{p.major_code}}</small></td><td>{{p.subjects.join(' / ')}}</td><td>{{p.plan_text||'—'}}</td></tr></tbody></table></div><p v-if="!school.programmes.length" class="muted">已建立院校档案，专业资料正在整理。</p><details v-if="school.notes.length" class="form-section"><summary>背景与复试经验摘要</summary><p v-for="note in school.notes" :key="note">{{note}}</p><small class="muted">经验摘要供参考；具体报考条件以对应年度招生规则为准。</small></details><p class="muted">已整理 {{school.history.length}} 条历年记录。<RouterLink to="/history">查看历年录取</RouterLink></p></section><p v-else-if="school" class="muted">院校档案正在建立。</p></template>
