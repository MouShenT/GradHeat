<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { Layers3 } from 'lucide-vue-next'
import { api } from '../api'
import { state } from '../state'
interface Profile { score: number | ''; politics: number | ''; english: number | ''; mathematics: number | ''; computer: number | ''; undergraduate_school: string; undergraduate_major: string; cross_major: boolean; previous_graduate: boolean; equivalent_education: boolean; programming: number | ''; research_experience: number | ''; preferred_tiers: string[]; preferred_units: string[]; mode: string }
interface Candidate { id: string; unit: string; major_name: string; department: string; tier: string; heat_value: number | null; victory_index: number | null; threshold: number | null; missing: string[] }
interface Result { ranking: Candidate[]; note: string; needs_profile: boolean }
const defaults: Profile = { score: '', politics: '', english: '', mathematics: '', computer: '', undergraduate_school: '', undergraduate_major: '', cross_major: false, previous_graduate: false, equivalent_education: false, programming: '', research_experience: '', preferred_tiers: [], preferred_units: [], mode: '全日制' }
let saved: Partial<Profile> = {}
try { saved = JSON.parse(localStorage.getItem('gradheat-personal-profile-v1') || '{}') } catch { /* optional draft */ }
const profile = reactive<Profile>({ ...defaults, ...Object.fromEntries(Object.entries(saved).filter(([k]) => k in defaults)) })
const result = ref<Result | null>(null), busy = ref(false), message = ref(''); let revision = 0
const signature = computed(() => JSON.stringify([profile, state.version]))
watch(signature, () => { revision++; result.value = null; message.value = ''; try { localStorage.setItem('gradheat-personal-profile-v1', JSON.stringify(profile)) } catch { /* optional draft */ } })
async function calculate() {
  const submitted = revision; busy.value = true; message.value = '正在计算各院校的胜利指数…'
  try {
    const input = { ...profile, ...Object.fromEntries(['score','politics','english','mathematics','computer','programming','research_experience'].map(k => [k, profile[k as keyof Profile] === '' ? null : profile[k as keyof Profile]])) }
    const { data } = await api<Result>('/victory-index', { data_version: state.version, profile: input, limit: 200 })
    if (submitted !== revision) { message.value = '个人条件已修改，请重新计算。'; return }
    result.value = data; message.value = data.needs_profile ? '请填写预计初试总分或完整单科分数。' : `已计算 ${data.ranking.length} 所院校。`
  } catch (e) { message.value = e instanceof Error ? e.message : '计算暂不可用。' } finally { busy.value = false }
}
</script>
<template>
  <section class="card"><div class="card-heading"><div><span class="eyebrow">YOUR VICTORY INDEX</span><h2>填写条件，计算胜利指数</h2><p>现在可以留空，以后填写；修改条件后可重新计算。</p></div></div>
  <form @submit.prevent="calculate"><div class="preference-grid">
    <label>预计初试总分<input v-model.number="profile.score" type="number" min="0" max="500" placeholder="0—500，可稍后填写" aria-label="预计初试总分"></label>
    <label>学习方式<select v-model="profile.mode"><option>全日制</option><option>非全日制</option><option value="all">全部</option></select></label>
    <label>本科院校<input v-model="profile.undergraduate_school" maxlength="160" placeholder="你的本科院校"></label><label>本科专业<input v-model="profile.undergraduate_major" maxlength="160" placeholder="你的本科专业"></label>
    <label v-for="subject in [{k:'politics', n:'政治',max:100},{k:'english',n:'英语',max:100},{k:'mathematics',n:'数学',max:150},{k:'computer',n:'408',max:150}]" :key="subject.k">{{ subject.n }}<input v-model.number="profile[subject.k as 'politics' | 'english' | 'mathematics' | 'computer']" type="number" min="0" :max="subject.max" placeholder="选填"></label>
    <label>编程 / 机试能力<input v-model.number="profile.programming" type="number" min="0" max="10" step="0.5" placeholder="自评 0—10，选填"></label><label>科研 / 项目经验<input v-model.number="profile.research_experience" type="number" min="0" max="10" step="0.5" placeholder="自评 0—10，选填"></label>
  </div><div class="form-section"><label class="form-label">希望的院校层次</label><div class="choice-pills"><label v-for="tier in ['985','211','普通院校','研究所']" :key="tier" :class="{selected:profile.preferred_tiers.includes(tier)}"><input v-model="profile.preferred_tiers" type="checkbox" :value="tier">{{ tier }}</label></div></div>
  <div class="choice-pills"><label><input v-model="profile.cross_major" type="checkbox">跨专业报考</label><label><input v-model="profile.previous_graduate" type="checkbox">往届生</label><label><input v-model="profile.equivalent_education" type="checkbox">同等学力</label></div>
  <details class="form-section"><summary>限定候选院校（可选）</summary><p class="muted">不勾选时计算所有符合 11408 的院校。</p><div class="school-choices"><label v-for="u in state.data?.units" :key="u.name"><input v-model="profile.preferred_units" type="checkbox" :value="u.name">{{ u.name }}</label></div></details>
  <div class="form-actions"><button class="button" :disabled="busy" type="submit"><Layers3 :size="16"/>{{busy ? '正在计算' : '计算胜利指数'}}</button><span class="muted" role="status">{{ message }}</span></div></form></section>
  <section v-if="result && !result.needs_profile" class="card game-result"><h2>各院校胜利指数</h2><p class="muted">{{ result.note }}</p><div class="index-table"><table><thead><tr><th>院校 / 对应专业</th><th>热度值</th><th>胜利指数</th></tr></thead><tbody><tr v-for="r in result.ranking" :key="r.unit"><td><strong>{{ r.unit }}</strong><small>{{r.department}} · {{r.major_name}}</small><small v-if="r.victory_index === null">对应分数资料待补齐</small></td><td>{{ r.heat_value == null ? '—' : r.heat_value.toFixed(1) }}</td><td><strong class="victory-number">{{ r.victory_index == null ? '—' : r.victory_index.toFixed(1) }}</strong></td></tr></tbody></table></div></section>
</template>
