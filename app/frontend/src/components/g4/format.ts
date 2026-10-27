/**
 * G4 报表展示格式（只做字符串格式化，不做金额计算，DEC-005）。
 * 与后端导出同一舍入：ROUND_HALF_UP；负号用「−」（U+2212）。
 */
import { formatDecimal, signOf } from '@/utils/decimal'

const minus = (s: string) => s.replace(/^-/, '−')

/** 金额：千分位 2 位小数；空值「—」 */
export function money(v: string | null | undefined, scale = 2): string {
  return minus(formatDecimal(v, scale))
}

/** 带符号金额：正数加「+」 */
export function moneySigned(v: string | null | undefined, scale = 2): string {
  const f = money(v, scale)
  return signOf(v ?? null) === 1 ? `+${f}` : f
}

/** 百分数字符串 → 「90.12%」 */
export function pct(v: string | null | undefined, scale = 2): string {
  const f = money(v, scale)
  return f === '—' ? f : `${f}%`
}

/** 带符号百分比：「+12.0%」 */
export function pctSigned(v: string | null | undefined, scale = 1): string {
  const f = pct(v, scale)
  return signOf(v ?? null) === 1 ? `+${f}` : f
}

/** 百分点差：「+1.25」 */
export function pp(v: string | null | undefined, scale = 2): string {
  return moneySigned(v, scale)
}

/** 有利 / 不利着色：higherBetter 时正数有利 */
export function tone(v: string | null | undefined, higherBetter = true): '' | 'good' | 'bad' {
  const s = signOf(v ?? null)
  if (s === null || s === 0) return ''
  return (s > 0) === higherBetter ? 'good' : 'bad'
}
