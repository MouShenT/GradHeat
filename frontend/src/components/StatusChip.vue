<script setup lang="ts">
import { computed } from 'vue'
const props = defineProps<{ text?: unknown }>()
const label = computed(() => props.text ? String(props.text) : '待补充')
const tone = computed(() => /两源|三源|已核|符合/.test(label.value) ? 'green' : /冲突|不符合/.test(label.value) ? 'red' : 'amber')
</script>
<template><span class="status-chip" :class="tone"><i />{{ label }}</span></template>
