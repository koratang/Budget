/**
 * 达成条规则（DESIGN.md「组件设计 · 达成条」，CMP-F10-01）
 * - 填充宽度 = min(实际 ÷ 预算, 120%) 映射到条宽（条宽代表 120%）
 * - 竖刻度位置 = 时间进度（同一刻度映射）
 * - 费用类：超过时间进度 10 个百分点为琥珀、超过 100% 为红
 * - 收入类：低于时间进度 10 个百分点为琥珀、低于 70% 为红
 * - 其余为中性深灰
 * 输入为「百分数字符串」（接口约定：比率以字符串传输，"88.0" 表示 88.0%）；仅用于展示分级，不参与金额计算。
 */

export type AchievementKind = 'revenue' | 'expense' | 'neutral'
export type AchievementLevel = 'good' | 'warn' | 'bad' | 'neutral'

export const BAR_SCALE_MAX = 120

function toNumber(v: string | number | null | undefined): number | null {
  if (v === null || v === undefined || v === '') return null
  const n = typeof v === 'number' ? v : Number(String(v).replace(/%$/, '').trim())
  return Number.isFinite(n) ? n : null
}

/** 百分数 → 条上位置（0–100，单位 %），超过 120% 封顶，负数归零 */
export function barPosition(percent: string | number | null | undefined): number | null {
  const n = toNumber(percent)
  if (n === null) return null
  const clamped = Math.min(Math.max(n, 0), BAR_SCALE_MAX)
  return Math.round((clamped * 1000) / BAR_SCALE_MAX) / 10
}

export function achievementLevel(
  kind: AchievementKind,
  rate: string | number | null | undefined,
  progress?: string | number | null,
): AchievementLevel {
  const r = toNumber(rate)
  if (r === null || kind === 'neutral') return 'neutral'
  const p = toNumber(progress)
  if (kind === 'expense') {
    if (r > 100) return 'bad'
    if (p !== null && r > p + 10) return 'warn'
    return 'neutral'
  }
  // revenue
  if (r < 70) return 'bad'
  if (p !== null && r < p - 10) return 'warn'
  return 'neutral'
}
