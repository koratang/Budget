/**
 * charts.ts 坐标轴刻度与末端标签避让的单元测试（纯渲染改进，不涉及任何数据计算）。
 * 场景取自 PAGE-F15-05：头程发货量（吨，小量级）、渠道订单量（单，全为非负）、管理费用组合图。
 */
import { describe, expect, it } from 'vitest'
import { HALF_W, OVERLAP_DASH, coincidentGroups, comboChart, fontScale, hBarChart, lineChart, niceScale, niceScaleN, sameAsEarlier, spreadLabels, stack100 } from './charts'
import { PAL } from './engine'

/** 取左轴刻度文字（lineChart 左轴标签 x = pad.l − 8 = 48，右对齐） */
function leftTicks(svgStr: string): string[] {
  return [...svgStr.matchAll(/<text x="48" y="[^"]+" [^>]*text-anchor="end"[^>]*>([^<]*)<\/text>/g)].map((m) => m[1])
}
/** 取末端标签的基线 y（x = 最后一个点 + 7） */
function endLabelYs(svgStr: string, x: number): number[] {
  const re = new RegExp('<text x="' + x + '" y="([^"]+)"[^>]*font-weight="700">', 'g')
  return [...svgStr.matchAll(re)].map((m) => Number(m[1]))
}

describe('niceScale：整齐步长（1 / 2 / 2.5 / 5 × 10^n）', () => {
  it('[0.5, 1, 1.5, 2, 3] 的刻度无重复、无 −0，步长 1 / 0.5 之类的整齐值', () => {
    const s = niceScale(0, 3.65)
    expect(s.step).toBe(1)
    expect(s.ticks).toEqual([0, 1, 2, 3, 4])
    expect(s.dec).toBe(0)
    expect(s.ticks.some((t) => Object.is(t, -0))).toBe(false)
  })

  it('小数步长的小数位随步长决定，浮点误差被消除', () => {
    const s = niceScale(0.1, 0.7)
    expect([0.1, 0.2, 0.25, 0.5]).toContain(s.step)
    s.ticks.forEach((t) => expect(String(t).length).toBeLessThanOrEqual(6))
    expect(niceScale(0, 1.1, 4).step).toBe(0.5)
    expect(niceScale(0, 1.1, 4).dec).toBe(1)
    expect(niceScale(0, 110, 4).step).toBe(50)
    expect(niceScale(0, 2.2, 4).step).toBe(1)
    expect(niceScale(10, 21, 4).step).toBe(5)
    expect(niceScale(0, 9, 4).step).toBe(2.5)
    expect(niceScale(0, 9, 4).dec).toBe(1)
  })

  it('跨零的范围：0 是刻度且不是 −0', () => {
    const s = niceScale(-0.3, 0.9)
    expect(s.ticks).toContain(0)
    expect(s.ticks.some((t) => Object.is(t, -0))).toBe(false)
  })

  it('niceScaleN：恰好 n 个间隔、覆盖数据范围（双轴网格线对齐）', () => {
    const s = niceScaleN(2.34, 2.67, 4)
    expect(s.ticks).toHaveLength(5)
    expect(s.lo).toBeLessThanOrEqual(2.34)
    expect(s.hi).toBeGreaterThanOrEqual(2.67)
  })
})

describe('lineChart 纵轴', () => {
  it('头程发货量 [0.5, 1, 1.5, 2, 3] 吨：刻度文字不重复、不出现 −0，下限为 0', () => {
    const out = lineChart(['01月', '02月', '03月', '04月', '05月'], [{ name: '燕文·英国', values: [0.5, 1, 1.5, 2, 3], color: '#2563eb' }], { dec: 0 })
    const ticks = leftTicks(out)
    expect(ticks.length).toBeGreaterThanOrEqual(3)
    expect(new Set(ticks).size).toBe(ticks.length)
    expect(ticks).not.toContain('-0')
    expect(ticks.some((t) => t.startsWith('-') || t.startsWith('−'))).toBe(false)
    expect(ticks[0]).toBe('0')
  })

  it('渠道订单量全为非负：纵轴下限不低于 0（不再出现 −409 之类的负刻度）', () => {
    const out = lineChart(['01月', '02月', '03月'], [
      { name: 'Amazon', values: [3120, 2980, 3405], color: '#2563eb' },
      { name: '独立站', values: [420, 515, 488], color: '#0d9488' },
    ], { dec: 0, endLabel: true })
    const ticks = leftTicks(out).map((t) => Number(t.replace(/,/g, '')))
    expect(Math.min(...ticks)).toBe(0)
    expect(new Set(ticks).size).toBe(ticks.length)
  })

  it('含负值的数据（如净利润率）仍可出现负刻度', () => {
    const out = lineChart(['01月', '02月'], [{ name: '净利润率', values: [-2.4, 3.1], color: '#2563eb' }])
    expect(leftTicks(out).some((t) => t.startsWith('-'))).toBe(true)
  })
})

describe('末端标签纵向避让', () => {
  it('spreadLabels：按 y 排序后相邻间距 ≥ gap，保持原相对顺序，且不越界', () => {
    const ys = [100, 101, 99.5, 160]
    const out = spreadLabels(ys, 12, 20, 220)
    const sorted = out.slice().sort((a, b) => a - b)
    for (let i = 1; i < sorted.length; i++) expect(sorted[i] - sorted[i - 1]).toBeGreaterThanOrEqual(12 - 1e-9)
    expect(out[2]).toBeLessThan(out[0])
    expect(out[0]).toBeLessThan(out[1])
    expect(out[3]).toBe(160)
    out.forEach((y) => { expect(y).toBeGreaterThanOrEqual(20); expect(y).toBeLessThanOrEqual(220) })
  })

  it('spreadLabels：贴底的标签整体上移，不超出下界', () => {
    const out = spreadLabels([218, 219, 220], 12, 20, 220)
    expect(Math.max(...out)).toBeLessThanOrEqual(220)
    expect(out.slice().sort((a, b) => a - b)).toEqual([196, 208, 220])
  })

  it('lineChart：渠道仓储成本占比末端 3.08 / 3.05 两个标签不重叠', () => {
    const out = lineChart(['07月', '08月', '09月'], [
      { name: 'Amazon', values: [2.9, 3.0, 3.08], color: '#2563eb' },
      { name: 'Wayfair', values: [2.95, 3.01, 3.05], color: '#0d9488' },
      { name: '独立站', values: [1.2, 1.4, 1.77], color: '#7c3aed' },
    ], { w: 540, h: 240, endLabel: true, dec: 2 })
    expect(out).toContain('>3.08<')
    expect(out).toContain('>3.05<')
    const ys = endLabelYs(out, 540 - 46 + 7).sort((a, b) => a - b)
    expect(ys).toHaveLength(3)
    for (let i = 1; i < ys.length; i++) expect(ys[i] - ys[i - 1]).toBeGreaterThanOrEqual(12 - 0.05)
  })

  it('lineChart：同值且重叠的末端标签合并为一个，写明「A / B 均为 x」并用中性色', () => {
    const out = lineChart(['08月', '09月'], [
      { name: '美森·美西', values: [6.1, 6.47], color: '#2563eb' },
      { name: '美森·美东', values: [6.2, 6.47], color: '#0d9488' },
    ], { endLabel: true, dec: 2 })
    expect(out.match(/6\.47</g)).toHaveLength(1)
    const label = out.match(/<text [^>]*fill="([^"]+)"[^>]*>美森·美西 \/ 美森·美东 均为 6\.47<\/text>/)
    expect(label).not.toBeNull()
    expect(label?.[1]).not.toBe('#2563eb')
    expect(label?.[1]).not.toBe('#0d9488')
  })

  it('lineChart：整段重合的序列自动改画虚线（透出下层线色），合并标签带单位，右边距容纳长标签', () => {
    const series = [
      { name: 'Amazon', values: [2.4, 2.57, 2.01], color: '#2563eb' },
      { name: 'Home Depot', values: [2.2, 2.39, 1.876], color: '#7c3aed' },
      { name: "Lowe's", values: [2.2, 2.39, 1.876 + 1e-15], color: '#e08600' },
    ]
    expect(sameAsEarlier(series)).toEqual([null, null, 1])
    expect(coincidentGroups(series)).toEqual([['Home Depot', "Lowe's"]])
    const out = lineChart(['07月', '08月', '09月'], series, { w: 860, endLabel: true, dec: 2, endUnit: '%' }).replace(/&#39;/g, "'")
    expect(out).toContain('stroke="#e08600" stroke-width="2.3" stroke-dasharray="' + OVERLAP_DASH + '"')
    expect(out).not.toContain('stroke="#7c3aed" stroke-width="2.3" stroke-dasharray')
    expect(out).toContain(">Home Depot / Lowe's 均为 1.88%<")
    expect(out).toContain('>2.01%<')
    /* 标签起点 x + 估算宽度不超出画布 */
    const m = out.match(/<text x="([\d.]+)"[^>]*>Home Depot \/ Lowe's 均为 1\.88%<\/text>/)
    expect(Number(m?.[1])).toBeLessThan(860 - 130)
  })
})

describe('字号随画布宽度自适应（半宽卡片）', () => {
  /** 取 SVG 内全部 font-size */
  const sizes = (out: string): number[] => [...out.matchAll(/font-size="([\d.]+)"/g)].map((m) => Number(m[1]))
  /** 半宽卡片在 1280 视口下的渲染宽度约 462px（PAGE-F15-05 截图实测） */
  const RENDER_W = 462

  it('fontScale：全宽画布（≥ 576）为 1，HALF_W 为 1.2，上限 1.35', () => {
    expect(fontScale(640)).toBe(1)
    expect(fontScale(860)).toBe(1)
    expect(fontScale(HALF_W)).toBeCloseTo(1.2, 5)
    expect(fontScale(200)).toBe(1.35)
  })

  it('HALF_W 画布的折线 / 组合 / 堆叠 / 条形图，渲染到半宽卡片后最小字号 ≥ 11px', () => {
    const labels = ['01月', '02月', '03月', '04月', '05月', '06月', '07月', '08月', '09月']
    const vals = [19, 16, 24, 28, 30, 32, 33, 36, 27]
    const outs = [
      lineChart(labels, [{ name: '人力资源部', values: vals, color: '#0d9488' }], { w: HALF_W, endLabel: true }),
      comboChart(labels, vals, [{ color: '#0d9488', values: vals.map((x) => x / 10) }], { w: HALF_W }),
      stack100(labels, [{ name: '新品', values: vals, color: '#2563eb' }, { name: '老品', values: vals, color: '#94a3b8' }], { w: HALF_W }),
      hBarChart([{ label: '人力资源部', value: 49.2 }, { label: '财务部', value: 41.8 }], { w: HALF_W }),
    ]
    outs.forEach((out) => {
      expect(out).toContain('viewBox="0 0 480 ')
      expect(Math.min(...sizes(out)) * RENDER_W / HALF_W).toBeGreaterThanOrEqual(11)
    })
  })

  it('全宽默认画布字号不变（10.5 号刻度）', () => {
    const out = lineChart(['01月', '02月'], [{ name: 'Amazon', values: [1, 2], color: '#2563eb' }])
    expect(sizes(out)).toContain(10.5)
  })
})

describe('comboChart', () => {
  it('柱色可配置，默认保持 #bfd5fb', () => {
    const labels = ['01月', '02月']
    expect(comboChart(labels, [26.1, 24.8], [{ color: '#0d9488', values: [2.5, 2.4] }])).toContain('fill="#bfd5fb"')
    expect(comboChart(labels, [26.1, 24.8], [{ color: '#0d9488', values: [2.5, 2.4] }], { barColor: '#93c5fd' })).toContain('fill="#93c5fd"')
  })

  it('柱顶数值与折线点冲突时移开（数值文字框不与任何折线点相交）', () => {
    /* 构造：费用率走势与发生额同形，折线点正好落在柱顶附近 */
    const bars = [20, 22, 25, 27.4, 27.3, 24, 26, 28, 26.5]
    const rates = [2.40, 2.45, 2.52, 2.60, 2.60, 2.50, 2.55, 2.62, 2.56]
    const labels = ['01月', '02月', '03月', '04月', '05月', '06月', '07月', '08月', '09月']
    const out = comboChart(labels, bars, [{ color: '#0d9488', values: rates }], { h: 268 })
    const circles = [...out.matchAll(/<circle cx="([^"]+)" cy="([^"]+)"/g)].map((m) => ({ x: Number(m[1]), y: Number(m[2]) }))
    const vals = [...out.matchAll(/<text x="([^"]+)" y="([^"]+)" font-size="10" [^>]*>([^<]*)<\/text>/g)].map((m) => ({ x: Number(m[1]), y: Number(m[2]) }))
    expect(vals).toHaveLength(bars.length)
    /* 场景确有冲突：至少一个数值不在默认位置（柱顶上方 6px） */
    const tops = [...out.matchAll(/<rect x="[^"]+" y="([^"]+)"/g)].map((m) => Number(m[1]))
    expect(vals.some((v, i) => Math.abs(v.y - (tops[i] - 6)) > 0.01)).toBe(true)
    vals.forEach((v) => {
      circles.filter((c) => Math.abs(c.x - v.x) < 1).forEach((c) => {
        const overlap = c.y + 4.5 > v.y - 10 && c.y - 4.5 < v.y + 2
        expect(overlap).toBe(false)
      })
    })
  })

  it('lineChart：合并标签过长时改写为「N 线均为 x」，绘图区宽度不被挤占（右边距 ≤ 32%）', () => {
    const v = [29.1, 29.2, 29.3, 29.5]
    const names = ['Amazon', 'Wayfair', 'HomeDepot', "Lowe's"]
    const out = lineChart(['01月', '02月', '03月', '04月'], names.map((name, i) => ({ name, color: PAL[i], values: v })),
      { w: HALF_W, h: 290, dec: 1, endLabel: true, endUnit: '%' })
    expect(out).toContain('>4 线均为 29.5%<')
    const xs = [...out.matchAll(/<text x="([\d.]+)"[^>]*>0[1-4]月<\/text>/g)].map((m) => Number(m[1]))
    expect(xs).toHaveLength(4)
    expect(xs[3] - xs[0]).toBeGreaterThan(HALF_W * 0.5)
  })
})
