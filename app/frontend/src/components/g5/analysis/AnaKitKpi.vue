<script setup lang="ts">
/**
 * 极简 KPI 卡（原 kpiSimple(label, val, unit, foot, cls)），用于派生口径的分析子模块，无目标达成率。
 * props：
 * - label: string           卡片标题（原 label）
 * - value: string           主数值，调用方已格式化（原 val，如 fmt(x, 1) 或渠道名）
 * - unit?: string           数值单位（原 unit），可省略
 * - foot?: string           脚注纯文本（原 foot）；脚注里需要编码标签等结构时改用具名插槽 #foot（插槽优先）
 * - tone?: KpiTone          左侧色条（原 cls，类型从 ./AnaKit 导出）：'fin' | 'biz' | 'warn' | 'bad' | 'good'，省略为默认色
 * - compact?: boolean       主数值用较小字号（原渠道效益里渠道名 font-size:20px 的写法）
 * 插槽：#foot 脚注内容（可放 <AnaKitCode>）。
 * 多张卡放进 <div class="grid-4">（g5.css）即可排成一行。
 */
import type { KpiTone } from './AnaKit'
defineProps<{ label: string; value: string; unit?: string; foot?: string; tone?: KpiTone; compact?: boolean }>()
</script>

<template>
  <div class="card ana-kpi" :data-tone="tone">
    <div class="kpi-label">{{ label }}</div>
    <div class="ana-kpi-val" :class="{ compact }">{{ value }}<span v-if="unit" class="u">{{ unit }}</span></div>
    <div class="ana-kpi-foot"><slot name="foot">{{ foot }}</slot></div>
  </div>
</template>

<style scoped>
.ana-kpi { position: relative; overflow: hidden; padding: var(--space-3) var(--space-4); }
.ana-kpi::before { content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 3px; background: var(--muted); }
.ana-kpi[data-tone="fin"]::before { background: var(--fg-2); }
.ana-kpi[data-tone="biz"]::before { background: var(--accent); }
.ana-kpi[data-tone="warn"]::before { background: var(--warn); }
.ana-kpi[data-tone="bad"]::before { background: var(--danger); }
.ana-kpi[data-tone="good"]::before { background: var(--success); }
.ana-kpi-val { font-size: var(--text-2xl); font-weight: 700; margin-top: var(--space-1); line-height: var(--leading-tight); font-variant-numeric: tabular-nums; letter-spacing: var(--tracking-display); }
.ana-kpi-val.compact { font-size: var(--text-xl); }
.ana-kpi-val .u { font-size: var(--text-xs); font-weight: 500; color: var(--muted); margin-left: 3px; letter-spacing: 0; }
.ana-kpi-foot { margin-top: var(--space-2); font-size: var(--text-xs); color: var(--muted); }
</style>
