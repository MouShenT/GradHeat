import type { DataRow } from './types'
export interface HistoryFilter { year: string; unit: string; group: string; search: string; scope: string; units: { name: string; group: string }[] }
export function filterHistorical(rows: DataRow[], filter: HistoryFilter, subjects: 'required' | 'allow-unknown' | 'not-applicable') {
  return rows.filter(row => {
    const text = [row.unit, row.department, row.major_name, row.scope, row.label, row.year].filter(x => x !== undefined && x !== null).join(' ').toLocaleLowerCase()
    const common = (!filter.unit || row.unit === filter.unit) && (!filter.group || filter.units.find(unit => unit.name === row.unit)?.group === filter.group) && (filter.year === 'all' || row.year === Number(filter.year)) && (!filter.search || text.includes(filter.search.trim().toLocaleLowerCase()))
    if (!common) return false
    if (filter.scope === 'all' || subjects === 'not-applicable') return true
    return row.exam_text === '11408' || subjects === 'allow-unknown' && (row.exam_text === undefined || row.exam_text === null || row.exam_text === '')
  })
}
export function populationLabel(row: DataRow) {
  if (row.population === 'enrolled') return '拟录取分组'
  if (row.population === 'retest_pool') return '复试分组'
  return '人群待核'
}
export function pair(low: unknown, high: unknown) {
  const known = (value: unknown) => typeof value === 'number' && Number.isFinite(value) ? String(Number(value.toFixed(2))) : '—'
  return `${known(low)} / ${known(high)}`
}
