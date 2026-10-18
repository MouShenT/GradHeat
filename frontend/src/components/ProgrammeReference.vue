<script setup lang="ts">
import { computed } from 'vue'
import type { ProgrammeDecisionInputs } from '../types'

const props = defineProps<{ inputs?: ProgrammeDecisionInputs }>()
const thresholdLabels: Record<string, string> = {
  'official-department': '官网专业复试线',
  'aligned-history': '对齐历史复试线',
  'community-school-table': '专题站整理复试线',
  'official-school-minimum': '官网校级最低要求',
  'school-claim-estimate': '讨论估计分数参考',
}
const thresholdLabel = computed(() => thresholdLabels[props.inputs?.threshold_basis || ''] || '分数参考（来源类型待核）')
const scores = computed(() => props.inputs?.admitted_scores)
const hasScores = computed(() => scores.value?.mean != null || scores.value?.minimum != null || scores.value?.maximum != null)
const hasWeights = computed(() => props.inputs?.retest_weights?.interview_weight != null)
const yearLabel = (year?: number | null) => year == null ? '年度待核' : `${year} 年`
const percent = (value: number) => `${(value * 100).toFixed(1)}%`
</script>
<template>
  <span v-if="inputs?.threshold != null">{{ yearLabel(inputs.threshold_year) }}{{ thresholdLabel }} {{ inputs.threshold }}<small v-if="inputs.threshold_basis === 'official-school-minimum'">入围还需看院系名额和排名</small></span>
  <small v-if="hasScores">{{ yearLabel(scores?.year) }}{{ scores?.population === 'observed-sample' ? '名单样本' : '录取' }}<span v-if="scores?.mean != null">均分 {{ scores.mean }}</span><span v-if="scores?.minimum != null"> · 最低 {{ scores.minimum }}</span><span v-if="scores?.maximum != null"> · 最高 {{ scores.maximum }}</span></small>
  <small v-if="hasWeights">{{ yearLabel(inputs?.retest_weights_year) }}复试权重 {{ percent(inputs!.retest_weights.interview_weight!) }}</small>
  <span v-if="inputs?.threshold == null && !hasScores && !hasWeights">—</span>
</template>
