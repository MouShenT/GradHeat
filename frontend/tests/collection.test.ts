import { describe, expect, it } from 'vitest'
import { collectionGroups, collectionProgressHeading, collectionStateNames, collectionTaskActive, parseCollectionInput } from '../src/collection'
describe('collection input', () => {
  it('retains literal queries and independent platform tasks', () => {
    const input = parseCollectionInput('\uFEFF' + JSON.stringify({ tasks: [{ platform: 'xhs', query: '任意搜索词' }, { platform: '小红书', query: '另一个词' }, { platform: 'github', repo: 'test/public' }] }))
    expect(input.tasks[0]!.query).toBe('任意搜索词'); expect(collectionGroups(input)).toEqual([['小红书', 2], ['GitHub', 1]])
  })
  it('rejects malformed, empty, unknown platform and private session inputs', () => {
    for (const text of ['{oops', '{}', '{"tasks":[]}', '{"tasks":[{"platform":"other","query":"a"}]}', '{"tasks":[{"platform":"xhs","query":"a","cookie":"private"}]}']) expect(() => parseCollectionInput(text)).toThrow()
  })
})

describe('collection receipts remain distinct from live collection and coverage', () => {
  it('keeps queued jobs waiting and treats running only as a recorded task state', () => {
    expect(collectionProgressHeading('QUEUED')).toBe('等待采集器接收')
    expect(collectionProgressHeading('running')).toBe('任务回执：处理中')
    expect(collectionTaskActive('STARTED')).toBe(true)
    expect(collectionTaskActive('pending')).toBe(true)
    expect(collectionTaskActive('succeeded')).toBe(false)
  })
  it('does not claim live progress or completion when refreshing the receipt failed', () => {
    for (const status of ['running', 'queued', 'succeeded']) {
      expect(collectionProgressHeading(status, true)).toBe('进度暂未更新，显示上次回执')
    }
    expect(collectionTaskActive('running')).toBe(true)
    expect(collectionProgressHeading('failed')).toBe('本轮任务未完成')
    expect(collectionProgressHeading()).toBe('采集进度待核对')
  })
  it('labels stored task counts separately from retained and partly stored material', () => {
    expect(collectionStateNames.committed).toBe('完整入库任务')
    expect(collectionStateNames['partial-committed']).toBe('部分入库任务')
    expect(collectionStateNames.retained).toBe('已取得，待入库')
    expect(collectionStateNames.running).toBe('回执处理中')
  })
})
