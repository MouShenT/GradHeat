<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { CheckCircle2, Clock3, RefreshCw } from 'lucide-vue-next'
import { api } from '../api'
import { state } from '../state'
import type { Task } from '../types'
import CollectionPanel from '../components/CollectionPanel.vue'
const tasks = ref<Task[]>([]); const error = ref(''); let timer: ReturnType<typeof setInterval>
async function refresh() {
  try {
    const ids: unknown = JSON.parse(localStorage.getItem('gradheat-task-ids') || '[]')
    if (!Array.isArray(ids)) return
    tasks.value = await Promise.all(ids.filter(id => typeof id === 'string').slice(-20).map(async id => (await api<Task>(`/tasks/${encodeURIComponent(id)}`)).data)); error.value = ''
  } catch { error.value = '部分任务进度暂时无法读取，可稍后刷新。' }
}
function label(status: string) { return ({ pending: '等待处理', queued: '等待处理', running: '进行中', started: '进行中', succeeded: '已完成', completed: '已完成', failed: '未完成', cancelled: '已取消', paused_human: '待人工操作' } as Record<string, string>)[status?.toLowerCase()] || '待核对' }
onMounted(() => { refresh(); timer = setInterval(() => { if (!document.hidden) refresh() }, 10000) }); onBeforeUnmount(() => clearInterval(timer))
</script>
<template><CollectionPanel /><section class="card update-card"><span class="accent-icon"><CheckCircle2 :size="25" /></span><div><h2>当前招生资料</h2><p>资料截至 {{ state.data?.data_as_of }}<span v-if="state.data?.last_checked"> · 最近检查 {{ state.data.last_checked }}</span></p><small class="muted">资料页面定期读取最新已提交版本，比较记录保留保存时的版本。</small></div></section><section class="card"><div class="card-heading"><h2>本浏览器提交的任务</h2><button class="text-button" @click="refresh"><RefreshCw :size="14" />刷新进度</button></div><p v-if="error" role="status">{{ error }}</p><div v-if="!tasks.length" class="empty-state"><Clock3 :size="30" /><h3>目前没有待查看的任务</h3><p>此处只显示由本浏览器记录的任务，不代表后台没有采集工作。</p></div><div v-for="(task, index) in tasks" :key="task.task_id" class="task-row"><Clock3 :size="18" /><strong>资料处理任务 {{ index + 1 }}</strong><span class="mini-pill">{{ label(task.status) }}</span></div></section></template>
