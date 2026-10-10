<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RefreshCw, TrendingUp } from 'lucide-vue-next'
import { api } from '../api'
import { state } from '../state'
import type { Heat } from '../types'
const unit = ref(state.unit || state.data?.units.find(u => u.name === '北京邮电大学')?.name || state.data?.units[0]?.name || '')
const heat = ref<Heat | null>(null), busy = ref(false), error = ref(''); let generation = 0
const schools = ref<Heat[]>([])
const available = computed(() => schools.value.length ? schools.value.map(s => s.unit) : state.data?.units.map(u => u.name) || [])
const ranked = computed(() => [...schools.value].filter(s => s.heat_value != null).sort((a,b) => (b.heat_value || 0)-(a.heat_value || 0)))
async function refresh() {
  const revision = ++generation; busy.value = true; error.value = ''
  try { const { data } = await api<Heat>(`/heat?unit=${encodeURIComponent(unit.value)}`); if (revision === generation) heat.value = data }
  catch (e) { if (revision === generation) error.value = e instanceof Error ? e.message : '读取暂不可用。' }
  finally { if (revision === generation) busy.value = false }
}
watch(unit, () => { heat.value = null; refresh() })
let timer: ReturnType<typeof setInterval>
onMounted(() => { refresh(); api<Heat[]>('/school-indices').then(r => { schools.value = r.data }).catch(() => {}); timer = setInterval(() => { if (!document.hidden && !busy.value) { refresh(); api<Heat[]>('/school-indices').then(r => { schools.value = r.data }).catch(() => {}) } }, 60000) })
onBeforeUnmount(() => { clearInterval(timer); generation++ })
function stamp(value?: string) { return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '尚未更新' }
</script>
<template>
  <section class="card heat-heading"><div><span class="eyebrow">SCHOOL HEAT</span><h2>院校热度值</h2><p>讨论与搜索关注度，统一为 0—100。</p></div><div class="inline-controls"><select v-model="unit" aria-label="热度招生单位"><option v-for="name in available" :key="name">{{ name }}</option></select><button class="button subtle" :disabled="busy" @click="refresh"><RefreshCw :size="15" :class="{ spinning: busy }" />刷新</button></div></section>
  <p v-if="error" class="error-banner" role="status">{{ error }}</p>
  <section class="card index-hero" aria-label="院校热度值"><TrendingUp :size="28"/><h3>{{ unit }}</h3><strong class="index-value">{{ heat?.heat_value == null ? '—' : heat.heat_value.toFixed(1) }}</strong><span>热度值 / 100</span><p class="muted">{{ heat?.basis === 'discussion-only' ? '讨论热度估算 · 搜索数据待接入' : heat?.basis === 'discussion-and-search' ? '讨论与搜索综合热度' : heat?.basis === 'search-only' ? '搜索热度估算' : busy ? '正在计算…' : '尚无足够数据' }}</p><small class="muted">更新 {{ stamp(heat?.checked_at) }}</small></section>
  <section v-if="ranked.length" class="card game-result"><h2>各院校热度</h2><div class="index-table"><table><thead><tr><th>院校</th><th>热度值</th></tr></thead><tbody><tr v-for="s in ranked" :key="s.unit"><td><button class="text-button" @click="unit = s.unit">{{s.unit}}</button></td><td><strong>{{s.heat_value?.toFixed(1)}}</strong></td></tr></tbody></table></div></section>
</template>
