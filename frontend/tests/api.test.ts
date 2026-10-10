import { afterEach, describe, expect, it, vi } from 'vitest'
import { api, job } from '../src/api'
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks() })
describe('Java-only API boundary', () => {
  it('calls the v1 route and keeps the exact publication header', async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({ counts: {} }), { headers: { 'X-Data-Version': 'a'.repeat(64) } }))
    vi.stubGlobal('fetch', fetcher)
    expect((await api('/admissions')).version).toBe('a'.repeat(64)); expect(fetcher.mock.calls[0]?.[0]).toBe('/api/v1/admissions')
  })
  it('tells the user that stale input must be refreshed', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{}', { status: 409 })))
    await expect(api('/recommendations', { data_version: 'old' })).rejects.toThrow('填写内容会保留')
  })
  it('does not poll a synchronous bounded algorithm result', async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ranking: [], eligible_candidates: 0 }))); vi.stubGlobal('fetch', fetcher)
    expect(await job('/recommendations', {})).toEqual({ ranking: [], eligible_candidates: 0 }); expect(fetcher).toHaveBeenCalledTimes(1)
  })
  it('returns only the completed task result and records a bounded browser history', async () => {
    const storage = { getItem: vi.fn(() => '["earlier"]'), setItem: vi.fn() }; vi.stubGlobal('localStorage', storage)
    const fetcher = vi.fn().mockResolvedValueOnce(new Response('{"task_id":"t-1","status":"queued"}')).mockResolvedValueOnce(new Response('{"task_id":"t-1","status":"succeeded"}')).mockResolvedValueOnce(new Response('{"ok":true}')); vi.stubGlobal('fetch', fetcher)
    expect(await job('/tasks', {})).toEqual({ ok: true }); expect(fetcher.mock.calls[1]?.[0]).toBe('/api/v1/tasks/t-1'); expect(fetcher.mock.calls[2]?.[0]).toBe('/api/v1/tasks/t-1/result'); expect(storage.setItem).toHaveBeenCalledWith('gradheat-task-ids', '["earlier","t-1"]')
  })
})
