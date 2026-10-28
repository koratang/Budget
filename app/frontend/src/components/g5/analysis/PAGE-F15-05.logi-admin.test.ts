/**
 * PAGE-F15-05 数据分析：头程物流 / 尾程物流 / 仓储 / 管理费用 四个子模块组件测试。
 * 期望值按示例数据手算：F1 净销售额 9,840 万元；F4.3 头程 2.15%、F4.4 尾程 2.90%、F4.5 仓储 1.35%、F4.7 管理费用 2.5%（目标 2.6%）。
 */
import { beforeEach, describe, expect, it } from 'vitest'
import { mount, type VueWrapper } from '@vue/test-utils'
import { nextTick, type Component } from 'vue'
import { S, recompute, seed } from '@/bizfin/engine'
import { store } from '@/bizfin/persist'
import AnaAdmin from './AnaAdmin.vue'
import AnaLogiPost from './AnaLogiPost.vue'
import AnaLogiPre from './AnaLogiPre.vue'
import AnaWarehouse from './AnaWarehouse.vue'

const kpiVal = (w: VueWrapper, key: string): string => w.get(`[data-kpi="${key}"] .ana-kpi-val`).text()
const kpiFoot = (w: VueWrapper, key: string): string => w.get(`[data-kpi="${key}"] .ana-kpi-foot`).text()
const num = (s: string): number => Number(s.replace(/[^\d.-]/g, ''))

beforeEach(() => {
  S.dim = 'year'
  S.curM = 9
  seed()
  store.loaded = true
  store.canEdit = true
})

describe('头程物流分析', () => {
  it('年度：头程成本 = F1 × F4.3（9,840 × 2.15% = 211.6 万元），占比 2.15%，三张趋势图', () => {
    const w = mount(AnaLogiPre)
    expect(kpiVal(w, 'cost')).toBe('211.6万元')
    expect(kpiFoot(w, 'cost')).toContain('全年累计')
    expect(kpiFoot(w, 'cost')).toContain('F4.3')
    expect(kpiVal(w, 'rate')).toBe('2.15%')
    expect(w.findAll('svg')).toHaveLength(3)
    expect(w.text()).toContain('美森快船·美西')
    expect(w.text()).toContain('月度（01月 ~ 09月）')
  })

  it('切到月度维度后 KPI 改为当月口径并自动刷新', async () => {
    const w = mount(AnaLogiPre)
    const yearCost = num(kpiVal(w, 'cost'))
    S.dim = 'month'
    S.curM = 3
    recompute()
    await nextTick()
    expect(kpiFoot(w, 'cost')).toContain('当月')
    expect(num(kpiVal(w, 'cost'))).toBeLessThan(yearCost)
    expect(w.text()).toContain('月度（01月 ~ 03月）')
  })
})

describe('尾程物流分析', () => {
  it('年度：尾程成本池 = F1 ×（F4.4 + F4.5）= 418.2 万元，占比 4.25%，单位成本 = 费用 ÷ 订单量', () => {
    const w = mount(AnaLogiPost)
    expect(kpiVal(w, 'cost')).toBe('418.2万元')
    expect(kpiVal(w, 'rate')).toBe('4.25%')
    const orders = num(kpiVal(w, 'orders'))
    expect(orders).toBeGreaterThan(0)
    expect(num(kpiVal(w, 'uc'))).toBeCloseTo(418.2 * 10000 / orders, 0)
    expect(w.text()).toContain('专线卡车')
    expect(w.findAll('svg')).toHaveLength(3)
  })
})

