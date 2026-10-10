import { describe, expect, it } from 'vitest'
import { collectionGroups, parseCollectionInput } from '../src/collection'
describe('collection input', () => {
  it('retains literal queries and independent platform tasks', () => {
    const input = parseCollectionInput('\uFEFF' + JSON.stringify({ tasks: [{ platform: 'xhs', query: '任意搜索词' }, { platform: '小红书', query: '另一个词' }, { platform: 'github', repo: 'test/public' }] }))
    expect(input.tasks[0]!.query).toBe('任意搜索词'); expect(collectionGroups(input)).toEqual([['小红书', 2], ['GitHub', 1]])
  })
  it('rejects malformed, empty, unknown platform and private session inputs', () => {
    for (const text of ['{oops', '{}', '{"tasks":[]}', '{"tasks":[{"platform":"other","query":"a"}]}', '{"tasks":[{"platform":"xhs","query":"a","cookie":"private"}]}']) expect(() => parseCollectionInput(text)).toThrow()
  })
})
