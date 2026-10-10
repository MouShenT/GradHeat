export const platformNames: Record<string, string> = { official: '官网', github: 'GitHub', xhs: '小红书', zhihu: '知乎', dy: '抖音', bili: 'B站', '官网': '官网', '小红书': '小红书', '知乎': '知乎', '抖音': '抖音', 'b站': 'B站', bilibili: 'B站' }
export interface CollectionInput { schema_version?: number; tasks: Record<string, unknown>[]; [key: string]: unknown }
export function parseCollectionInput(text: string): CollectionInput {
  let value: unknown
  try { value = JSON.parse(text.replace(/^\uFEFF/, '')) } catch { throw new Error('JSON 格式不正确，请检查逗号、引号和括号。') }
  if (!value || typeof value !== 'object' || !('tasks' in value) || !Array.isArray(value.tasks) || !value.tasks.length) throw new Error('文件需要非空的 tasks 数组。')
  if (value.tasks.length > 100000) throw new Error('任务数量超过本次输入预算。')
  for (const row of value.tasks) {
    if (!row || typeof row !== 'object' || !platformNames[String(row.platform).toLowerCase()]) throw new Error('每项任务需要受支持的 platform。')
    if (!row.query && !row.urls?.length && !row.repo) throw new Error('每项需要 query，或官网 urls / GitHub repo。')
    if (Object.keys(row).some(k => /cookie|password|token|signature|headers/i.test(k))) throw new Error('检索文件不要填写密码、Cookie 或令牌。')
  }
  return value as CollectionInput
}
export function collectionGroups(input: CollectionInput) {
  const counts: Record<string, number> = {}
  for (const row of input.tasks) { const label = platformNames[String(row.platform).toLowerCase()]!; counts[label] = (counts[label] || 0) + 1 }
  return Object.entries(counts)
}
export interface CollectionProgress {
  batch_id: string; plan_sha: string; planned_jobs: number; processed_jobs: number; complete_jobs: number; incomplete_jobs: number
  unattempted_jobs: number; states: Record<string, number>; downloads: { incomplete: boolean; handoff: boolean }
}
export const collectionStateNames: Record<string, string> = {
  running: '采集中', committed: '材料已收集并入库', 'partial-committed': '已存部分材料', 'empty-sample': '没有取得内容',
  'needs-human': '登录或验证受限', 'not-requested-platform-blocked': '平台受限，未请求', 'needs-ingest': '材料待入库', failed: '请求或格式异常',
  'budget-paused': '预算到期，待续跑', 'missing-entry-url': '没有找到官网入口', 'invalid-content': '内容格式异常',
}
