<script setup lang="ts">
/**
 * 偏差说明弹窗（AC-F10-11，API-F10-05 PUT /api/variance-notes）
 * 财务BP 填写或修改（空内容就地提示「请填写说明内容」）；其他角色只读查看全文。
 */
import { nextTick, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { api, ApiError, NETWORK_ERROR_MESSAGE } from '@/api/client'
import type { NoteTarget, VarianceNote } from './types'

const props = defineProps<{ target: NoteTarget | null; canEdit: boolean }>()
const emit = defineEmits<{ close: []; saved: [note: VarianceNote] }>()

const text = ref('')
const error = ref('')
const saving = ref(false)
const input = ref<HTMLTextAreaElement | null>(null)
const closeBtn = ref<HTMLButtonElement | null>(null)

watch(
  () => props.target,
  async (t) => {
    text.value = t?.note?.text ?? ''
    error.value = ''
    if (t) {
      await nextTick()
      ;(props.canEdit ? input.value : closeBtn.value)?.focus()
    }
  },
)

async function save(): Promise<void> {
  const t = props.target
  if (!t || saving.value) return
  if (!text.value.trim()) {
    error.value = '请填写说明内容'
    return
  }
  saving.value = true
  try {
    const res = await api.put<VarianceNote>('/api/variance-notes', {
      report_type: t.report_type,
      month: t.month,
      object_type: t.object_type,
      object_key: t.object_key,
      note: text.value,
    })
    ElMessage({ message: '偏差说明已保存', duration: 3000 })
    emit('saved', { text: res.text, author: res.author, updated_at: res.updated_at })
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : NETWORK_ERROR_MESSAGE
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div v-if="target" class="modal-backdrop" @click.self="emit('close')" @keydown.esc="emit('close')">
    <div class="modal" role="dialog" aria-modal="true" aria-labelledby="g4-note-title">
      <h3 id="g4-note-title">偏差说明</h3>
      <div class="meta">
        {{ target.month }} · {{ target.label }}<template v-if="target.note"> · {{ target.note.author }} 于 {{ target.note.updated_at }} 填写</template>
      </div>
      <div v-if="canEdit">
        <textarea
          ref="input"
          v-model="text"
          aria-label="偏差说明"
          :aria-invalid="!!error || undefined"
          placeholder="写明偏差原因，例如：4 月 Prime 会员日前备货不足，3 款框镜断货 9 天"
          @input="error = ''"
        ></textarea>
        <div v-if="error" class="field-error" role="alert">{{ error }}</div>
      </div>
      <p v-else class="note-full">{{ target.note?.text ?? '—' }}</p>
      <div class="modal-actions">
        <button ref="closeBtn" type="button" class="btn" @click="emit('close')">关闭</button>
        <button v-if="canEdit" type="button" class="btn btn-primary" :disabled="saving" @click="save">
          {{ saving ? '正在保存…' : '保存说明' }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.modal-backdrop { z-index: 50; }
.modal h3 { margin: 0 0 var(--space-1); font-size: var(--text-lg); }
.meta { font-size: var(--text-sm); color: var(--muted); margin-bottom: var(--space-3); }
.note-full { margin: 0; white-space: pre-wrap; }
textarea { width: 100%; min-height: 120px; box-sizing: border-box; padding: var(--space-2) var(--space-3); border: 1px solid var(--border); border-radius: var(--radius-md); font: inherit; color: var(--fg); background: var(--surface); resize: vertical; }
textarea:hover { border-color: var(--muted); }
textarea:focus-visible { outline: none; border-color: var(--accent); box-shadow: var(--focus-ring); }
.modal-actions { display: flex; justify-content: flex-end; gap: var(--space-2); margin-top: var(--space-4); }
</style>
