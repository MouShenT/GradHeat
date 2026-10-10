<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Activity, MessageCircle, RefreshCw, ThumbsUp, TrendingUp } from 'lucide-vue-next'
import { api } from '../api'
import { fmt, state } from '../state'
import type { Heat } from '../types'
const unit = ref(state.unit || state.data?.units.find(u => u.name === '北京邮电大学')?.name || state.data?.units[0]?.name || '')
const heat = ref<Heat | null>(null); const busy = ref(false); const error = ref(''); let generation = 0
const total = computed(() => heat.value?.platforms.reduce((n, p) => n + p.unique_contents, 0) || 0)
async function refresh() {
  const revision = ++generation; busy.value = true; error.value = ''
  try { const { data } = await api<Heat>(`/heat?unit=${encodeURIComponent(unit.value)}`); if (revision === generation) heat.value = data }
  catch (e) { if (revision === generation) error.value = e instanceof Error ? e.message : '读取暂不可用。' }
  finally { if (revision === generation) busy.value = false }
}
watch(unit, () => { heat.value = null; refresh() })
let timer: ReturnType<typeof setInterval>; onMounted(() => { refresh(); timer = setInterval(() => { if (!document.hidden && !busy.value) refresh() }, 60000) }); onBeforeUnmount(() => { clearInterval(timer); generation++ })
function stamp(value?: string | null) { return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '尚无采样' }
const colours: Record<string, string> = { xhs: '#e06072', zhihu: '#5d8ecb', dy: '#535268', bili: '#5aadc0' }
</script>
<template><section class="card heat-heading"><div><span class="eyebrow">PLATFORM PULSE</span><h2>院校讨论样本</h2><p>每 60 秒刷新已存资料，最新采集时间与页面刷新时间分开显示。</p></div><div class="inline-controls"><select v-model="unit" aria-label="热度招生单位"><option v-for="u in state.data?.units" :key="u.name">{{ u.name }}</option></select><button class="button subtle" :disabled="busy" @click="refresh"><RefreshCw :size="15" :class="{ spinning: busy }" />刷新</button></div></section><p v-if="error" class="error-banner" role="status">{{ error }}</p><div class="heat-summary"><Activity :size="18" /><span>{{ heat ? `${total} 条平台内去重内容` : '正在读取平台样本…' }}</span><span class="muted">刷新 {{ stamp(heat?.checked_at) }}</span></div><div class="heat-grid"><article v-for="platform in heat?.platforms" :key="platform.platform" class="card heat-card" :style="{ '--platform': colours[platform.platform] || '#207875' }"><div class="card-heading"><div class="platform-name"><span class="platform-mark">{{ platform.label[0] }}</span><h3>{{ platform.label }}</h3></div><span class="mini-pill" :class="{ warning: platform.health?.state === 'needs-human' }">{{ platform.health?.state === 'needs-human' ? '待人工验证' : platform.sampling_state === 'sample-available' ? '已有样本' : '暂无样本' }}</span></div><div class="heat-number"><strong>{{ platform.unique_contents || '—' }}</strong><span>{{ platform.unique_contents ? '条已存内容' : '样本尚未取得' }}</span></div><div class="heat-metrics"><div><ThumbsUp :size="14" /><small>已知点赞</small><strong>{{ fmt(platform.metrics.like?.sum_known_values) }}</strong></div><div><MessageCircle :size="14" /><small>已知评论</small><strong>{{ fmt(platform.metrics.comment?.sum_known_values) }}</strong></div><div><TrendingUp :size="14" /><small>已知播放</small><strong>{{ fmt(platform.metrics.view?.sum_known_values) }}</strong></div></div><p class="sample-time">最近采样 {{ stamp(platform.observed_until) }}</p><details class="sample-context"><summary>查看采样范围</summary><p v-for="(query, index) in platform.query_groups" :key="index">{{ query.query }}<small>{{ query.actual_sort || '实际排序未确认' }}</small></p><p>未知互动数字不计为零；同一作者的多条内容不代表多个独立招生事实。</p></details></article></div><div v-if="heat && !heat.platforms.length" class="empty-state"><h3>当前暂无可读的平台样本</h3><p>未知不表示热度为零，可稍后刷新。</p></div><div class="method-note"><strong>如何理解这些数字</strong><p>{{ heat?.note || '这里展示有界关键词样本，不能推算全站热度、实际报名人数或录取概率。' }}</p><p v-if="heat?.read_state === 'previous-verified-sample' || heat?.read_state === 'using-last-verified-cache'">本次使用此前已核样本，采样时间保留原值。</p></div></template>
