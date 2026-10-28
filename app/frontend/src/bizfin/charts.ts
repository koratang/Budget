/**
 * SVG 图表工具（由 workbench.html 原样移植，纯手绘、无外部依赖）
 * 所有函数返回 SVG 字符串，页面用 v-html 渲染。
 * 与原代码的差异：插入 SVG 的文本（标签、数值文字）以及来自参数的属性值（颜色、虚线样式等）一律经 esc 转义，
 * 因此调用方传入原始文本即可，不要预先转义。
 */
import { C, PAL, esc, fmt, healthColor } from './engine'

export interface TxtOpts {
  size?: number
  fill?: string
  anchor?: 'start' | 'middle' | 'end'
  weight?: number
}
export interface BarItem {
  label: string
  value: number
  target?: number | null
  color?: string
}
export interface BarOpts {
  w?: number
  h?: number
  bw?: number
  dec?: number
}
export interface HBarItem {
  label: string
  value: number
  target?: number | null
  color?: string
  text?: string | null
  tcolor?: string
  bold?: boolean
}
export interface HBarOpts {
  rowH?: number
  w?: number
  labelW?: number
  rightW?: number
  signed?: boolean
}
export interface ComboLine {
  values: number[]
  color: string
}
export interface SizeOpts {
  w?: number
  h?: number
}
export interface LineSeries {
  name?: string
  values: number[]
  color: string
  axis?: 1 | 2
  dash?: string
  dec?: number
  width?: number
}
export interface LineOpts {
  w?: number
  h?: number
  dual?: boolean
  endLabel?: boolean
  zero?: boolean
  dec?: number | null
  dec2?: number | null
  dots?: boolean
}
export interface StackSeries {
  name?: string
  values: (number | null | undefined)[]
  color: string
}
export interface StackOpts {
  w?: number
  h?: number
  bw?: number
}
export interface DonutItem {
  label?: string
  value: number
  color?: string
}
export interface DonutOpts {
  size?: number
  centerTop?: string
  centerVal?: string
}
export interface GaugeOpts {
  w?: number
  h?: number
  label?: string
}

export function svg(vb: string, inner: string, style?: string): string {
  return '<svg class="chart" viewBox="' + esc(vb) + '" preserveAspectRatio="xMidYMid meet" ' + (style ? 'style="' + esc(style) + '"' : '') + '>' + inner + '</svg>'
}
export function txt(x: number, y: number, s: string | number, o?: TxtOpts): string {
  o = o || {}
  return '<text x="' + x + '" y="' + y + '" font-size="' + (o.size || 11) + '" fill="' + esc(o.fill || C.text2) + '" text-anchor="' + (o.anchor || 'start') + '" font-weight="' + (o.weight || 400) + '">' + esc(s) + '</text>'
}
export function arcPath(cx: number, cy: number, R: number, r: number, a0: number, a1: number): string {
  const P = (rad: number, a: number): [number, number] => [cx + rad * Math.cos(a), cy + rad * Math.sin(a)]
  const p0 = P(R, a0), p1 = P(R, a1), p2 = P(r, a1), p3 = P(r, a0)
  const laf = (a1 - a0) > Math.PI ? 1 : 0
  return 'M' + p0[0].toFixed(2) + ',' + p0[1].toFixed(2) +
    ' A' + R + ',' + R + ' 0 ' + laf + ' 1 ' + p1[0].toFixed(2) + ',' + p1[1].toFixed(2) +
    ' L' + p2[0].toFixed(2) + ',' + p2[1].toFixed(2) +
    ' A' + r + ',' + r + ' 0 ' + laf + ' 0 ' + p3[0].toFixed(2) + ',' + p3[1].toFixed(2) + ' Z'
}

