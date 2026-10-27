<script setup lang="ts">
/** 达成条 AchievementBar（CMP-F10-01）：细横条 = 实际 ÷ 预算，竖刻度 = 时间进度；规则见 achievement.ts */
import { computed } from 'vue'
import { achievementLevel, barPosition, type AchievementKind, type AchievementLevel } from './achievement'
import { formatPercent } from '@/utils/decimal'

const props = withDefaults(
  defineProps<{
    /** 达成率，百分数字符串（"88.0"）；null 表示分母 ≤ 0 等无法计算 */
    rate: string | number | null
    /** 时间进度，百分数字符串；不传则不画刻度 */
    progress?: string | number | null
    kind?: AchievementKind
    /** 服务端已给出分级时直接使用 */
    level?: AchievementLevel
    /** 是否在条右侧显示数值 */
    showValue?: boolean
  }>(),
  { progress: null, kind: 'neutral', level: undefined, showValue: false },
)

const fillWidth = computed(() => barPosition(props.rate) ?? 0)
const tickLeft = computed(() => barPosition(props.progress))
const resolvedLevel = computed(() => props.level ?? achievementLevel(props.kind, props.rate, props.progress))
const rateText = computed(() => formatPercent(props.rate === null ? null : String(props.rate).replace(/%$/, '')))
const label = computed(() => {
  const parts = [`达成 ${rateText.value}`]
  if (props.progress !== null && props.progress !== undefined && props.progress !== '') {
    parts.push(`时间进度 ${formatPercent(String(props.progress).replace(/%$/, ''))}`)
  }
  return parts.join('，')
})
</script>

<template>
  <span class="attain-wrap">
    <span
      class="attain"
      :class="resolvedLevel !== 'neutral' ? `is-${resolvedLevel}` : ''"
      role="img"
      :aria-label="label"
      :title="label"
      :data-level="resolvedLevel"
    >
      <span class="fill" :style="{ width: fillWidth + '%' }"></span>
      <span v-if="tickLeft !== null" class="tick" :style="{ left: `calc(${tickLeft}% - 1px)` }"></span>
    </span>
    <span v-if="showValue" class="attain-value" :class="{ bad: resolvedLevel === 'bad' }">{{ rateText }}</span>
  </span>
</template>

<style scoped>
.attain-wrap { display: inline-flex; align-items: center; gap: var(--space-2); vertical-align: middle; }
.attain { display: inline-block; flex: none; }
.attain > .fill, .attain > .tick { display: block; }
.attain-value { font-size: var(--text-sm); font-variant-numeric: tabular-nums; }
</style>
