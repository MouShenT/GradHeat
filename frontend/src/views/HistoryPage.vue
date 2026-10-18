<script setup lang="ts">
import { computed, ref } from 'vue'
import { ChevronDown, Files, Info, ShieldCheck } from 'lucide-vue-next'
import AdmissionsTable from '../components/AdmissionsTable.vue'
import ScopeFilters from '../components/ScopeFilters.vue'
import StatusChip from '../components/StatusChip.vue'
import { filterHistorical, listCountLabel, pair, populationLabel } from '../history'
import { fmt, ratio, state } from '../state'
import type { Column, DataRow } from '../types'
import '../history.css'
const year = ref('2026')
const context = computed(() => ({ year: year.value, unit: state.unit, group: state.group, search: state.search, scope: state.scope, units: state.data?.units || [] }))
const rows = computed(() => filterHistorical(state.data?.history || [], context.value, 'required'))
const lines = computed(() => filterHistorical(state.data?.cutoff_rows || [], context.value, 'not-applicable'))
const lists = computed(() => filterHistorical(state.data?.admission_groups || [], context.value, 'allow-unknown'))
const columns: Column[] = [
  { key: 'unit', label: '院校 / 院系', width: 19, value: r => [r.unit, r.department].filter(Boolean).join(' / ') },
  { key: 'major', label: '年度 / 专业', width: 19, value: r => [r.year, r.major_name].filter(Boolean).join(' / ') },
  { key: 'cutoff', label: '复试线', width: 9, value: r => r.cutoff ?? r.cutoff_text },
  { key: 'retest', label: '复试人数', width: 10, value: r => r.retest_count ?? r.retest_text },
  { key: 'admit', label: '拟录取人数', width: 10, value: r => r.admit_count ?? r.admit_text },
  { key: 'ratio', label: '复录比', width: 9, value: r => r.interview_admit_ratio },
  { key: 'score', label: '录取分数', width: 13, value: r => r.admitted_score_text },
  { key: 'status', label: '状态', width: 11, value: r => r.status },
]
const lineColumns: Column[] = [
  { key: 'unit', label: '院校', width: 23, value: r => r.unit },
  { key: 'year', label: '年度', width: 11, value: r => r.year },
  { key: 'scope', label: '分数线适用范围', width: 37, value: r => r.label },
  { key: 'cutoff', label: '复试总分线', width: 13, value: r => r.cutoff },
  { key: 'status', label: '状态', width: 16, value: r => r.status },
]
const listColumns: Column[] = [
  { key: 'unit', label: '院校 / 年度', width: 18, value: r => `${r.unit} / ${r.year}` },
  { key: 'scope', label: '名单分组 / 人群', width: 26, value: r => `${r.scope || '范围待核'} / ${populationLabel(r)}` },
  { key: 'subjects', label: '当年科目', width: 11, value: r => r.exam_text },
  { key: 'n', label: '提取数量', width: 9, value: r => r.n },
  { key: 'range', label: '最低 / 最高', width: 12, value: r => pair(r.minimum, r.maximum) },
  { key: 'average', label: '均分 / 中位', width: 12, value: r => pair(r.mean, r.median) },
  { key: 'status', label: '状态', width: 12, value: r => r.status },
]
function fieldStatus(row: DataRow, field: string) {
  const states = row.verification as Record<string, { state: string; parts?: { state: string }[] }> | undefined
  const value = states?.[field]
  if (value?.state === 'three-source-agreement') return '三源一致'
  if (value?.state === 'two-source-agreement') return '两源一致'
  if (value?.state === 'conflict') return '数值冲突'
  if (value?.parts?.some(p => /source-agreement/.test(p.state))) return '部分两源一致'
  return ''
}
</script>
<template>
  <ScopeFilters historical />
  <div class="section-tools"><div class="year-tabs"><button v-for="y in ['2026', '2025', '2024', '2023', 'all']" :key="y" :class="{ selected: year === y }" @click="year = y">{{ y === 'all' ? '全部年度' : y }}</button></div><span class="muted">按当年专业与考试口径展示</span></div>
  <div class="inline-note"><Info :size="15" /><span>复录比＝同年度、同范围复试人数 ÷ 拟录取人数；分母保留原表的普通、专项及一志愿 / 调剂口径，未核明人群保持待核。</span></div>
  <AdmissionsTable :rows="rows" :columns="columns" title="专业录取统计">
    <template #cell-unit="{ row }"><strong class="cell-primary">{{ row.unit }}</strong><span class="cell-secondary">{{ row.department }}</span></template>
    <template #cell-major="{ row }"><span class="year-pill">{{ row.year }}</span><strong class="cell-primary">{{ row.major_name }}</strong><span class="cell-secondary">{{ row.exam_text }}</span></template>
    <template #cell-cutoff="{ row }"><strong class="score-number">{{ row.cutoff_text || '—' }}</strong><StatusChip v-if="fieldStatus(row, 'cutoff_text')" :text="fieldStatus(row, 'cutoff_text')" /></template>
    <template #cell-ratio="{ row }">{{ ratio(row.interview_admit_ratio) }}</template>
    <template #cell-status="{ row }"><StatusChip :text="row.status" /><span class="cell-secondary">{{ row.scope }}</span></template>
  </AdmissionsTable>
  <details class="history-detail" data-history-lines>
    <summary><span class="history-detail-icon"><ShieldCheck :size="18" /></span><span><strong>校线、院线与其他分数线</strong><small>保留独立范围，不替代对应专业的分数线</small></span><span class="history-detail-count">{{ lines.length }} 条</span><ChevronDown :size="15" /></summary>
    <div class="history-detail-content"><div class="inline-note"><Info :size="14" />这里包含院校其他口径的分数线。科目未明确时不据此认定 11408；专项、院系和学位类别按原范围分行，不合并。</div>
      <AdmissionsTable :rows="lines" :columns="lineColumns" title="独立范围分数线">
        <template #cell-unit="{ row }"><strong class="cell-primary">{{ row.unit }}</strong></template>
        <template #cell-year="{ row }"><span class="year-pill">{{ row.year ?? '年度待核' }}</span></template>
        <template #cell-scope="{ row }"><span class="cell-primary">{{ row.label || '适用范围待核' }}</span></template>
        <template #cell-cutoff="{ row }"><strong class="score-number">{{ fmt(row.cutoff) }}</strong><StatusChip v-if="fieldStatus(row, 'cutoff')" :text="fieldStatus(row, 'cutoff')" /></template>
        <template #cell-status="{ row }"><StatusChip :text="row.status" /></template>
      </AdmissionsTable>
    </div>
  </details>
  <details class="history-detail" data-history-groups>
    <summary><span class="history-detail-icon"><Files :size="18" /></span><span><strong>名单分组的分数统计</strong><small>复试分组与拟录取分组分别展示</small></span><span class="history-detail-count">{{ lists.length }} 条</span><ChevronDown :size="15" /></summary>
    <div class="history-detail-content"><div class="inline-note"><Info :size="14" />数量按行标明人数或观测行；脱敏标识无法确认唯一考生时，人数保持待核。名单分组完整性待核，不是整个专业的录取人数；复试名单不作为录取分布，不用分组人数计算复录比。</div>
      <AdmissionsTable :rows="lists" :columns="listColumns" title="名单分组统计">
        <template #cell-unit="{ row }"><strong class="cell-primary">{{ row.unit }}</strong><span class="year-pill">{{ row.year ?? '年度待核' }}</span></template>
        <template #cell-scope="{ row }"><span class="cell-primary">{{ row.scope || '范围待核' }}</span><span class="population-label" :class="{ interview: row.population === 'retest_pool' }">{{ populationLabel(row) }}</span></template>
        <template #cell-subjects="{ row }"><span class="subject-codes">{{ row.exam_text || '科目待核' }}</span></template>
        <template #cell-n="{ row }"><span>{{ fmt(row.n) }}</span><span class="cell-secondary">{{ listCountLabel(row) }}</span><span v-if="typeof row.masked_identifier_rows === 'number' && row.masked_identifier_rows > 0" class="cell-secondary">脱敏标识 {{ row.masked_identifier_rows }} 行</span><StatusChip v-if="fieldStatus(row, 'n')" :text="fieldStatus(row, 'n')" /></template>
        <template #cell-status="{ row }"><StatusChip :text="row.status" /><span class="cell-secondary">{{ row.population === 'retest_pool' ? '非最终录取统计' : '分组完整性待核' }}</span></template>
      </AdmissionsTable>
    </div>
  </details>
</template>