/* 垂直柱状图（含目标刻度线） */
export function barChart(items: BarItem[], o?: BarOpts): string {
  o = o || {}
  const W = o.w || 560, H = o.h || 260
  const pad = { l: 54, r: 14, t: 18, b: 44 }
  const iw = W - pad.l - pad.r, ih = H - pad.t - pad.b
  const max = (Math.max(...items.map(i => Math.max(i.value, i.target || 0))) || 1) * 1.18
  const step = iw / items.length
  const bw = Math.min(o.bw || 44, step * 0.52)
  let g = ''
  for (let k = 0; k <= 4; k++) {
    const y = pad.t + ih - ih * k / 4
    g += '<line x1="' + pad.l + '" y1="' + y + '" x2="' + (W - pad.r) + '" y2="' + y + '" stroke="' + C.grid + '"/>'
    g += txt(pad.l - 8, y + 3.5, fmt(max * k / 4, 0), { anchor: 'end', size: 10.5, fill: C.text3 })
  }
  const dec = o.dec
  items.forEach(function (it, idx) {
    const cx = pad.l + step * idx + step / 2
    const h = Math.max(1, ih * it.value / max)
    const y = pad.t + ih - h
    const color = it.color || PAL[idx % PAL.length]
    g += '<rect x="' + (cx - bw / 2) + '" y="' + y + '" width="' + bw + '" height="' + h + '" rx="3.5" fill="' + esc(color) + '" opacity=".92"/>'
    g += txt(cx, y - 6, fmt(it.value, dec), { anchor: 'middle', size: 10.5, weight: 700, fill: C.text })
    if (it.target != null) {
      const ty = pad.t + ih - ih * it.target / max
      g += '<line x1="' + (cx - bw / 2 - 6) + '" y1="' + ty + '" x2="' + (cx + bw / 2 + 6) + '" y2="' + ty + '" stroke="' + C.up + '" stroke-width="1.6" stroke-dasharray="4 3"/>'
    }
    g += txt(cx, H - pad.b + 18, it.label, { anchor: 'middle', size: 10.5, fill: C.text2 })
  })
  return svg('0 0 ' + W + ' ' + H, g)
}

/* 水平条形图（排行 / 达成率）；o.signed = true 时支持带正负号的居中条形 */
export function hBarChart(items: HBarItem[], o?: HBarOpts): string {
  o = o || {}
  const rowH = o.rowH || 28, W = o.w || 560
  const padL = o.labelW || 120, padR = o.rightW || 74
  const H = 16 + items.length * rowH
  const iw = W - padL - padR
  let g = ''
  if (o.signed) {
    const posMax = Math.max(...items.map(function (i) { return Math.max(0, i.value) }).concat([0])) || 1
    const negMax = Math.abs(Math.min(...items.map(function (i) { return Math.min(0, i.value) }).concat([0]))) || 1
    const span = posMax + negMax || 1
    const sc = iw / span
    const zeroX = padL + negMax * sc
    /* 零轴 */
    g += '<line x1="' + zeroX + '" y1="6" x2="' + zeroX + '" y2="' + (H - 10) + '" stroke="' + C.line + '" stroke-width="1.2"/>'
    items.forEach(function (it, idx) {
      const y = 8 + idx * rowH + 4
      const bh = rowH - 14
      const v = it.value
      const w = Math.max(2, Math.abs(v) * sc)
      const x = v >= 0 ? zeroX : zeroX - w
      g += txt(padL - 10, y + bh / 2 + 4, it.label, { anchor: 'end', size: 11, fill: C.text2, weight: it.bold ? 600 : 400 })
      g += '<rect x="' + Math.min(x, zeroX) + '" y="' + y + '" width="' + Math.max(w, 2) + '" height="' + bh + '" rx="3" fill="' + esc(it.color || C.biz) + '" opacity=".9"/>'
      const tx = v >= 0 ? (zeroX + w + 6) : (zeroX - w - 6)
      g += txt(tx, y + bh / 2 + 4, (it.text != null ? it.text : fmt(v, 1)), { anchor: v >= 0 ? 'start' : 'end', size: 11, weight: 700, fill: it.tcolor || C.text })
    })
    return svg('0 0 ' + W + ' ' + H, g)
  }
  const max = (Math.max(...items.map(i => i.value)) || 1) * 1.02
  items.forEach(function (it, idx) {
    const y = 8 + idx * rowH + 4
    const bh = rowH - 14
    const w = Math.max(3, iw * it.value / max)
    g += txt(padL - 10, y + bh / 2 + 4, it.label, { anchor: 'end', size: 11, fill: C.text2, weight: it.bold ? 600 : 400 })
    g += '<rect x="' + padL + '" y="' + y + '" width="' + iw + '" height="' + bh + '" rx="3" fill="#f2f5fa"/>'
    g += '<rect x="' + padL + '" y="' + y + '" width="' + w + '" height="' + bh + '" rx="3" fill="' + esc(it.color || C.biz) + '" opacity=".9"/>'
    if (it.target != null) {
      const tx = padL + Math.min(iw, iw * it.target / max)
      g += '<line x1="' + tx + '" y1="' + (y - 2) + '" x2="' + tx + '" y2="' + (y + bh + 2) + '" stroke="' + C.up + '" stroke-width="1.5" stroke-dasharray="3 2.5"/>'
    }
    g += txt(W - padR + 8, y + bh / 2 + 4, (it.text != null ? it.text : fmt(it.value, 1)), { anchor: 'start', size: 11, weight: 700, fill: it.tcolor || C.text })
  })
  return svg('0 0 ' + W + ' ' + H, g)
}

