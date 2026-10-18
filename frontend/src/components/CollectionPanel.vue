<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ArrowRight, Check, Download, FileJson, FolderUp, Globe2, LoaderCircle, Play, RefreshCw } from 'lucide-vue-next'
import { api } from '../api'
import { state } from '../state'
import { collectionGroups, collectionProgressHeading, collectionStateNames, collectionTaskActive, parseCollectionInput, type CollectionInput, type CollectionProgress } from '../collection'
import type { Task } from '../types'
const browser = ref(false), opening = ref(false), confirmed = ref(false), busy = ref(false), error = ref(''), notice = ref('')
const input = ref<CollectionInput | null>(null), filename = ref(''), progress = ref<CollectionProgress | null>(null), task = ref<Task | null>(null)
const batchId = ref(''), taskId = ref(''); let timer: ReturnType<typeof setInterval>
const lastReadAt = ref(''), progressError = ref(''), refreshing = ref(false)
let prepared: { batch_id: string; plan_sha: string; platforms: string[] } | null = null
let requestId = ''
const groups = computed(() => input.value ? collectionGroups(input.value) : [])
const percentage = computed(() => progress.value ? Math.round(100 * progress.value.processed_jobs / Math.max(1, progress.value.planned_jobs)) : 0)
const active = computed(() => collectionTaskActive(task.value?.status))
const heading = computed(() => collectionProgressHeading(task.value?.status, !!progressError.value))
const canStart = computed(() => browser.value && confirmed.value && input.value && state.version && !busy.value && !active.value && !progressError.value && (!taskId.value || !!lastReadAt.value))
async function refresh() {
  if (refreshing.value) return
  refreshing.value = true
  try {
    await Promise.all([
      (async () => {
        try {
          const status = (await api<{ browser_available: boolean; opening: boolean }>('/collection/browser')).data
          browser.value = status.browser_available; opening.value = status.opening
        } catch { browser.value = false; confirmed.value = false; opening.value = false }
      })(),
      (async () => {
        if (!batchId.value) return
        const readingBatch = batchId.value, readingTask = taskId.value
        try {
          const [nextProgress, nextTask] = await Promise.all([
            api<CollectionProgress>(`/collection/${readingBatch}`),
            readingTask ? api<Task>(`/tasks/${readingTask}`) : Promise.resolve(null),
          ])
          if (readingBatch !== batchId.value || readingTask !== taskId.value) return
          progress.value = nextProgress.data; task.value = nextTask?.data ?? null
          lastReadAt.value = new Date().toLocaleTimeString('zh-CN', { hour12: false }); progressError.value = ''
        } catch { if (readingBatch === batchId.value && readingTask === taskId.value) progressError.value = '暂时无法读取最新进度；已保留上次回执，采集是否仍在运行待核对。' }
      })(),
    ])
  } finally { refreshing.value = false }
}
async function openBrowser() {
  error.value = ''; opening.value = true
  try { await api('/collection/browser', {}); notice.value = '专用浏览器正在打开。请在四个平台完成登录，再回到这里确认。'; await refresh() }
  catch (e) { error.value = e instanceof Error ? e.message : '浏览器未能打开。'; opening.value = false }
}
async function selectFile(event: Event) {
  error.value = ''; input.value = null; filename.value = ''; prepared = null; requestId = ''
  const file = (event.target as HTMLInputElement).files?.[0]; if (!file) return
  if (file.size > 4800000) { error.value = 'JSON 文件请控制在 4.8 MB 以内。'; return }
  try { input.value = parseCollectionInput(await file.text()); filename.value = file.name }
  catch (e) { error.value = e instanceof Error ? e.message : '文件无法读取。' }
}
async function start() {
  if (!canStart.value || !input.value) return
  busy.value = true; error.value = ''; notice.value = ''
  try {
    const plan = prepared || (await api<{ batch_id: string; plan_sha: string; platforms: string[] }>('/collection/prepare', input.value)).data
    prepared = plan; requestId ||= crypto.randomUUID()
    const created = (await api<Task>('/tasks', { request_id: requestId, type: 'collect.autonomous.win-primary', input_version: state.version,
      deadline_minutes: 1440, scope: { batch_id: plan.batch_id, plan_sha: plan.plan_sha, retry_platforms: plan.platforms.filter(p => ['xhs', 'zhihu', 'dy', 'bili'].includes(p)) } })).data
    batchId.value = plan.batch_id; taskId.value = created.task_id; task.value = created
    progress.value = null; lastReadAt.value = ''; progressError.value = ''
    try {
      localStorage.setItem('gradheat-collection', JSON.stringify({ batchId: batchId.value, taskId: taskId.value }))
      const ids = JSON.parse(localStorage.getItem('gradheat-task-ids') || '[]')
      localStorage.setItem('gradheat-task-ids', JSON.stringify([...new Set([...(Array.isArray(ids) ? ids : []), taskId.value])].slice(-20)))
    } catch { /* Optional browser history. */ }
    notice.value = '任务已加入队列。保留专用浏览器，关闭页面后后台会继续执行。'; await refresh()
  } catch (e) { error.value = e instanceof Error ? e.message : '任务暂时无法开始。' }
  finally { busy.value = false }
}
async function resumeBatch() {
  if (!progress.value || active.value || busy.value || progressError.value || !lastReadAt.value) return
  busy.value = true; error.value = ''
  try {
    task.value = (await api<Task>('/tasks', { request_id: crypto.randomUUID(), type: 'collect.autonomous.win-primary', input_version: state.version,
      deadline_minutes: 1440, scope: { batch_id: batchId.value, plan_sha: progress.value.plan_sha, retry_platforms: [] } })).data
    taskId.value = task.value.task_id
    lastReadAt.value = ''; progressError.value = ''
    localStorage.setItem('gradheat-collection', JSON.stringify({ batchId: batchId.value, taskId: taskId.value }))
    notice.value = '继续本批未执行的任务，成功材料保留。'; await refresh()
  } catch (e) { error.value = e instanceof Error ? e.message : '暂时无法续跑。' }
  finally { busy.value = false }
}
onMounted(() => {
  try { const saved = JSON.parse(localStorage.getItem('gradheat-collection') || '{}'); if (/^batch-\d{8}-[a-f0-9]{12}$/.test(saved.batchId)) batchId.value = saved.batchId; if (/^[a-f0-9-]{36}$/.test(saved.taskId)) taskId.value = saved.taskId } catch { /* Optional history. */ }
  refresh(); timer = setInterval(() => { if (!document.hidden) refresh() }, 5000)
})
onBeforeUnmount(() => clearInterval(timer))
</script>
<template>
  <section class="collection-panel card">
    <div class="collection-title"><div><span class="eyebrow">COLLECT YOUR NEXT CLUE</span><h2>把资料采集交给程序</h2><p>登录一次，放入检索清单。官网、四个平台和 GitHub，按顺序收集。</p></div><span class="collection-badge"><Globe2 :size="17" />六个渠道</span></div>
    <div class="collection-steps">
      <div class="collection-step"><span class="step-index">01</span><h3>打开采集浏览器</h3><p>调出小红书、抖音、知乎和 B站。登录保存在这台电脑。</p><button class="button" :disabled="opening" @click="openBrowser"><LoaderCircle v-if="opening" :size="16" class="spinning" /><Globe2 v-else :size="16" />{{ opening ? '正在打开' : '爬取 · 打开浏览器' }}</button><label class="login-confirm"><input v-model="confirmed" type="checkbox" :disabled="!browser" /><span>我已登录，确认平台可以搜索</span></label><small v-if="browser" class="browser-ready"><Check :size="13" />浏览器已连接</small></div>
      <div class="collection-step"><span class="step-index">02</span><h3>放入 JSON 清单</h3><p>每项填平台和搜索词。官网可指定网址，GitHub可指定仓库。</p><label class="collection-file"><FolderUp :size="23" /><strong>{{ filename || '选择 JSON 文件' }}</strong><span>{{ input ? `${input.tasks.length} 个检索任务` : '支持 .json · 最大 4.8 MB' }}</span><input type="file" accept=".json,application/json" aria-label="选择采集 JSON 文件" @change="selectFile" /></label><div class="collection-tags"><span v-for="[name, count] in groups" :key="name">{{ name }} {{ count }}</span></div></div>
      <div class="collection-step"><span class="step-index">03</span><h3>开始自动采集</h3><p>异常内容记入未完成清单，继续后面的任务。原材料收好后，再统一分析。</p><button class="button" :disabled="!canStart" @click="start"><LoaderCircle v-if="busy" :size="16" class="spinning" /><Play v-else :size="16" />{{ busy ? '正在创建任务' : active ? '任务已提交' : '开始爬取' }}<ArrowRight :size="15" /></button><small>无需逐条操作。请保留浏览器和本机服务。</small></div>
    </div>
    <p v-if="notice" class="collection-notice" role="status">{{ notice }}</p><p v-if="error" class="collection-error" role="alert">{{ error }}</p>
    <p v-if="progressError" class="collection-error" role="status">{{ progressError }}</p>
    <div v-if="progress" class="collection-progress"><div class="collection-progress-heading"><strong>{{ heading }}</strong><button class="text-button" :disabled="refreshing" @click="refresh"><RefreshCw :size="14" :class="{ spinning: refreshing }" />刷新</button></div><p class="muted collection-read-time">最近读取 {{ lastReadAt || '—' }}<span v-if="active"> · 任务状态以最后回执为准</span></p><div class="collection-progress-track"><div :style="{ width: percentage + '%' }" /></div><div class="collection-metrics"><span>已处理任务 <b>{{ progress.processed_jobs }} / {{ progress.planned_jobs }}</b></span><span>完整入库任务 <b>{{ progress.complete_jobs }}</b></span><span v-if="progress.states['partial-committed']">部分入库任务 <b>{{ progress.states['partial-committed'] }}</b></span><span>有缺口任务 <b>{{ progress.incomplete_jobs }}</b></span><span>未执行任务 <b>{{ progress.unattempted_jobs }}</b></span></div><div class="collection-tags"><span v-for="(count, key) in progress.states" :key="key">{{ collectionStateNames[key] || key }} {{ count }}</span></div><div class="collection-downloads"><button v-if="!active && (progress.unattempted_jobs || progress.states['budget-paused'])" class="collection-download" :disabled="busy || !!progressError || refreshing" @click="resumeBatch"><Play :size="15" />继续未执行任务</button><a v-if="progress.downloads.incomplete" class="collection-download" :href="`/api/v1/collection/${batchId}/download/incomplete`" download><FileJson :size="17" />下载未完成 JSON</a><a v-if="progress.downloads.handoff" class="collection-download" :href="`/api/v1/collection/${batchId}/download/handoff`" download><Download :size="17" />下载原材料包</a><small>计数单位为检索任务。部分入库任务仍含缺口；已入库材料需继续核验，未计作院校完整覆盖。</small></div></div>
  </section>
