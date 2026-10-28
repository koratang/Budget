<script setup lang="ts">
/**
 * 图表 / 表格下方的解读说明（原 '<div class="chart-note">…</div>'），无 props。
 * 插槽：default 说明文字，可含 <b>、<AnaKitCode>。
 */
</script>

<template>
  <div class="ana-chart-note"><slot /></div>
</template>

<style scoped>
.ana-chart-note { margin-top: var(--space-3); padding: var(--space-2) var(--space-3); border-left: 3px solid var(--accent); background: var(--surface-warm); font-size: var(--text-sm); color: var(--fg-2); line-height: 1.75; }
.ana-chart-note :deep(b) { color: var(--fg); }
</style>