/* 组合图：柱（金额）+ 折线（比率） */
export function comboChart(labels: string[], bars: number[], lines: ComboLine[], o?: SizeOpts): string {
  o = o || {}
  const W = o.w || 640, H = o.h || 280
  const pad = { l: 58, r: 60, t: 20, b: 40 }
  const iw = W - pad.l - pad.r, ih = H - pad.t - pad.b
  const maxB = (Math.max(...bars) || 1) * 1.22
  const allL: number[] = []
  lines.forEach(l => l.values.forEach(v => allL.push(v)))
  const minL = Math.min(...allL), maxL = Math.max(...allL)
  const span = (maxL - minL) || 1
  const lo = minL - span * 0.3, hi = maxL + span * 0.35
  let g = ''
  for (let k = 0; k <= 4; k++) {
    const y = pad.t + ih - ih * k / 4
    g += '<line x1="' + pad.l + '" y1="' + y + '" x2="' + (W - pad.r) + '" y2="' + y + '" stroke="' + C.grid + '"/>'
    g += txt(pad.l - 8, y + 3.5, fmt(maxB * k / 4, 0), { anchor: 'end', size: 10.5, fill: C.text3 })
    g += txt(W - pad.r + 8, y + 3.5, fmt(lo + (hi - lo) * k / 4, 1) + '%', { anchor: 'start', size: 10.5, fill: C.text3 })
  }
  const step = iw / labels.length
  const bw = Math.min(38, step * 0.44)
  bars.forEach(function (v, idx) {
    const cx = pad.l + step * idx + step / 2
    const h = Math.max(1, ih * v / maxB)
    g += '<rect x="' + (cx - bw / 2) + '" y="' + (pad.t + ih - h) + '" width="' + bw + '" height="' + h + '" rx="3" fill="#bfd5fb"/>'
    g += txt(cx, pad.t + ih - h - 6, fmt(v, 0), { anchor: 'middle', size: 10, fill: C.text2 })
  })
  const PT = (v: number, i: number): [number, number] => [pad.l + step * i + step / 2, pad.t + ih - ih * (v - lo) / (hi - lo)]
  lines.forEach(function (L) {
    let d = ''
    L.values.forEach(function (v, i) { const p = PT(v, i); d += (i ? ' L' : 'M') + p[0].toFixed(1) + ',' + p[1].toFixed(1) })
    g += '<path d="' + d + '" fill="none" stroke="' + esc(L.color) + '" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>'
    L.values.forEach(function (v, i) {
      const p = PT(v, i)
      g += '<circle cx="' + p[0] + '" cy="' + p[1] + '" r="3.2" fill="#fff" stroke="' + esc(L.color) + '" stroke-width="2"/>'
    })
  })
  labels.forEach(function (lb, i) {
    g += txt(pad.l + step * i + step / 2, H - pad.b + 18, lb, { anchor: 'middle', size: 10.5, fill: C.text2 })
  })
  return svg('0 0 ' + W + ' ' + H, g)
}

