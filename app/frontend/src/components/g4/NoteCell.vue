<script setup lang="ts">
/** 偏差说明单元格（AC-F10-11）：说明首行 + 填写人 · 时间；财务BP 可填写 / 编辑，其他角色只读查看全文 */
import type { VarianceNote } from './types'

defineProps<{ note: VarianceNote | null | undefined; canEdit: boolean }>()
const emit = defineEmits<{ open: [] }>()
</script>

<template>
  <div class="note-cell-inner">
    <template v-if="note">
      <div class="note-text" :title="note.text">{{ note.text }}</div>
      <div class="note-by">
        {{ note.author }} · {{ note.updated_at }} ·
        <button type="button" class="link-btn" @click="emit('open')">{{ canEdit ? '查看/编辑' : '查看全文' }}</button>
      </div>
    </template>
    <button v-else-if="canEdit" type="button" class="link-btn" @click="emit('open')">填写说明</button>
    <span v-else class="muted">—</span>
  </div>
</template>

<style scoped>
.note-cell-inner { min-width: 200px; max-width: 260px; white-space: normal; line-height: var(--leading-tight); padding: 6px 0; }
.note-text { display: -webkit-box; -webkit-line-clamp: 1; line-clamp: 1; -webkit-box-orient: vertical; overflow: hidden; color: var(--fg-2); }
.note-by { font-size: var(--text-xs); color: var(--muted); }
.muted { color: var(--muted); }
.link-btn { padding: 0; border: 0; background: none; color: var(--fg-2); text-decoration: underline; font-size: var(--text-xs); cursor: pointer; border-radius: var(--radius-sm); }
.link-btn:hover { color: var(--fg); }
.link-btn:focus-visible { outline: none; box-shadow: var(--focus-ring); }
</style>
