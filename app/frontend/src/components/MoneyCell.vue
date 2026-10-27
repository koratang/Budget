<script setup lang="ts">
/**
 * 金额单元 MoneyCell：右对齐、等宽数字；按「有利 / 不利」着色（不利红 / 有利绿）
 * - value 为十进制字符串（接口约定）；display 为后端已格式化的展示值（优先使用）
 * - direction：higher-better（收入、利润差额：正数有利）/ lower-better（费用差额：正数不利）/ none（不着色）
 * - favorable 显式指定时覆盖 direction 判断
 */
import { computed } from 'vue'
import { formatDecimal, signOf } from '@/utils/decimal'

const props = withDefaults(
  defineProps<{
    value: string | null | undefined
    display?: string | null
    direction?: 'higher-better' | 'lower-better' | 'none'
    favorable?: boolean | null
    currency?: string
    scale?: number
  }>(),
  { display: null, direction: 'none', favorable: null, currency: '', scale: 2 },
)

const tone = computed<'good' | 'bad' | null>(() => {
  if (props.favorable === true) return 'good'
  if (props.favorable === false) return 'bad'
  if (props.direction === 'none') return null
  const s = signOf(props.value)
  if (s === null || s === 0) return null
  const good = props.direction === 'higher-better' ? s > 0 : s < 0
  return good ? 'good' : 'bad'
})

const text = computed(() => {
  if (props.display) return props.display
  const f = formatDecimal(props.value, props.scale)
  if (f === '—' || !props.currency) return f
  return `${props.currency} ${f}`
})
</script>

<template>
  <span class="money" :class="tone" :data-tone="tone ?? 'none'">{{ text }}</span>
</template>

<style scoped>
.money { display: block; text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
</style>