/* 多序列月度趋势折线图
   series: [{name, values:[…], color, axis:1|2, dash?, dec?}]
   o.dual = true 时 axis:2 的序列改走右轴刻度（用于量纲不同的双指标同图） */
export function lineChart(labels: string[], series: LineSeries[], o?: LineOpts): string {
  const opt: LineOpts = o || {}
  const dual = !!opt.dual
  const W = opt.w || 640, H = opt.h || 268
  const pad = { l: 56, r: dual ? 58 : (opt.endLabel ? 46 : 20), t: 20, b: 40 }
  const iw = W - pad.l - pad.r, ih = H - pad.t - pad.b
  const n = labels.length
  const scope = function (list: LineSeries[]): { lo: number; hi: number } {
    const all: number[] = []
    list.forEach(function (s) { s.values.forEach(function (v) { all.push(v) }) })
    if (!all.length) return { lo: 0, hi: 1 }
    let mn = Math.min(...all)
    const mx = Math.max(...all)
    if (opt.zero) mn = Math.min(0, mn)
    const sp = (mx - mn) || Math.abs(mx) || 1
    return { lo: mn - sp * 0.20, hi: mx + sp * 0.26 }
  }
  const A = scope(series.filter(function (s) { return s.axis !== 2 }))
  const B = dual ? scope(series.filter(function (s) { return s.axis === 2 })) : A
  const X = function (i: number): number { return n > 1 ? pad.l + iw * i / (n - 1) : pad.l + iw / 2 }
  const Y = function (v: number, r: { lo: number; hi: number }): number { return pad.t + ih - ih * (v - r.lo) / ((r.hi - r.lo) || 1) }
  const dec1 = opt.dec == null ? 1 : opt.dec, dec2 = opt.dec2 == null ? dec1 : opt.dec2
  let g = ''
  for (let k = 0; k <= 4; k++) {
    const y = pad.t + ih - ih * k / 4
    g += '<line x1="' + pad.l + '" y1="' + y + '" x2="' + (W - pad.r) + '" y2="' + y + '" stroke="' + C.grid + '"/>'
    g += txt(pad.l - 8, y + 3.5, fmt(A.lo + (A.hi - A.lo) * k / 4, dec1), { anchor: 'end', size: 10.5, fill: C.text3 })
    if (dual) g += txt(W - pad.r + 8, y + 3.5, fmt(B.lo + (B.hi - B.lo) * k / 4, dec2), { anchor: 'start', size: 10.5, fill: C.text3 })
  }
  labels.forEach(function (lb, i) { g += txt(X(i), H - pad.b + 18, lb, { anchor: 'middle', size: 10.5, fill: C.text2 }) })
  series.forEach(function (s) {
    const r = (s.axis === 2 && dual) ? B : A
    const d = s.values.map(function (v, i) { return (i ? 'L' : 'M') + X(i).toFixed(1) + ',' + Y(v, r).toFixed(1) }).join(' ')
    g += '<path d="' + d + '" fill="none" stroke="' + esc(s.color) + '" stroke-width="' + (s.width || 2.3) + '"' +
      (s.dash ? ' stroke-dasharray="' + esc(s.dash) + '"' : '') + ' stroke-linecap="round" stroke-linejoin="round"/>'
    if (opt.dots !== false) {
      s.values.forEach(function (v, i) {
        g += '<circle cx="' + X(i).toFixed(1) + '" cy="' + Y(v, r).toFixed(1) + '" r="2.9" fill="#fff" stroke="' + esc(s.color) + '" stroke-width="1.8"/>'
      })
    }
    if (opt.endLabel) {
      const lv = s.values[s.values.length - 1]
      g += txt(X(n - 1) + 7, Y(lv, r) + 4, fmt(lv, s.dec == null ? dec1 : s.dec), { size: 10.5, weight: 700, fill: s.color })
    }
  })
  return svg('0 0 ' + W + ' ' + H, g)
}

