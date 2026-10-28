<script setup lang="ts">
/**
 * 图例行（原 lgRow(items)），色块 + 名称，样式用 g5.css 的 .legend。
 * props：
 * - items: { name: string; color: string; dash?: string }[]   名称与色值（色值用引擎 CH_COLOR / CAT_COLOR / PAL / provColor 等常量）；
 *   dash 为折线的 stroke-dasharray（如 '7 4'），给出时图例画一段同线型的短线代替色块，与图中线型对应
 */
defineProps<{ items: { name: string; color: string; dash?: string }[] }>()
</script>

<template>
  <div class="legend">
    <span v-for="it in items" :key="it.name">
      <svg v-if="it.dash !== undefined" class="line-key" viewBox="0 0 22 8" aria-hidden="true">
        <line x1="1" y1="4" x2="21" y2="4" :stroke="it.color" stroke-width="2.4" :stroke-dasharray="it.dash || undefined" />
      </svg>
      <i v-else :style="{ background: it.color }" />{{ it.name }}
    </span>
  </div>
</template>

<style scoped>
.line-key { width: 22px; height: 8px; margin-right: 4px; vertical-align: 0; }
</style>
