<script setup lang="ts">
/** G3 弹窗：app.css 的 .modal-backdrop / .modal；Esc 或点「取消」关闭，打开时聚焦首个可操作元素 */
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'

const props = withDefaults(defineProps<{ open: boolean; title: string; wide?: boolean }>(), { wide: false })
const emit = defineEmits<{ close: [] }>()
const box = ref<HTMLElement | null>(null)

function onKey(e: KeyboardEvent): void {
  if (e.key === 'Escape' && props.open) emit('close')
}
watch(
  () => props.open,
  async (v) => {
    if (v) {
      document.addEventListener('keydown', onKey)
      await nextTick()
      box.value?.querySelector<HTMLElement>('textarea, input, select, button')?.focus()
    } else {
      document.removeEventListener('keydown', onKey)
    }
  },
  { immediate: true },
)
onBeforeUnmount(() => document.removeEventListener('keydown', onKey))
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="modal-backdrop g3-backdrop" @click.self="emit('close')">
      <div ref="box" class="modal g3-modal" :class="{ 'modal-wide': wide }" role="dialog" aria-modal="true" :aria-label="title">
        <h2>{{ title }}</h2>
        <slot />
        <div class="modal-actions"><slot name="actions" /></div>
      </div>
    </div>
  </Teleport>
</template>