describe('仓储分析', () => {
  it('年度：仓储成本（含代发）= 9,840 × 1.35% × 1.35 = 179.3 万元，库存勾稽 期初 + 入库 − 出库 = 期末', () => {
    const w = mount(AnaWarehouse)
    expect(kpiVal(w, 'cost')).toBe('179.3万元')
    expect(kpiFoot(w, 'cost')).toContain('仓储 132.8 + 代发 46.5')
    expect(kpiVal(w, 'rate')).toBe('1.82%')
    expect(num(kpiVal(w, 'open'))).toBe(22000)
    const k = (key: string): number => num(kpiVal(w, key))
    expect(k('open') + k('in') - k('out')).toBe(k('close'))
    const rows = w.get('[data-testid="stock-table"]').findAll('tbody tr')
    expect(rows).toHaveLength(5) /* 4 座海外仓 + 合计 */
    expect(rows[0].text()).toContain('万邑通·美西仓')
    expect(w.text()).not.toContain('自有仓')
  })

  it('月度：库存表标注当月，KPI 为当月流水', async () => {
    S.dim = 'month'
    S.curM = 5
    recompute()
    const w = mount(AnaWarehouse)
    expect(w.text()).toContain('当月（05月）')
    expect(kpiFoot(w, 'open')).toBe('当月月初 4 仓合计')
    const k = (key: string): number => num(kpiVal(w, key))
    expect(k('open') + k('in') - k('out')).toBe(k('close'))
  })
})

describe('管理费用分析', () => {
  it('管理费用池 = F1 × F4.7 = 246.0 万元，费用率 2.50% 优于目标 0.10pt，逐月合计与年度池勾稽', () => {
    const w = mount(AnaAdmin)
    expect(kpiVal(w, 'pool')).toBe('246.0万元')
    expect(kpiVal(w, 'rate')).toBe('2.50%')
    expect(kpiFoot(w, 'rate')).toBe('目标 2.6% · 优于目标 0.10pt')
    expect(w.get('[data-kpi="rate"]').attributes('data-tone')).toBe('good')
    expect(w.text()).toContain('管理费用分析口径：')
    expect(w.text()).toContain('逐分勾稽')

    const deptTable = w.get('[data-testid="dept-month-table"]')
    const total = deptTable.findAll('tbody tr').at(-1)
    expect(total?.text()).toContain('246.0')
    expect(total?.text()).toContain('100.0%')
    /* 合计行 1-9 月之和 = 年度池 */
    const monthCells = (total?.findAll('td') ?? []).slice(1, 10).map((c) => num(c.text()))
    expect(monthCells.reduce((a, b) => a + b, 0)).toBeCloseTo(246, 0)
    expect(deptTable.findAll('tbody tr')).toHaveLength(10) /* 9 个部门 + 合计 */
    expect(w.get('[data-testid="type-month-table"]').findAll('tbody tr')).toHaveLength(8) /* 7 类 + 合计 */
    expect(w.text()).toContain('2026年度累计（1-9月）')
    expect(w.findAll('svg')).toHaveLength(4)
  })

  it('月度维度：矩阵取选中月份，合计等于该月管理费用池', async () => {
    S.dim = 'month'
    S.curM = 4
    recompute()
    const w = mount(AnaAdmin)
    expect(kpiFoot(w, 'pool')).toBe('2026年 04月发生额')
    const monthTotal = w.get('[data-testid="dept-month-table"]').findAll('tbody tr').at(-1)?.findAll('td')[4].text()
    expect(kpiVal(w, 'pool')).toBe(monthTotal + '万元')
    expect(w.get('[data-testid="matrix-table"]').findAll('tbody tr').at(-1)?.text()).toContain(monthTotal ?? '')
  })
})

describe('只读视图：CEO（canEdit=false）同样无任何编辑控件', () => {
  const views: [string, Component][] = [['头程', AnaLogiPre], ['尾程', AnaLogiPost], ['仓储', AnaWarehouse], ['管理费用', AnaAdmin]]
  it.each(views)('%s 子模块不渲染输入框与按钮', (_name, view) => {
    store.canEdit = false
    const w = mount(view)
    expect(w.findAll('input, select, textarea, button')).toHaveLength(0)
  })
})
