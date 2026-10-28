/**
 * 数据分析子模块公用小工具（原工作台 3693–3722 的非 HTML 部分）。
 *
 * 颜色口径（业财分析全部页面统一，「涨红跌绿」）：数值本身或变动方向
 *   正 / 上升 / 偏高 = 红（--danger，同 g5.css .up）；负 / 下降 / 偏低 = 绿（--success，同 .down）；中间档 = 中性；
 *   与指标好坏无关（费用偏高也是红、毛利偏低也是绿）。
 * - hiLo(high)：两档比较（如高于均值），返回表格单元格的内联样式（颜色 + 加粗），
 *   模板里写 :style="hiLo(r.cvr >= cm.cvr)"。
 * - signTrend(v)：按正负号取档；trendStyle(t) / TREND_COLOR[t]：按档取样式 / 颜色。
 */
import { OVERLAP_DASH, coincidentGroups, sameAsEarlier, type LineSeries } from '@/bizfin/charts'
import { fmt } from '@/bizfin/engine'

/** KPI 卡左侧色条色调（原 kpiSimple 的 cls）；'up' / 'down' 为涨红跌绿口径的「最高 / 最低」 */
export type KpiTone = 'fin' | 'biz' | 'warn' | 'bad' | 'good' | 'up' | 'down'

export type Trend = 'up' | 'down' | 'flat'

export const TREND_COLOR: Record<Trend, string> = {
  up: 'var(--danger)',
  down: 'var(--success)',
  flat: 'var(--fg-2)',
}

export function signTrend(v: number): Trend {
  return v > 0 ? 'up' : v < 0 ? 'down' : 'flat'
}

export function trendStyle(t: Trend): { color: string; fontWeight: number } {
  return { color: TREND_COLOR[t], fontWeight: 700 }
}

export function hiLo(high: boolean): { color: string; fontWeight: number } {
  return trendStyle(high ? 'up' : 'down')
}

/** 折线图图例项：每条线画线型短线；与前面序列整段重合的序列用 OVERLAP_DASH（与 lineChart 自动叠画的虚线一致） */
export function lineLegend(series: LineSeries[]): { name: string; color: string; dash: string }[] {
  const same = sameAsEarlier(series)
  return series.map((s, i) => ({ name: s.name ?? '', color: s.color, dash: s.dash || (same[i] != null ? OVERLAP_DASH : '') }))
}

/**
 * 重合线说明（无重合时返回空串），与 lineChart 的合并末端标签对应，如
 * 「Home Depot 与 Lowe's 逐月数值相同，两线重合（Lowe's 以虚线叠画），末端标签合并为「Home Depot / Lowe's 均为 1.88%」」
 */
export function overlapNote(series: LineSeries[], dec: number, unit = ''): string {
  return coincidentGroups(series).map((g) => {
    const first = series.find((s) => s.name === g[0])
    const last = first && first.values.length ? fmt(first.values[first.values.length - 1], dec) + unit : ''
    return g.join(' 与 ') + ' 逐月数值相同，' + (g.length === 2 ? '两' : g.length + ' ') + '线重合（' + g.slice(1).join('、') +
      ' 以虚线叠画），末端标签合并为「' + g.join(' / ') + ' 均为 ' + last + '」'
  }).join('；')
}
