<script setup lang="ts">
/** 居中弹窗（app.css .modal-backdrop / .modal）；Esc = 取消 */
import { onBeforeUnmount, onMounted } from 'vue'

withDefaults(defineProps<{ title: string; alert?: boolean }>(), { alert: false })
const emit = defineEmits<{ close: [] }>()

function onKey(e: KeyboardEvent): void {
  if (e.key === 'Escape') emit('close')
}
onMounted(() => document.addEventListener('keydown', onKey))
onBeforeUnmount(() => document.removeEventListener('keydown', onKey))
</script>

<template>
  <div class="modal-backdrop">
    <div class="modal" :role="alert ? 'alertdialog' : 'dialog'" aria-modal="true" :aria-label="title">
      <h3>{{ title }}</h3>
      <slot />
      <div class="acts"><slot name="actions" /></div>
    </div>
  </div>
</template>
