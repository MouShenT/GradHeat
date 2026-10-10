import { describe, expect, it } from 'vitest'
import { filterHistorical, pair, populationLabel, type HistoryFilter } from '../src/history'
import type { DataRow } from '../src/types'
const filter: HistoryFilter = { year: '2026', unit: '', group: '', search: '', scope: 'matched', units: [{ name: '示例 A', group: '研究所' }, { name: '示例 B', group: '985' }] }
const rows: DataRow[] = [
  { id: 'one', unit: '示例 A', year: 2026, scope: '081200 / 普通一志愿', exam_text: '11408', population: 'enrolled', n: 10 },
  { id: 'two', unit: '示例 A', year: 2026, scope: '081200 / 普通一志愿', exam_text: '11408', population: 'retest_pool', n: 20 },
  { id: 'three', unit: '示例 A', year: 2026, scope: '专项 / 调剂', exam_text: null, population: 'unknown', n: null },
  { id: 'four', unit: '示例 B', year: 2025, scope: '普通', exam_text: '11408', population: 'enrolled', n: 5 },
  { id: 'five', unit: '示例 B', year: 2026, scope: '专硕', exam_text: '22408', population: 'enrolled', n: 2 },
]
describe('historical scopes remain separate', () => {
  it('keeps exam-confirmed rows and separates interviewed and enrolled populations', () => { const result = filterHistorical(rows, filter, 'required'); expect(result.map(r => r.id)).toEqual(['one', 'two']); expect(result.map(populationLabel)).toEqual(['拟录取分组', '复试分组']); expect(result[0]?.n).toBe(10); expect(result[1]?.n).toBe(20) })
  it('retains unknown-exam list groups as unknown but excludes an explicit 22408 group', () => expect(filterHistorical(rows, filter, 'allow-unknown').map(r => r.id)).toEqual(['one', 'two', 'three']))
  it('shows school lines without treating them as subject evidence and filters the independent year', () => { const lines: DataRow[] = [{ id: 'line-1', unit: '示例 A', year: 2026, label: '院线 / 专项', cutoff: 0 }, { id: 'line-2', unit: '示例 A', year: 2025, label: '校线', cutoff: null }]; expect(filterHistorical(lines, filter, 'not-applicable').map(r => r.id)).toEqual(['line-1']); expect(filterHistorical(lines, { ...filter, year: 'all' }, 'not-applicable')).toHaveLength(2) })
  it('applies unit/category and scope searches without combining ordinary, special, first-choice, or transfer scopes', () => expect(filterHistorical(rows, { ...filter, group: '研究所', search: '专项' }, 'allow-unknown').map(r => r.id)).toEqual(['three']))
  it('does not use counts to derive a ratio or replace unknown numbers with zero', () => { expect(pair(null, 350)).toBe('— / 350'); expect(pair(0, null)).toBe('0 / —'); expect(populationLabel(rows[2]!)).toBe('人群待核'); expect(rows[0]?.interview_admit_ratio).toBeUndefined() })
})