</template>
<style scoped>
.collection-panel{padding:28px;margin-bottom:22px}.collection-title{display:flex;justify-content:space-between;gap:20px;align-items:flex-start;margin-bottom:28px}.collection-title .eyebrow{font-size:10px;letter-spacing:1.4px;color:var(--accent)}.collection-title h2{font-size:23px;margin-top:10px}.collection-title p{margin:0;color:var(--muted)}.collection-badge{display:flex;align-items:center;gap:7px;background:#edf4e8;color:#487153;border-radius:100px;padding:9px 12px;font-size:11px;white-space:nowrap}.collection-steps{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:28px}.collection-step{padding-left:20px;border-left:1px solid var(--border)}.collection-step:first-child{padding-left:0;border:0}.step-index{font-size:11px;letter-spacing:2px;color:#6f967b;display:block;margin-bottom:14px}.collection-step h3{font-size:16px}.collection-step p{font-size:12px;color:var(--muted);min-height:48px}.collection-step .button{font-size:12px;padding:12px 15px}.login-confirm{display:flex;gap:8px;align-items:center;margin:17px 0 8px;font-size:11px;cursor:pointer}.login-confirm input{accent-color:var(--accent)}.browser-ready{display:flex;align-items:center;gap:5px;color:var(--accent);font-size:11px}.collection-file{border:1px dashed #abc0a7;background:#f8faf5;border-radius:10px;position:relative;padding:17px;display:flex;flex-direction:column;align-items:center;gap:8px;cursor:pointer;overflow:hidden;color:#51745b;min-height:117px}.collection-file strong{font-size:12px;max-width:100%;overflow-wrap:anywhere}.collection-file span{font-size:10px;color:var(--muted)}.collection-file input{position:absolute;inset:0;width:100%;height:100%;opacity:0;cursor:pointer}.collection-step>small{display:block;font-size:10px;margin-top:16px;line-height:1.7}.collection-tags{display:flex;flex-wrap:wrap;gap:6px;margin-top:12px}.collection-tags span{background:#f1f5ed;border:1px solid #e4ecdf;color:#62765b;border-radius:6px;padding:5px 8px;font-size:10px}.collection-notice,.collection-error{font-size:12px;padding:12px 15px;margin:22px 0 0;border-radius:8px;background:#eef5e8;color:#496c4a}.collection-error{background:#fbefe6;color:#915a36}.collection-progress{margin-top:28px;border-top:1px solid var(--border);padding-top:21px}.collection-progress-heading{display:flex;justify-content:space-between;align-items:center}.collection-read-time{font-size:11px;margin:10px 0 0}.collection-progress-track{height:7px;background:#eef3e9;border-radius:8px;margin:15px 0}.collection-progress-track>div{height:100%;background:#65987a;border-radius:8px;transition:width .3s}.collection-metrics{display:flex;flex-wrap:wrap;gap:24px;font-size:11px;color:var(--muted)}.collection-metrics b{color:var(--text);margin-left:6px;font-size:14px}.collection-downloads{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin-top:18px}.collection-download{display:flex;align-items:center;gap:7px;font-size:11px;border:1px solid #cedfc7;color:#4e7457;padding:9px 12px;border-radius:7px}.collection-downloads small{font-size:10px;line-height:1.7}@media(max-width:950px){.collection-steps{gap:16px}.collection-panel{padding:22px}.collection-step{padding-left:14px}}@media(max-width:700px){.collection-steps{grid-template-columns:1fr;gap:24px}.collection-step,.collection-step:first-child{border:0;padding:0}.collection-step p{min-height:0}.collection-title{gap:10px}.collection-title h2{font-size:20px}.collection-title p{font-size:12px}.collection-badge{font-size:10px;padding:8px}.collection-metrics{gap:14px}}
</style>
