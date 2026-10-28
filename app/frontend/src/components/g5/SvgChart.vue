<script setup lang="ts">
/** 图表容器：渲染 bizfin/charts.ts 生成的 SVG 字符串（文本已在生成时转义） */
defineProps<{ svg: string; label?: string }>()
</script>

<template>
  <div class="chart" role="img" :aria-label="label" v-html="svg" />
</template>
