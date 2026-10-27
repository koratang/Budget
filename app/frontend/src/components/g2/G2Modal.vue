<script setup lang="ts">
/** G2 弹窗：沿用原型的 .modal-backdrop / .modal（app.css）；点遮罩或 Esc 关闭 */
import { onBeforeUnmount, onMounted } from 'vue'

withDefaults(defineProps<{ title: string; wide?: boolean }>(), { wide: false })
const emit = defineEmits<{ close: [] }>()

function onKey(e: KeyboardEvent): void {
  if (e.key === 'Escape') emit('close')
}
onMounted(() => document.addEventListener('keydown', onKey))
onBeforeUnmount(() => document.removeEventListener('keydown', onKey))
</script>

<template>
  <Teleport to="body">
    <div class="modal-backdrop g2-modal" @click.self="emit('close')">
      <div class="modal" :class="{ wide }" role="dialog" aria-modal="true" :aria-label="title">
        <h2>{{ title }}</h2>
        <slot />
        <div class="modal-actions"><slot name="actions" /></div>
      </div>
    </div>
  </Teleport>
</template>
