<script setup lang="ts">
/** 右侧抽屉（页面唯一带浮层阴影的元素）；Esc 或点击遮罩 = 取消 */
import { onBeforeUnmount, onMounted } from 'vue'

withDefaults(defineProps<{ title: string; sub?: string; wide?: boolean }>(), { sub: '', wide: false })
const emit = defineEmits<{ close: [] }>()

function onKey(e: KeyboardEvent): void {
  if (e.key === 'Escape') emit('close')
}
onMounted(() => document.addEventListener('keydown', onKey))
onBeforeUnmount(() => document.removeEventListener('keydown', onKey))
</script>

<template>
  <div>
    <div class="drawer-mask" @click="emit('close')"></div>
    <section class="drawer" :class="{ wide }" role="dialog" aria-modal="true" :aria-label="title">
      <header>
        <h2>{{ title }}</h2>
        <div v-if="sub" class="meta">{{ sub }}</div>
      </header>
      <div class="body"><slot /></div>
      <footer><slot name="footer" /></footer>
    </section>
  </div>
</template>
