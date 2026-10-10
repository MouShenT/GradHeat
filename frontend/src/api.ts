import type { Task } from './types'

export class ApiError extends Error { constructor(message: string, public status: number) { super(message) } }
export async function api<T>(path: string, body?: unknown): Promise<{ data: T; version: string | null }> {
  const response = await fetch(`/api/v1${path}`, body === undefined ? {} : {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  })
  const data = await response.json().catch(() => null)
  if (!response.ok) {
    const detail = typeof data?.detail === 'string' ? data.detail : typeof data?.message === 'string' ? data.message : null
    throw new ApiError(response.status === 409 ? '资料已更新，请刷新后重试；你的填写内容会保留。' : detail || '暂时无法完成操作，请稍后重试。', response.status)
  }
  return { data, version: response.headers.get('X-Data-Version') }
}

export async function job<T>(path: string, body: unknown, onState?: (state: string) => void): Promise<T> {
  const { data } = await api<T | Task>(path, body)
  if (!data || typeof data !== 'object' || !('task_id' in data)) return data as T
  const taskId = (data as Task).task_id
  try {
    const saved: unknown = JSON.parse(localStorage.getItem('gradheat-task-ids') || '[]')
    const ids = Array.isArray(saved) ? saved.filter(id => typeof id === 'string') : []
    localStorage.setItem('gradheat-task-ids', JSON.stringify([...new Set([...ids, taskId])].slice(-20)))
  } catch { /* Task execution does not depend on optional browser history. */ }
  for (let i = 0; i < 120; i++) {
    const { data: task } = await api<Task>(`/tasks/${encodeURIComponent(taskId)}`)
    onState?.(task.status)
    if (['succeeded', 'completed', 'SUCCEEDED', 'COMPLETED'].includes(task.status)) return (await api<T>(`/tasks/${encodeURIComponent(taskId)}/result`)).data
    if (['failed', 'cancelled', 'FAILED', 'CANCELLED', 'paused_human'].includes(task.status)) throw new ApiError(task.status === 'paused_human' ? '任务等待人工操作，可在更新记录查看。' : '本次任务未完成，填写内容已保留。', 502)
    await new Promise(resolve => setTimeout(resolve, 1000))
  }
  throw new ApiError('任务仍在处理中，可稍后在任务列表查看。', 202)
}
