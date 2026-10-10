<script setup lang="ts">
import { Plus, Check, Info } from 'lucide-vue-next'
import AdmissionsTable from '../components/AdmissionsTable.vue'
import ScopeFilters from '../components/ScopeFilters.vue'
import StatusChip from '../components/StatusChip.vue'
import { filtered, fmt, state, toggle } from '../state'
import type { Column } from '../types'
const columns: Column[] = [
  { key: 'unit', label: '院校 / 院系', width: 22, value: p => [p.unit, p.department, p.campus].filter(Boolean).join(' / ') },
  { key: 'major', label: '专业 / 方向', width: 23, value: p => [p.major_name, p.major_code, ...(p.directions as string[] || [])].filter(Boolean).join(' / ') },
  { key: 'degree', label: '学位 / 方式', width: 13, value: p => `${p.degree_type} / ${p.mode}` },
  { key: 'subjects', label: '考试科目', width: 15, value: p => (p.subjects as string[]).join(' / ') },
  { key: 'plan', label: '招生计划', width: 18, value: p => p.plan_text },
  { key: 'compare', label: '比较', width: 9, value: p => state.selected.includes(p.id) ? '已加入' : '未加入' },
]
</script>
<template><ScopeFilters /><div class="inline-note"><Info :size="15" /><span>计划保留公布口径。含推免或专项的人数，不直接作为普通统考名额。</span></div><AdmissionsTable :rows="filtered" :columns="columns" title="2027 招生专业"><template #cell-unit="{ row }"><strong class="cell-primary">{{ row.unit }}</strong><span class="cell-secondary">{{ row.department || '院系待补' }}</span><span v-if="row.campus" class="cell-secondary">{{ row.campus }}</span></template><template #cell-major="{ row }"><strong class="cell-primary">{{ row.major_name }}</strong><span class="code-label">{{ row.major_code }}</span><span v-if="(row.directions as string[]).length" class="cell-secondary">{{ (row.directions as string[]).join(' / ') }}</span></template><template #cell-degree="{ row }"><span class="degree-label">{{ row.degree_type === '学术学位' ? '学硕' : row.degree_type === '专业学位' ? '专硕' : row.degree_type }}</span><span class="cell-secondary">{{ row.mode }}</span></template><template #cell-subjects="{ row }"><span class="subject-codes">{{ (row.subjects as string[]).join(' / ') || '—' }}</span><span class="cell-secondary">{{ row.eligible_11408 === true ? '11408' : row.eligible_11408 === false ? '其他科目' : '科目待核' }}</span></template><template #cell-plan="{ row }"><strong class="cell-primary plan-value">{{ row.plan_text || '待公布 / 待补' }}</strong><span class="cell-secondary">普通统考 {{ fmt(row.ordinary_quota) }}</span><StatusChip :text="row.plan_status" /></template><template #cell-compare="{ row }"><button class="select-programme" :class="{ selected: state.selected.includes(row.id) }" :aria-label="`${state.selected.includes(row.id) ? '移除' : '加入比较'}${row.unit}${row.major_name}`" @click="toggle(row.id)"><Check v-if="state.selected.includes(row.id)" :size="15" /><Plus v-else :size="15" /><span>{{ state.selected.includes(row.id) ? '已加入' : '比较' }}</span></button></template></AdmissionsTable></template>
