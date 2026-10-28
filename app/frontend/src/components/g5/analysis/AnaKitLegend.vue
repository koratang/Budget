<script setup lang="ts">
/**
 * 图例行（原 lgRow(items)），色块 + 名称，样式用 g5.css 的 .legend。
 * props：
 * - items: { name: string; color: string }[]   名称与色值（色值用引擎 CH_COLOR / CAT_COLOR / PAL / provColor 等常量）
 */
defineProps<{ items: { name: string; color: string }[] }>()
</script>

<template>
  <div class="legend">
    <span v-for="it in items" :key="it.name"><i :style="{ background: it.color }" />{{ it.name }}</span>
  </div>
</template>
