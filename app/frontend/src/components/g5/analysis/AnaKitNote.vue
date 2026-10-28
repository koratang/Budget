<script setup lang="ts">
/**
 * 口径说明框（原 anaNote(title, body) 与 '<div class="note"><b>…</b>…</div>'）。
 * props：
 * - title: string           加粗标题，原样带冒号（如「流量分析口径：」）
 * 插槽：default 正文，可含 <b>、<AnaKitCode> 等结构。
 */
defineProps<{ title: string }>()
</script>

<template>
  <div class="ana-note">
    <b>{{ title }}</b><slot />
  </div>
</template>

<style scoped>
.ana-note { margin-bottom: var(--space-4); padding: var(--space-3) var(--space-4); background: var(--surface-warm); border: 1px solid var(--border-soft); border-radius: var(--radius-md); font-size: var(--text-sm); color: var(--fg-2); line-height: 1.85; }
.ana-note :deep(b) { color: var(--fg); }
</style>