/* 占比月度趋势：100% 堆叠柱
   series: [{name, values:[…], color}]，values 可传绝对值，函数内部按列归一化 */
export function stack100(labels: string[], series: StackSeries[], o?: StackOpts): string {
  o = o || {}
  const W = o.w || 640, H = o.h || 258
  const pad = { l: 52, r: 16, t: 18, b: 42 }
  const iw = W - pad.l - pad.r, ih = H - pad.t - pad.b
  const n = labels.length, step = iw / n
  const bw = Math.min(o.bw || 42, step * 0.62)
  const tots: number[] = []
  for (let i = 0; i < n; i++) {
    let s = 0
    series.forEach(function (se) { s += Math.max(0, se.values[i] || 0) })
    tots.push(s || 1)
  }
  let g = ''
  for (let k = 0; k <= 4; k++) {
    const y = pad.t + ih - ih * k / 4
    g += '<line x1="' + pad.l + '" y1="' + y + '" x2="' + (W - pad.r) + '" y2="' + y + '" stroke="' + C.grid + '"/>'
    g += txt(pad.l - 8, y + 3.5, (k * 25) + '%', { anchor: 'end', size: 10.5, fill: C.text3 })
  }
  for (let i = 0; i < n; i++) {
    const cx = pad.l + step * i + step / 2
    let acc = 0
    series.forEach(function (se) {
      const v = Math.max(0, se.values[i] || 0) / tots[i] * 100
      const h = ih * v / 100
      const y = pad.t + ih - ih * (acc + v) / 100
      g += '<rect x="' + (cx - bw / 2).toFixed(1) + '" y="' + y.toFixed(2) + '" width="' + bw +
        '" height="' + Math.max(0.4, h).toFixed(2) + '" fill="' + esc(se.color) + '" opacity=".93"/>'
      if (v >= 9) g += txt(cx, y + h / 2 + 3.5, fmt(v, 0) + '%', { anchor: 'middle', size: 9.5, weight: 700, fill: '#fff' })
      acc += v
    })
    g += txt(cx, H - pad.b + 18, labels[i], { anchor: 'middle', size: 10.5, fill: C.text2 })
  }
  return svg('0 0 ' + W + ' ' + H, g)
}

/* 环形图 */
export function donutChart(items: DonutItem[], o?: DonutOpts): string {
  o = o || {}
  const S = o.size || 216, cx = S / 2, cy = S / 2, R = S / 2 - 6, r = R * 0.6
  const total = (items.reduce((a, b) => a + b.value, 0)) || 1
  let a0 = -Math.PI / 2, g = ''
  items.forEach(function (it, idx) {
    const a1 = a0 + it.value / total * Math.PI * 2
    g += '<path d="' + arcPath(cx, cy, R, r, a0, a1) + '" fill="' + esc(it.color || PAL[idx % PAL.length]) + '" opacity=".93"/>'
    a0 = a1
  })
  g += '<circle cx="' + cx + '" cy="' + cy + '" r="' + (r - 1) + '" fill="#fff"/>'
  g += txt(cx, cy - 2, o.centerTop || '', { anchor: 'middle', size: 10.5, fill: C.text3 })
  g += txt(cx, cy + 17, o.centerVal || '', { anchor: 'middle', size: 17, weight: 800, fill: C.text })
  return svg('0 0 ' + S + ' ' + S, g)
}

