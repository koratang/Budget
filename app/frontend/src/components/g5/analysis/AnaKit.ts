/**
 * 数据分析子模块公用小工具（原工作台 3693–3722 的非 HTML 部分）。
 *
 * goodBad(good, goodTone, badTone)：对应原 goodBad(v, good, goodColor, badColor)，
 *   返回表格单元格的内联样式对象（颜色 + 加粗），在模板里写 :style="goodBad(r.cvr >= cm.cvr, 'good', 'warn')"。
 *   原配色常量与色调对应：G（绿 = 优）→ 'good'；R（红 = 劣）→ 'bad'；Y（黄）→ 'warn'，颜色取平台令牌。
 */
/** KPI 卡左侧色条色调（原 kpiSimple 的 cls） */
export type KpiTone = 'fin' | 'biz' | 'warn' | 'bad' | 'good'

export type GbTone = 'good' | 'warn' | 'bad'

const TONE_COLOR: Record<GbTone, string> = {
  good: 'var(--success)',
  warn: 'var(--warn)',
  bad: 'var(--danger)',
}

export function goodBad(good: boolean, goodTone: GbTone, badTone: GbTone): { color: string; fontWeight: number } {
  return { color: TONE_COLOR[good ? goodTone : badTone], fontWeight: 700 }
}
