import { computed, reactive } from 'vue'
import { api } from './api'
import type { Admissions, Dashboard, Programme } from './types'

function savedSelection(): string[] {
  try { const value = JSON.parse(localStorage.getItem('gradheat-admissions-selection') || '[]'); return Array.isArray(value) ? value.filter(x => typeof x === 'string').slice(0, 8) : [] } catch { return [] }
}
export const state = reactive({
  data: null as Admissions | null, dashboard: null as Dashboard | null, version: '', loading: false,
  error: '', selected: savedSelection(), search: '', unit: '', group: '', degree: '', mode: '', scope: 'matched',
})
export const chosen = computed(() => state.data?.programmes.filter(p => state.selected.includes(p.id)) || [])
export const groups = computed(() => [...new Set(state.data?.units.map(u => u.group) || [])])
export const filtered = computed(() => (state.data?.programmes || []).filter(p => {
  const group = p.group || state.data?.units.find(u => u.name === p.unit)?.group
  const text = [p.unit, p.department, p.major_name, p.major_code, ...(p.directions || [])].join(' ').toLocaleLowerCase()
  return (!state.search || text.includes(state.search.trim().toLocaleLowerCase())) && (!state.unit || p.unit === state.unit)
    && (!state.group || group === state.group) && (!state.degree || p.degree_type === state.degree)
    && (!state.mode || p.mode === state.mode) && (state.scope === 'all' || p.eligible_11408 === true)
}))
export function toggle(id: string) {
  if (state.selected.includes(id)) state.selected = state.selected.filter(x => x !== id)
  else if (state.selected.length < 8) state.selected.push(id)
  else { state.error = '最多比较 8 个专业，请先移除一个。'; return }
  localStorage.setItem('gradheat-admissions-selection', JSON.stringify(state.selected))
}
export function clearSelection() { state.selected = []; localStorage.setItem('gradheat-admissions-selection', '[]') }
export async function load() {
  if (state.loading) return
  state.loading = true; state.error = ''
  try {
    const { data, version } = await api<Admissions>('/admissions')
    state.data = data; state.version = version || ''; state.selected = state.selected.filter(id => data.programmes.some(p => p.id === id))
    localStorage.setItem('gradheat-admissions-selection', JSON.stringify(state.selected))
    try { const { data: overview } = await api<Dashboard>('/dashboard'); state.dashboard = overview.data_version === state.version ? overview : null } catch { state.dashboard = null }
  } catch (error) { state.error = error instanceof Error ? error.message : '数据暂时无法读取。' } finally { state.loading = false }
}
export const fmt = (value: unknown) => value === undefined || value === null || value === '' ? '—' : typeof value === 'number' ? String(Number(value.toFixed(2))) : String(value)
export const ratio = (value: unknown) => typeof value === 'number' ? `${Number(value.toFixed(2))} : 1` : '—'
export const programmeLabel = (p: Programme) => `${p.unit} · ${p.major_name}`
