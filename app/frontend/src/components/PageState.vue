<script setup lang="ts">
/**
 * 页面状态：空 / 加载 / 错误 / 无权限（DESIGN.md「页面状态」：.state / .state-title / .skeleton）
 * - 传 error（ApiError）时自动判断：403 → 无权限，其他 → 错误
 * - 空状态：一句话说明 + 一个能产生数据的操作（action 插槽），不用插画
 */
import { computed } from 'vue'
import { ApiError, FORBIDDEN_MESSAGE, NETWORK_ERROR_MESSAGE } from '@/api/client'

export type PageStateKind = 'empty' | 'loading' | 'error' | 'forbidden'

const props = withDefaults(
  defineProps<{
    state?: PageStateKind
    error?: unknown
    title?: string
    description?: string
    /** 加载态骨架行数 */
    rows?: number
    /** 是否包在 .card 工作面里 */
    card?: boolean
  }>(),
  { state: undefined, error: undefined, title: undefined, description: undefined, rows: 6, card: true },
)

const emit = defineEmits<{ retry: [] }>()

const kind = computed<PageStateKind>(() => {
  if (props.state) return props.state
  if (props.error instanceof ApiError && props.error.isForbidden) return 'forbidden'
  if (props.error) return 'error'
  return 'empty'
})

const errorMessage = computed(() => {
  if (props.description) return props.description
  if (props.error instanceof ApiError && props.error.status >= 400 && props.error.status < 500) return props.error.message
  return NETWORK_ERROR_MESSAGE
})
</script>

<template>
  <div v-if="kind === 'loading'" :class="{ card }" aria-busy="true" data-state="loading">
    <div class="skeleton" style="width: 30%; margin-bottom: var(--space-4)"></div>
    <div v-for="i in rows" :key="i" class="skeleton" style="margin-top: var(--space-3)"></div>
    <span class="sr-only">正在加载…</span>
  </div>

  <div v-else-if="kind === 'forbidden'" class="state" :class="{ card }" role="alert" data-state="forbidden">
    <div class="state-title">{{ title ?? FORBIDDEN_MESSAGE }}</div>
    <p v-if="description">{{ description }}</p>
    <slot name="action">
      <RouterLink class="btn" :to="{ name: 'workbench' }">返回工作台</RouterLink>
    </slot>
  </div>

  <div v-else-if="kind === 'error'" class="state" :class="{ card }" role="alert" data-state="error">
    <div class="state-title">{{ title ?? '数据加载失败' }}</div>
    <p>{{ errorMessage }}</p>
    <slot name="action">
      <button type="button" class="btn" @click="emit('retry')">重试</button>
    </slot>
  </div>

  <div v-else class="state" :class="{ card }" data-state="empty">
    <div class="state-title">{{ title ?? '暂无数据' }}</div>
    <p v-if="description">{{ description }}</p>
    <slot name="action" />
  </div>
</template>

<style scoped>
.state p { margin: 0 0 var(--space-4); }
.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
</style>
