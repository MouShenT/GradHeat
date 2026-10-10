<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { Download, GitCompareArrows, Save, SlidersHorizontal, X } from 'lucide-vue-next'
import { api, job } from '../api'
import StatusChip from '../components/StatusChip.vue'
import { chosen, fmt, ratio, state, toggle } from '../state'
import type { DataRow } from '../types'
const dimensions: Record<string, string> = { research: '研究兴趣', location: '城市与生活', cost: '费用可承受度', career: '就业与发展', training: '培养方式适配' }
interface Rating { low: number | ''; high: number | ''; basis: string }
interface CandidateDraft { eligibility: string; ratings: Record<string, Rating>; notes: string }
interface Draft { title: string; notes: string; weights: Record<string, number>; candidates: Record<string, CandidateDraft> }
interface Saved { comparison_id: string; title: string; created_at: string; candidate_count: number }
interface Result { input: { title: string }; interpretation: string; assumptions: string[]; cards?: { id: string; programme: { unit: string; major_name: string } }[]; baseline: { intervals: Record<string, { low: number; high: number; unknown_dimensions: string[]; specified_weight: number }>; certain_best: string[]; potential_best: string[] }; stable_certain_best: string[] }
function initial(): Draft {
  const empty: Draft = { title: '我的 2027 择校比较', notes: '', weights: Object.fromEntries(Object.keys(dimensions).map(d => [d, 1])), candidates: {} }
  try { const previous = JSON.parse(localStorage.getItem('gradheat-vue-comparison-draft') || 'null'); return previous?.weights && previous?.candidates ? { ...empty, ...previous } : empty } catch { return empty }
}
const draft = reactive(initial()); const editing = ref(false); const busy = ref(false); const message = ref(''); const result = ref<Result | null>(null); const saved = ref<Saved[]>([]); let revision = 0
watch(chosen, () => { for (const p of chosen.value) draft.candidates[p.id] ||= { eligibility: 'unknown', notes: '', ratings: Object.fromEntries(Object.keys(dimensions).map(d => [d, { low: '', high: '', basis: '' }])) } }, { immediate: true })
watch(() => JSON.stringify([draft, state.selected, state.version]), () => { revision++; result.value = null; try { localStorage.setItem('gradheat-vue-comparison-draft', JSON.stringify(draft)) } catch { message.value = '浏览器无法保留草稿，请及时保存比较。' } })
const titleNames = computed(() => Object.fromEntries([...chosen.value.map(p => [p.id, `${p.unit} · ${p.major_name}`]), ...(result.value?.cards || []).map(c => [c.id, `${c.programme.unit} · ${c.programme.major_name}`])]))
function history(id: string): DataRow[] { const matches = state.data?.historical_alignment?.[id]?.matched || []; return (state.data?.history || []).filter(r => matches.includes(r.id)).sort((a, b) => b.year - a.year).slice(0, 4) }
function input() {
  if (!state.version) throw Error('资料版本尚未就绪，请刷新。')
  if (!Object.values(draft.weights).some(n => n > 0)) throw Error('至少一项权重需要大于零。')
  const candidates = chosen.value.map(p => {
    const candidate = draft.candidates[p.id]!; const ratings: Record<string, { low: number; high: number; basis: string }> = {}
    for (const [d, rating] of Object.entries(candidate.ratings)) {
      if (rating.low === '' && rating.high === '') continue
      if (rating.low === '' || rating.high === '' || rating.low > rating.high) throw Error(`${dimensions[d]}需要填写有效的上下限，或同时留空。`)
      ratings[d] = { low: rating.low, high: rating.high, basis: rating.basis }
    }
    return { programme_id: p.id, personal_eligibility: candidate.eligibility, ratings, notes: candidate.notes }
  })
  return { title: draft.title.trim(), data_version: state.version, profile: { target_year: 2027, modes: ['全日制'], degrees: ['学术学位', '专业学位'], notes: draft.notes }, weights: { ...draft.weights }, candidates }
}
async function readSaved() { try { saved.value = (await api<{ items: Saved[] }>('/admissions/comparisons')).data.items } catch (e) { message.value = e instanceof Error ? e.message : '保存记录读取暂不可用。' } }
async function run(save: boolean) {
  let body: unknown; try { body = input() } catch (e) { message.value = e instanceof Error ? e.message : '请检查填写。'; return }
  const submitted = revision; busy.value = true; message.value = save ? '正在保存本次比较…' : '正在计算偏好范围…'
  try {
    if (save) {
      const receipt = (await api<{ comparison_id: string; reused: boolean }>('/admissions/comparisons', body)).data
      const record = (await api<{ result: Result }>(`/admissions/comparisons/${receipt.comparison_id}`)).data
      if (submitted === revision) result.value = record.result
      message.value = submitted === revision ? '已保存提交时的资料与填写内容。' : '已保存提交时的版本；当前条件已变化，请重新计算。'
      await readSaved()
    } else {
      const value = await job<Result>('/admissions/compare', body)
      if (submitted !== revision) { message.value = '填写内容已改变，请重新计算。'; return }
      result.value = value; message.value = '已计算，你可以继续调整偏好。'
    }
  } catch (e) { message.value = e instanceof Error ? e.message : '比较暂不可用。' } finally { busy.value = false }
}
async function showSaved(id: string) { try { result.value = (await api<{ result: Result }>(`/admissions/comparisons/${id}`)).data.result; message.value = '显示保存时的结果；当前填写内容已保留。' } catch (e) { message.value = e instanceof Error ? e.message : '读取暂不可用。' } }
</script>
<template><div v-if="!chosen.length" class="card empty-state"><GitCompareArrows :size="38" /><h2>先建立你的候选清单</h2><p>从招生计划加入专业，最多并排比较 8 个。</p><RouterLink to="/plans" class="button">查看招生计划</RouterLink></div><template v-else><div class="section-tools"><span class="section-label">{{ chosen.length }} 个候选专业</span><button class="button subtle" @click="editing = !editing"><SlidersHorizontal :size="15" />{{ editing ? '收起偏好' : '填写个人偏好' }}</button></div><div class="comparison-grid"><article v-for="p in chosen" :key="p.id" class="card comparison-card"><div class="card-heading"><span class="mini-pill">{{ p.major_code }}</span><button class="icon-button" :aria-label="`移除${p.unit}${p.major_name}`" @click="toggle(p.id)"><X :size="17" /></button></div><h2>{{ p.unit }}</h2><h3>{{ p.major_name }}</h3><p class="muted">{{ p.department }}</p><dl><dt>学位 / 方式</dt><dd>{{ p.degree_type }} · {{ p.mode }}</dd><dt>初试科目</dt><dd>{{ p.subjects.join(' / ') }}</dd><dt>2027 计划</dt><dd>{{ p.plan_text || '—' }}<StatusChip :text="p.plan_status" /></dd><dt>普通统考</dt><dd>{{ fmt(p.ordinary_quota) }}</dd><dt>本科背景</dt><dd><StatusChip text="友好程度待核" /></dd></dl><div class="comparison-history"><h4>对应专业历史</h4><div v-for="row in history(p.id)" :key="row.id"><b>{{ row.year }}</b><p>复试线 {{ row.cutoff_text || '—' }} · 拟录取 {{ row.admit_text || '—' }}</p><p>复录比 {{ ratio(row.interview_admit_ratio) }}</p><small>{{ row.admitted_score_text || '暂无录取分数统计' }}</small></div><p v-if="!history(p.id).length" class="muted">暂无明确对应的历史专业数据。</p></div></article></div><section v-if="editing" class="card personal-preferences"><div class="card-heading"><div><h2>让偏好进入比较</h2><p>填写适配度 0—10；留空表示未知，不是初试分数。</p></div></div><form @submit.prevent="run(false)"><div class="preference-grid"><label>比较名称<input v-model="draft.title" maxlength="120" required></label><label>个人备注<input v-model="draft.notes" maxlength="2000" placeholder="城市、预算或职业方向"></label></div><div class="weight-grid"><label v-for="(name, key) in dimensions" :key="key">{{ name }}<input v-model.number="draft.weights[key]" type="number" min="0" max="10" step="0.1" required></label></div><details v-for="p in chosen" :key="p.id" class="rating-section"><summary>{{ p.unit }} · {{ p.major_name }}</summary><label>个人报考资格<select v-model="draft.candidates[p.id]!.eligibility"><option value="unknown">尚未确认</option><option value="self_reported_pass">我已核对，符合条件</option><option value="self_reported_fail">不符合条件</option></select></label><div class="rating-grid"><fieldset v-for="(name, key) in dimensions" :key="key"><legend>{{ name }}</legend><div><input v-model.number="draft.candidates[p.id]!.ratings[key]!.low" type="number" min="0" max="10" step="0.1" placeholder="下限" :aria-label="`${p.unit}${name}下限`"><span>—</span><input v-model.number="draft.candidates[p.id]!.ratings[key]!.high" type="number" min="0" max="10" step="0.1" placeholder="上限" :aria-label="`${p.unit}${name}上限`"></div><input v-model="draft.candidates[p.id]!.ratings[key]!.basis" maxlength="600" placeholder="判断依据" :aria-label="`${p.unit}${name}依据`"></fieldset></div></details><div class="form-actions"><button class="button" :disabled="busy" type="submit">计算偏好比较</button><button class="button subtle" :disabled="busy" type="button" @click="run(true)"><Save :size="15" />保存比较</button><span class="muted" role="status">{{ message }}</span></div></form></section><section v-if="result" class="card preference-results"><h2>{{ result.input.title }}</h2><p>{{ result.interpretation }}</p><div class="score-grid"><article v-for="(interval, id) in result.baseline.intervals" :key="id"><strong>{{ titleNames[id] || '保存时的候选专业' }}</strong><div class="interval-score">{{ fmt(interval.low) }}—{{ fmt(interval.high) }}<small>/ 10</small></div><StatusChip :text="result.baseline.certain_best.includes(String(id)) ? '本次偏好范围内最优' : result.baseline.potential_best.includes(String(id)) ? '可能最优' : '本次非最优'" /><p>已填写偏好权重 {{ Math.round(interval.specified_weight * 100) }}%</p></article></div><details><summary>查看本次计算说明</summary><p v-for="assumption in result.assumptions" :key="assumption">{{ assumption }}</p></details></section></template><details class="saved-comparisons" @toggle="($event.target as HTMLDetailsElement).open && readSaved()"><summary>已保存的比较</summary><div v-for="record in saved" :key="record.comparison_id" class="saved-row"><div><strong>{{ record.title }}</strong><small>{{ new Date(record.created_at).toLocaleString('zh-CN') }} · {{ record.candidate_count }} 个专业</small></div><div><button class="text-button" @click="showSaved(record.comparison_id)">查看</button><a :href="`/api/v1/admissions/comparisons/${record.comparison_id}/export?format=md`" class="text-button"><Download :size="14" />报告</a><a :href="`/api/v1/admissions/comparisons/${record.comparison_id}/export?format=json`" class="text-button">数据</a></div></div><p v-if="!saved.length" class="muted">暂无保存记录，填写偏好后可保存。</p></details></template>
