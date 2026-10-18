import { createSSRApp } from 'vue'
import { renderToString } from 'vue/server-renderer'
import { describe, expect, it } from 'vitest'
import ProgrammeReference from '../src/components/ProgrammeReference.vue'
import type { ProgrammeDecisionInputs } from '../src/types'

function inputs(values: Partial<ProgrammeDecisionInputs> = {}): ProgrammeDecisionInputs {
  return { threshold: null, threshold_year: null, ordinary_quota: null, capacity_proxy: null, capacity_year: null, retest_weights: {}, admitted_scores: {}, ...values }
}
const render = (value?: ProgrammeDecisionInputs) => renderToString(createSSRApp(ProgrammeReference, { inputs: value }))

describe('programme evidence is displayed with its own scope', () => {
  it('shows admission samples and retest weights even when the cutoff is missing', async () => {
    const html = await render(inputs({ admitted_scores: { year: 2025, population: 'observed-sample', mean: 362 }, retest_weights: { interview_weight: 0.4 }, retest_weights_year: 2026 }))
    expect(html).toContain('2025 年名单样本')
    expect(html).toContain('均分 362')
    expect(html).toContain('2026 年复试权重 40.0%')
    expect(html).not.toContain('复试线')
  })
  it('keeps the source basis and year of community thresholds visible', async () => {
    const html = await render(inputs({ threshold: 310, threshold_year: 2025, threshold_basis: 'community-school-table' }))
    expect(html).toContain('2025 年专题站整理复试线 310')
    expect(html).not.toContain('官网专业复试线')
  })
  it('keeps university minima distinct from professional thresholds', async () => {
    const minimum = await render(inputs({ threshold: 300, threshold_year: 2026, threshold_basis: 'official-school-minimum' }))
    expect(minimum).toContain('2026 年官网校级最低要求 300')
    expect(minimum).toContain('入围还需看院系名额和排名')
    const official = await render(inputs({ threshold: 330, threshold_year: 2025, threshold_basis: 'official-department' }))
    expect(official).toContain('2025 年官网专业复试线 330')
  })
  it('preserves zero weights and partial score statistics without inventing a mean or year', async () => {
    const html = await render(inputs({ admitted_scores: { minimum: 340 }, retest_weights: { interview_weight: 0 } }))
    expect(html).toContain('最低 340')
    expect(html).toContain('年度待核复试权重 0.0%')
    expect(html).not.toContain('均分')
    expect(html).not.toContain('undefined')
    expect(html).not.toContain('0 年')
  })
  it('keeps absent evidence empty and unknown source types explicit', async () => {
    expect(await render()).toContain('—')
    expect(await render(inputs())).toContain('—')
    expect(await render(inputs({ threshold: 320, threshold_year: null, threshold_basis: 'new-provider' }))).toContain('年度待核分数参考（来源类型待核） 320')
  })
})
