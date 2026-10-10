import { describe, expect, it } from 'vitest'
import { applyTable } from '../src/table'
import type { Column, DataRow } from '../src/types'
const columns: Column[] = [{ key: 'name', label: '名称', width: 50, value: r => r.unit }, { key: 'plan', label: '计划', width: 50, value: r => r.plan }]
const rows: DataRow[] = [
  { id: 'a', unit: '示例院校 A', year: 2027, plan: 30 }, { id: 'b', unit: '示例院校 B', year: 2027, plan: null },
  { id: 'c', unit: '示例院校 C', year: 2027, plan: 5 }, { id: 'd', unit: '其他单位', year: 2027, plan: 0 },
]
describe('public column filtering', () => {
  it('combines selected values and searches across columns', () => expect(applyTable(rows, columns, { name: { search: '示例', values: ['示例院校 A', '示例院校 C'] }, plan: { search: '5', values: [] } }, null).map(r => r.id)).toEqual(['c']))
  it('sorts known numbers, including zero, and leaves unknown last ascending', () => expect(applyTable(rows, columns, {}, { key: 'plan', direction: 'asc' }).map(r => r.id)).toEqual(['d', 'c', 'a', 'b']))
  it('keeps unknown last descending too without mutating the source', () => { expect(applyTable(rows, columns, {}, { key: 'plan', direction: 'desc' }).map(r => r.id)).toEqual(['a', 'c', 'd', 'b']); expect(rows[0]?.id).toBe('a') })
  it('matches unknown text only when explicitly selected', () => expect(applyTable(rows, columns, { plan: { search: '', values: ['—'] } }, null).map(r => r.id)).toEqual(['b']))
})
