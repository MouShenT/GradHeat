<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { ArrowRight, Layers3 } from 'lucide-vue-next'
import { job } from '../api'
import BarChart from '../components/BarChart.vue'
import { chosen, fmt, state } from '../state'
interface Allocation { programme_id: string; hypothetical_capacity: number; hypothetical_choices: number; crowding_ratio: number; model_utility: number }
interface Scenario { participants: number; converged: boolean; allocations: Allocation[]; demand_factor?: number }
interface Result { base: Scenario; sensitivity: Scenario[]; assumptions: string[]; validation: string }
const participants = ref(120); const weight = ref(2); const options = reactive<Record<string, { capacity: number | ''; preference: number }>>({})
const result = ref<Result | null>(null); const busy = ref(false); const message = ref(''); let revision = 0
watch(chosen, () => chosen.value.forEach(p => { options[p.id] ??= { capacity: '', preference: 5 } }), { immediate: true })
const signature = computed(() => JSON.stringify([chosen.value.map(p => p.id), options, participants.value, weight.value, state.version]))
watch(signature, () => { revision++; result.value = null; message.value = '' })
async function simulate() {
  if (chosen.value.length < 2) { message.value = '请先加入至少两个专业。'; return }
  if (!state.version) { message.value = '资料版本尚未就绪，请刷新数据。'; return }
  const submitted = revision; busy.value = true; message.value = '正在运行假设情景…'
  try {
    const value = await job<Result>('/game-scenario', { data_version: state.version, participants: participants.value, crowding_weight: weight.value, seed: 0, options: chosen.value.map(p => ({ programme_id: p.id, capacity: options[p.id]!.capacity, preference: options[p.id]!.preference })) })
    if (submitted !== revision) { message.value = '参数已改变，请重新运行。'; return }
    result.value = value; message.value = value.base.converged ? '本次假设游戏已达到稳定选择。' : '达到计算预算，当前结果尚未收敛。'
  } catch (e) { message.value = e instanceof Error ? e.message : '本次情景未完成。' } finally { busy.value = false }
}
const labels = computed(() => chosen.value.map(p => `${p.unit} · ${p.major_name}`))
const series = computed(() => (result.value?.sensitivity || []).map(s => ({ name: `需求 × ${s.demand_factor}`, values: chosen.value.map(p => s.allocations.find(a => a.programme_id === p.id)?.hypothetical_choices ?? null) })))
</script>
<template><div v-if="chosen.length < 2" class="card empty-state"><Layers3 :size="38" /><h2>先选两个想比较的专业</h2><p>从招生计划加入 2—8 个候选，就能观察假设需求变化。</p><RouterLink to="/plans" class="button">去选候选专业<ArrowRight :size="15" /></RouterLink></div><section v-else class="card"><div class="card-heading"><div><span class="eyebrow">CONGESTION SCENARIO</span><h2>建立一个有边界的假设</h2><p>容量不自动读取招生总计划；结果表示模拟选择，不是录取概率。</p></div></div><form @submit.prevent="simulate"><div class="preference-grid game-global"><label>假设参与人数<input v-model.number="participants" type="number" min="2" max="500" required></label><label>拥挤权重<input v-model.number="weight" type="number" min="0.1" max="20" step="0.1" required></label></div><div class="game-options"><article v-for="p in chosen" :key="p.id"><div><strong>{{ p.unit }}</strong><span>{{ p.major_name }} · {{ p.major_code }}</span></div><label>假设容量<input v-model.number="options[p.id]!.capacity" type="number" min="1" max="10000" placeholder="由你填写" required :aria-label="`${p.unit}${p.major_name}假设容量`"></label><label>偏好 0—10<input v-model.number="options[p.id]!.preference" type="number" min="0" max="10" step="0.1" required :aria-label="`${p.unit}${p.major_name}情景偏好`"></label></article></div><div class="form-actions"><button class="button" :disabled="busy" type="submit"><Layers3 :size="16" />{{ busy ? '正在模拟' : '运行假设情景' }}</button><span role="status" class="muted">{{ message }}</span></div></form></section><section v-if="result" class="card game-result"><div class="card-heading"><div><span class="eyebrow">DEMAND SENSITIVITY</span><h2>需求变化，选择如何分布？</h2></div><span class="mini-pill">模拟选择人数</span></div><BarChart :labels="labels" :series="series" unit=" 人" /><div class="allocation-list"><div v-for="allocation in result.base.allocations" :key="allocation.programme_id"><strong>{{ chosen.find(p => p.id === allocation.programme_id)?.unit }}</strong><span>模拟选择 {{ allocation.hypothetical_choices }}</span><span>假设容量 {{ allocation.hypothetical_capacity }}</span><span>拥挤比 {{ fmt(allocation.crowding_ratio) }}</span></div></div><details class="model-assumptions" open><summary>本次模型的适用范围</summary><p v-for="assumption in result.assumptions" :key="assumption">{{ assumption }}</p><p>{{ result.validation }}</p></details></section></template>
