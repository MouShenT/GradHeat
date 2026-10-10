<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { init, use, type ECharts } from 'echarts/core'
import { BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent, AriaComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
use([BarChart, GridComponent, TooltipComponent, LegendComponent, AriaComponent, CanvasRenderer])
const props = defineProps<{ labels: string[]; series: { name: string; values: (number | null)[]; color?: string }[]; unit?: string }>()
const element = ref<HTMLElement>(); let chart: ECharts | undefined; let observer: ResizeObserver | undefined
function update() { chart?.setOption({ aria: { enabled: true }, animationDuration: 350, color: ['#207875', '#80b7af', '#d8a667'], grid: { left: 6, right: 25, top: 38, bottom: 10, containLabel: true }, legend: { top: 0, right: 0, icon: 'roundRect', textStyle: { color: '#748184', fontSize: 11 } }, tooltip: { trigger: 'axis', renderMode: 'richText', valueFormatter: (value: unknown) => `${value ?? '未知'}${props.unit || ''}` }, xAxis: { type: 'value', splitLine: { lineStyle: { color: '#eef1ef' } }, axisLabel: { color: '#8c989b', fontSize: 10 } }, yAxis: { type: 'category', inverse: true, data: props.labels, axisTick: { show: false }, axisLine: { show: false }, axisLabel: { color: '#506265', width: 105, overflow: 'truncate', fontSize: 11 } }, series: props.series.map(s => ({ name: s.name, type: 'bar', data: s.values, barMaxWidth: 16, itemStyle: { borderRadius: [0, 5, 5, 0], color: s.color }, label: { show: true, position: 'right', color: '#506265', fontSize: 10 } })) }, true) }
onMounted(() => { if (!element.value) return; chart = init(element.value); update(); observer = new ResizeObserver(() => chart?.resize()); observer.observe(element.value) })
watch(() => [props.labels, props.series], update, { deep: true })
onBeforeUnmount(() => { observer?.disconnect(); chart?.dispose() })
</script>
<template><div v-if="labels.length" ref="element" class="chart" role="img" :aria-label="`${labels.join('、')}：${series.map(s => s.name).join('、')}`" :style="{ height: `${Math.max(240, labels.length * 52 + 55)}px` }" /><div v-else class="empty-chart">暂无对应口径的数字</div></template>
