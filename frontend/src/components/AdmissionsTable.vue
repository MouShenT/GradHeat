<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ArrowDown, ArrowUp, Check, ChevronsUpDown, Filter, RotateCcw, Search, X } from 'lucide-vue-next'
import { applyTable, cellText, type ColumnFilter, type Sort } from '../table'
import type { Column, DataRow } from '../types'
const props = defineProps<{ rows: DataRow[]; columns: Column[]; title?: string }>()
const filters = reactive<Record<string, ColumnFilter>>({})
const sort = ref<Sort | null>(null)
const active = ref<string | null>(null)
const position = ref({ top: '0px', left: '0px' })
const search = ref('')
const output = computed(() => applyTable(props.rows, props.columns, filters, sort.value))
const activeColumn = computed(() => props.columns.find(c => c.key === active.value))
const values = computed(() => activeColumn.value ? [...new Set(props.rows.map(row => cellText(activeColumn.value!.value(row))))].sort((a, b) => a.localeCompare(b, 'zh-CN', { numeric: true })).filter(v => v.toLocaleLowerCase().includes(search.value.toLocaleLowerCase())) : [])
const activeCount = computed(() => Object.values(filters).filter(f => f.search || f.values.length).length + (sort.value ? 1 : 0))
function open(column: Column, event: MouseEvent) {
  if (active.value === column.key) { active.value = null; return }
  const rect = (event.currentTarget as HTMLElement).getBoundingClientRect()
  position.value = { top: `${Math.min(rect.bottom + 9, innerHeight - 390)}px`, left: `${Math.max(12, Math.min(rect.left, innerWidth - 292))}px` }
  active.value = column.key; filters[column.key] ||= { search: '', values: [] }; search.value = ''
}
function cycleSort(key: string) { sort.value = sort.value?.key === key ? sort.value.direction === 'asc' ? { key, direction: 'desc' } : null : { key, direction: 'asc' } }
function choose(value: string) { if (!active.value) return; const values = filters[active.value]!.values; const index = values.indexOf(value); index < 0 ? values.push(value) : values.splice(index, 1) }
function reset() { for (const key of Object.keys(filters)) delete filters[key]; sort.value = null; active.value = null }
function closeOutside(event: MouseEvent) { if (!(event.target as HTMLElement).closest('[data-column-popup], [data-column-trigger]')) active.value = null }
function keydown(event: KeyboardEvent) { if (event.key === 'Escape') active.value = null }
onMounted(() => { document.addEventListener('click', closeOutside); document.addEventListener('keydown', keydown) })
onBeforeUnmount(() => { document.removeEventListener('click', closeOutside); document.removeEventListener('keydown', keydown) })
</script>
<template>
  <section class="data-panel">
    <div class="table-toolbar"><div><span class="section-label">{{ title || '数据列表' }}</span><span class="muted">{{ output.length }} 条记录</span><span v-if="activeCount" class="filter-count">{{ activeCount }} 项条件</span></div><button class="text-button" @click="reset"><RotateCcw :size="14" />重置</button></div>
    <div class="table-scroll" tabindex="0" :aria-label="title || '数据表格'">
      <table class="admissions-table"><colgroup><col v-for="column in columns" :key="column.key" :style="{ width: column.width + '%' }"></colgroup><thead><tr><th v-for="column in columns" :key="column.key" :aria-sort="sort?.key === column.key ? sort.direction === 'asc' ? 'ascending' : 'descending' : 'none'">
        <div class="column-heading"><button class="column-title" :title="`${column.label}：点击切换排序`" @click="cycleSort(column.key)">{{ column.label }}<ArrowUp v-if="sort?.key === column.key && sort.direction === 'asc'" :size="13" /><ArrowDown v-else-if="sort?.key === column.key" :size="13" /></button><button data-column-trigger class="column-filter" :class="{ filtered: !!filters[column.key]?.search || !!filters[column.key]?.values.length }" :aria-label="`筛选${column.label}`" :aria-expanded="active === column.key" @click.stop="open(column, $event)"><Filter :size="13" /></button></div>
      </th></tr></thead><tbody><tr v-for="row in output" :key="row.id"><td v-for="column in columns" :key="column.key"><slot :name="`cell-${column.key}`" :row="row">{{ cellText(column.value(row)) }}</slot></td></tr></tbody></table>
      <div v-if="!output.length" class="empty-state"><Search :size="28" /><h3>没有符合条件的记录</h3><p>调整搜索内容，或清除某一列的筛选。</p><button class="button subtle" @click="reset">清除本表条件</button></div>
    </div>
  </section>
  <Teleport to="body"><div v-if="active && activeColumn" data-column-popup class="column-popup" :style="position" role="dialog" :aria-label="`${activeColumn.label}筛选与排序`"><div class="popup-heading"><strong>{{ activeColumn.label }}</strong><button class="icon-button" aria-label="关闭列筛选" @click="active = null"><X :size="16" /></button></div><div class="sort-options"><button :class="{ selected: sort?.key === active && sort.direction === 'asc' }" @click="sort = { key: active!, direction: 'asc' }"><ArrowUp :size="15" />升序</button><button :class="{ selected: sort?.key === active && sort.direction === 'desc' }" @click="sort = { key: active!, direction: 'desc' }"><ArrowDown :size="15" />降序</button><button aria-label="清除排序" title="清除排序" @click="sort = null"><ChevronsUpDown :size="15" /></button></div><label class="popup-search"><Search :size="15" /><input v-model="filters[active]!.search" placeholder="搜索这一列" :aria-label="`搜索${activeColumn.label}`"></label><div class="popup-options"><button v-for="value in values.slice(0, 200)" :key="value" @click="choose(value)"><span class="checkbox" :class="{ checked: filters[active]!.values.includes(value) }"><Check v-if="filters[active]!.values.includes(value)" :size="12" /></span><span>{{ value }}</span></button><p v-if="!values.length" class="muted">当前无可选值。</p></div><div class="popup-foot"><button class="text-button" @click="filters[active!] = { search: '', values: [] }">清除筛选</button><button class="button small" @click="active = null">完成</button></div></div></Teleport>
</template>
