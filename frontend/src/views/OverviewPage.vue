<script setup lang="ts">
import { computed, ref } from 'vue'
import { ArrowUpRight, Info } from 'lucide-vue-next'
import BarChart from '../components/BarChart.vue'
import ScopeFilters from '../components/ScopeFilters.vue'
import StatusChip from '../components/StatusChip.vue'
import { chosen, filtered, fmt, state, toggle } from '../state'
const metric = ref('cutoff')
const metricNames: Record<string, string> = { cutoff: '复试总分线', mean: '录取初试均分', minimum: '录取初试最低分', admit_count: '拟录取人数', interview_admit_ratio: '复录比' }
const programmes = computed(() => (chosen.value.length ? chosen.value : filtered.value).slice(0, 8))
const details = computed(() => programmes.value.map(p => state.dashboard?.programmes.find(d => d.id === p.id)).filter(p => p !== undefined))
const labels = computed(() => details.value.map(p => `${p.unit} · ${p.major_name}`))
const planSeries = computed(() => [{ name: '公布计划', values: details.value.map(p => p.reported_plan) }])
const historySeries = computed(() => [2026, 2025].map(year => ({ name: String(year), values: details.value.map(p => { const rows = p.history.filter(r => r.year === year && typeof r[metric.value] === 'number'); return rows.length === 1 ? rows[0]![metric.value] as number : null }) })))
</script>
<template><ScopeFilters /><div class="inline-note"><Info :size="15" />{{ chosen.length ? '优先展示比较清单' : '展示当前筛选中前 8 个专业' }}。不同计划口径与同年多范围的数字不合并。</div><div v-if="!state.dashboard" class="empty-state"><h3>图览数据暂未准备好</h3><p>招生列表仍可查阅，刷新后再试。</p></div><div v-else class="chart-grid"><article class="card chart-card"><div class="card-heading"><div><span class="eyebrow">ADMISSIONS PLAN</span><h2>2027 公布计划</h2></div><span class="mini-pill">人数 · 原口径</span></div><BarChart :labels="labels" :series="planSeries" unit=" 人" /><p class="chart-caption">含推免总计划与统考计划各保留原义，不作为竞争容量。</p></article><article class="card chart-card"><div class="card-heading"><div><span class="eyebrow">HISTORICAL DATA</span><h2>往年专业表现</h2></div><select v-model="metric" aria-label="图表历史指标"><option v-for="(name, key) in metricNames" :key="key" :value="key">{{ name }}</option></select></div><BarChart :labels="labels" :series="historySeries" /><p class="chart-caption">同年明确对应的单一范围才绘制；缺失及有歧义数据留空。</p></article></div><div class="programme-grid"><article v-for="p in programmes" :key="p.id" class="card programme-card"><div class="card-heading"><span class="mini-pill">{{ p.major_code }}</span><button class="icon-button" :aria-label="`比较${p.unit}${p.major_name}`" @click="toggle(p.id)"><ArrowUpRight :size="18" /></button></div><h3>{{ p.unit }}</h3><p>{{ p.major_name }} · {{ p.degree_type === '学术学位' ? '学硕' : '专硕' }}</p><span class="muted">{{ p.department }}</span><div class="programme-metrics"><div><small>公布计划</small><strong>{{ p.plan_text || '—' }}</strong></div><div><small>普通统考</small><strong>{{ fmt(p.ordinary_quota) }}</strong></div></div><StatusChip :text="p.plan_status" /><div class="background-note">本科背景友好程度 <b>待核</b></div></article></div></template>
