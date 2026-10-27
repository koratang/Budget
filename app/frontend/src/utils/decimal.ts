/**
 * 十进制字符串的展示格式化（DEC-005：前端不做金额计算，只做字符串层面的千分位与小数位处理，
 * 不经过浮点数，避免精度误差）。
 */

const DECIMAL_RE = /^([+-])?(\d*)(?:\.(\d*))?$/

/** 去掉粘贴/输入中的空白、千分位逗号与人民币符号；空串返回 null */
export function normalizeInput(raw: unknown, opts: { percent?: boolean } = {}): string | null {
  if (raw === null || raw === undefined) return null
  let s = String(raw).trim().replace(/[\s,，¥￥]/g, '')
  if (opts.percent) s = s.replace(/%$/, '')
  return s === '' ? null : s
}

/** 是否为合法的十进制字符串 */
export function isDecimalString(s: string): boolean {
  const m = DECIMAL_RE.exec(s)
  return !!m && (m[2] !== '' || (m[3] ?? '') !== '')
}

/** 符号：-1 / 0 / 1；无法解析返回 null */
export function signOf(value: string | null | undefined): -1 | 0 | 1 | null {
  if (value === null || value === undefined) return null
  const s = String(value).trim().replace(/,/g, '')
  if (!isDecimalString(s)) return null
  const m = DECIMAL_RE.exec(s)!
  const digits = (m[2] ?? '') + (m[3] ?? '')
  if (/^0*$/.test(digits)) return 0
  return m[1] === '-' ? -1 : 1
}

/** 对无符号的整数位 + 小数位按 scale 做四舍五入（字符串进位） */
function roundDigits(intPart: string, frac: string, scale: number): [string, string] {
  if (frac.length <= scale) return [intPart, frac.padEnd(scale, '0')]
  const keep = intPart + frac.slice(0, scale)
  const roundUp = frac.charCodeAt(scale) - 48 >= 5
  let digits = keep
  if (roundUp) {
    const arr = keep.split('')
    let i = arr.length - 1
    while (i >= 0) {
      if (arr[i] === '9') {
        arr[i] = '0'
        i--
      } else {
        arr[i] = String.fromCharCode(arr[i].charCodeAt(0) + 1)
        break
      }
    }
    digits = (i < 0 ? '1' : '') + arr.join('')
  }
  const cut = digits.length - scale
  return [digits.slice(0, cut) || '0', digits.slice(cut)]
}

/**
 * "1234567.891" → "1,234,567.89"；无法解析的原样返回；null/空 → 「—」
 */
export function formatDecimal(value: string | null | undefined, scale = 2, empty = '—'): string {
  if (value === null || value === undefined || String(value).trim() === '') return empty
  const s = String(value).trim().replace(/,/g, '')
  const m = DECIMAL_RE.exec(s)
  if (!m || !isDecimalString(s)) return String(value)
  const [intRaw, frac] = roundDigits((m[2] ?? '').replace(/^0+(?=\d)/, '') || '0', m[3] ?? '', scale)
  const intPart = intRaw.replace(/^0+(?=\d)/, '')
  const grouped = intPart.replace(/\B(?=(\d{3})+(?!\d))/g, ',')
  const isZero = /^0*$/.test(intPart + frac)
  const sign = m[1] === '-' && !isZero ? '-' : ''
  return sign + grouped + (scale > 0 ? '.' + frac : '')
}

/** 百分数字符串展示："12.5" → "12.5%"（scale 默认 1 位） */
export function formatPercent(value: string | null | undefined, scale = 1, empty = '—'): string {
  const f = formatDecimal(value, scale, empty)
  return f === empty ? f : f + '%'
}
