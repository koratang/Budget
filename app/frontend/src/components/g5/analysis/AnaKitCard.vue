<script setup lang="ts">
/**
 * 分析卡片（原 '<div class="card"><div class="card-head"><h3>…</h3><span class="desc">…</span><div class="r"><span class="pill">…</span></div></div><div class="card-body">…'）。
 * props：
 * - title: string           卡片标题（原 h3）
 * - desc?: string           标题旁的灰色说明（原 span.desc）
 * - pill?: string           右侧胶囊标签（原 .r .pill，如「月度（01月 ~ 09月）」）
 * 插槽：default 卡片主体（表格、图表、说明）。
 */
defineProps<{ title: string; desc?: string; pill?: string }>()
</script>

<template>
  <section class="card ana-card">
    <div class="ana-card-head">
      <h3 class="card-title">{{ title }}</h3>
      <span v-if="desc" class="small muted">{{ desc }}</span>
      <span v-if="pill" class="badge badge-info ana-card-pill">{{ pill }}</span>
    </div>
    <slot />
  </section>
</template>

<style scoped>
.ana-card { margin-bottom: var(--space-4); min-width: 0; }
.ana-card-head { display: flex; align-items: baseline; flex-wrap: wrap; gap: var(--space-2) var(--space-3); margin-bottom: var(--space-3); }
.ana-card-head .card-title { margin: 0; }
.ana-card-pill { margin-left: auto; }
</style>
