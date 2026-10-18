<script setup lang="ts">
import type { CommunityAdmissionSample } from '../types'

defineProps<{ samples: CommunityAdmissionSample[] }>()
</script>
<template>
  <details v-if="samples.length">
    <summary>站点名单样本（{{ samples.length }} 组）</summary>
    <div class="index-table"><table>
      <thead><tr><th>年度 / 专业</th><th>科目组合</th><th>站点名单记录</th><th>标为录取</th><th>标为未录</th><th>站点名单最低</th><th>录取样本最低</th></tr></thead>
      <tbody><tr v-for="(sample, i) in samples" :key="`${sample.year}-${sample.program_name}-${i}`">
        <td>{{ sample.year ?? '年度待核' }}<small>{{ sample.program_name || '专业范围待核' }}</small><small v-if="sample.verification_state === 'extracted-needs-scope-review'">范围待交叉核对</small></td>
        <td>{{ sample.exam_text || '科目待核' }}</td>
        <td>{{ sample.record_count ?? '—' }}</td>
        <td>{{ sample.admitted_sample_count ?? '—' }}</td>
        <td>{{ sample.unadmitted_retest_sample_count ?? '—' }}</td>
        <td>{{ sample.observed_retest_list_minimum ?? '—' }}</td>
        <td>{{ sample.admitted_total_minimum ?? '—' }}</td>
      </tr></tbody>
    </table></div>
    <p class="muted">数量 0 表示站点已报零条，— 表示未提供。最低分适用范围为站点现有名单。</p>
  </details>
</template>
