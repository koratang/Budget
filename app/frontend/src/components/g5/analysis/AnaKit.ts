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
