import type { Column, DataRow } from './types'
export interface ColumnFilter { search: string; values: string[] }
export interface Sort { key: string; direction: 'asc' | 'desc' }
export const cellText = (value: unknown) => value === null || value === undefined || value === '' ? '—' : Array.isArray(value) ? value.join(' / ') : String(value)
const collator = new Intl.Collator('zh-CN', { numeric: true, sensitivity: 'base' })
export function applyTable(rows: DataRow[], columns: Column[], filters: Record<string, ColumnFilter>, sort: Sort | null) {
  const output = rows.filter(row => columns.every(column => {
    const filter = filters[column.key]; if (!filter) return true
    const text = cellText(column.value(row))
    return (!filter.search || text.toLocaleLowerCase().includes(filter.search.trim().toLocaleLowerCase())) && (!filter.values.length || filter.values.includes(text))
  }))
  if (!sort) return output
  const column = columns.find(x => x.key === sort.key); if (!column) return output
  return [...output].sort((a, b) => {
    const x = column.value(a); const y = column.value(b)
    // Unknown values stay last in both directions.
    const emptyX = x === undefined || x === null || x === ''; const emptyY = y === undefined || y === null || y === ''
    if (emptyX || emptyY) return emptyX === emptyY ? 0 : emptyX ? 1 : -1
    const result = typeof x === 'number' && typeof y === 'number' ? x - y : collator.compare(cellText(x), cellText(y))
    return sort.direction === 'asc' ? result : -result
  })
}
