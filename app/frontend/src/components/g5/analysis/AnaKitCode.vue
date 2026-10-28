<script setup lang="ts">
/**
 * 指标编码标签（原 codeTag(c) → <code>c</code>），等宽小字。
 * props：
 * - code: string            指标编码，如 'F1.1'、'S1.2'
 */
defineProps<{ code: string }>()
</script>

<template>
  <code class="ana-code">{{ code }}</code>
</template>

<style scoped>
.ana-code { font-family: var(--font-mono); font-size: 0.92em; padding: 0 4px; border-radius: var(--radius-sm); background: var(--surface-raised); color: var(--fg-2); }
</style>