/* 半环仪表 */
export function gauge(value: number, o?: GaugeOpts): string {
  o = o || {}
  const W = o.w || 220, H = o.h || 122
  const cx = W / 2, cy = H - 12, R = Math.min(W / 2 - 12, 86), r = R - 13
  const v = Math.max(0, Math.min(130, value))
  const a1 = Math.PI + Math.PI * (v / 130)
  const color = healthColor(v)
  const P = (rad: number, a: number): [number, number] => [cx + rad * Math.cos(a), cy + rad * Math.sin(a)]
  const s = P(R, Math.PI), e = P(R, Math.PI * 2), i0 = P(r, Math.PI), j0 = P(r, Math.PI * 2), vp = P(R, a1), wp = P(r, a1)
  let g = ''
  g += '<path d="M' + s[0] + ',' + s[1] + ' A' + R + ',' + R + ' 0 0 1 ' + e[0] + ',' + e[1] + ' L' + j0[0] + ',' + j0[1] + ' A' + r + ',' + r + ' 0 0 0 ' + i0[0] + ',' + i0[1] + ' Z" fill="#eef2f8"/>'
  if (v > 0.5) {
    g += '<path d="M' + s[0] + ',' + s[1] + ' A' + R + ',' + R + ' 0 0 1 ' + vp[0].toFixed(2) + ',' + vp[1].toFixed(2) + ' L' + wp[0].toFixed(2) + ',' + wp[1].toFixed(2) + ' A' + r + ',' + r + ' 0 0 0 ' + i0[0] + ',' + i0[1] + ' Z" fill="' + color + '" opacity=".92"/>'
  }
  g += txt(cx, cy - 24, fmt(value, 1) + '%', { anchor: 'middle', size: 23, weight: 800, fill: color })
  g += txt(cx, cy - 7, o.label || '综合达成率', { anchor: 'middle', size: 10.5, fill: C.text3 })
  return svg('0 0 ' + W + ' ' + H, g)
}

/* 导航图标（<svg viewBox="0 0 24 24"> 的内部图形，键与 NAV / ANA_NAV 的 icon 字段对应；常量，无用户输入） */
export const ICONS: Record<string, string> = {
  dashboard: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
  finance: '<path d="M4 20V10M9.5 20V4M15 20v-7M20.5 20V7"/>',
  business: '<path d="M3 20h18"/><rect x="5" y="11" width="3.4" height="6" rx="1"/><rect x="10.3" y="7" width="3.4" height="10" rx="1"/><rect x="15.6" y="13" width="3.4" height="4" rx="1"/>',
  linkage: '<circle cx="6" cy="6" r="2.6"/><circle cx="18" cy="6" r="2.6"/><circle cx="12" cy="18" r="2.6"/><path d="M8.4 7.4 11 15.4M15.6 7.4 13 15.4M8.6 6h6.8"/>',
  analysis: '<circle cx="12" cy="12" r="9"/><path d="M12 3v9l7 4"/>',
  advice: '<path d="M9 18h6M10 21h4"/><path d="M12 3a6 6 0 0 0-3.6 10.8c.6.5 1 1.2 1.1 2h5c.1-.8.5-1.5 1.1-2A6 6 0 0 0 12 3z"/>',
  keywork: '<rect x="5" y="3" width="14" height="18" rx="1.5"/><path d="M9 7h6M9 11h6M9 15h4"/><path d="M9.5 18.2 11 19.6l3-3.2"/>',
  data: '<ellipse cx="12" cy="6" rx="8" ry="3"/><path d="M4 6v6c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6"/>',
  policy: '<path d="M6 3h9l4 4v14H6z"/><path d="M15 3v4h4"/><path d="M9 12h7M9 16h7"/>',
}
