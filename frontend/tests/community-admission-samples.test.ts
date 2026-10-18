import { createSSRApp } from 'vue'
import { renderToString } from 'vue/server-renderer'
import { describe, expect, it } from 'vitest'
import CommunityAdmissionSamples from '../src/components/CommunityAdmissionSamples.vue'
import type { CommunityAdmissionSample } from '../src/types'

const render = (samples: CommunityAdmissionSample[]) => renderToString(createSSRApp(CommunityAdmissionSamples, { samples }))

describe('community admission list samples retain their scope', () => {
  it('shows independent counts and minima with their programme and year, retaining reported zero', async () => {
    const html = await render([{ year: 2026, program_name: '示例学院 软件工程', exam_text: '11408', record_count: 12, admitted_sample_count: 12, unadmitted_retest_sample_count: 0, observed_retest_list_minimum: 320, admitted_total_minimum: 335, verification_state: 'extracted-needs-scope-review' }, { year: 2025, program_name: '示例学院 计算机技术', record_count: 8, admitted_sample_count: null, unadmitted_retest_sample_count: 2, observed_retest_list_minimum: null, admitted_total_minimum: 330 }])
    for (const text of ['2026', '2025', '示例学院 软件工程', '示例学院 计算机技术', '11408', '站点名单记录', '标为录取', '标为未录', '站点名单最低', '录取样本最低', '范围待交叉核对']) expect(html).toContain(text)
    expect(html).toContain('<td>0</td>')
    expect(html).toContain('<td>—</td>')
    expect(html).toContain('<td>335</td>')
    expect(html).toContain('数量 0 表示站点已报零条')
    for (const text of ['官网复试线', '普通净名额', '淘汰率']) expect(html).not.toContain(text)
  })
  it('does not invent identifiers or measurements and hides the table when samples are absent', async () => {
    const html = await render([{}])
    expect(html).toContain('年度待核')
    expect(html).toContain('专业范围待核')
    expect(html).toContain('科目待核')
    expect(html.match(/<td>—<\/td>/g)).toHaveLength(5)
    expect(html).not.toContain('undefined')
    expect(await render([])).not.toContain('<table>')
  })
})
