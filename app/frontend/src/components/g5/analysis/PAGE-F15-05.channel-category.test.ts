/**
 * PAGE-F15-05 数据分析：渠道效益 / 流量 / 用户 / 订单 / 品类 五个子模块组件测试。
 * 示例数据：F1 净销售额 9,840 万元；F4 净利润 553.9 万元；F5 净利润率 5.63%；渠道收入 F1.1~F1.5（Amazon 3,560 万元为第一大渠道）。
 * 这些子模块只读（原工具无编辑控件），因此 CEO 只读身份下应不出现任何输入框。
 */
import { beforeEach, describe, expect, it } from 'vitest'
import { mount, type VueWrapper } from '@vue/test-utils'
import { nextTick } from 'vue'
import { S, channelModel, orderModel, recompute, seed } from '@/bizfin/engine'
import { store } from '@/bizfin/persist'
import AnaCategory from './AnaCategory.vue'
import AnaChannel from './AnaChannel.vue'
import AnaOrder from './AnaOrder.vue'
import AnaTraffic from './AnaTraffic.vue'
import AnaUser from './AnaUser.vue'

const kpiVal = (w: VueWrapper, key: string): string => w.get(`[data-kpi="${key}"] .ana-kpi-val`).text()
const kpiFoot = (w: VueWrapper, key: string): string => w.get(`[data-kpi="${key}"] .ana-kpi-foot`).text()
const num = (s: string): number => Number(s.replace(/[^\d.-]/g, ''))
const totalCells = (w: VueWrapper): string[] => w.get('[data-test="total"]').findAll('td').map((td) => td.text())

beforeEach(() => {
  S.dim = 'year'
  S.curM = 9
  seed()
  store.loaded = true
  store.canEdit = true
})

describe('渠道效益分析', () => {
  it('矩阵合计：收入 9,840 万元，贡献毛利额合计 ≡ F4 净利润 553.9 万元（勾稽一致）', () => {
    const w = mount(AnaChannel)
    const total = w.get('[data-test="matrix-total"]').findAll('td').map((td) => td.text())
    expect(total[0]).toBe('合计')
    expect(total[1]).toBe('9,840')
    expect(total[9]).toBe('+554')
    expect(total[11]).toBe('100.0%')
    expect(kpiVal(w, 'gross')).toBe('554万')
    const tie = w.get('[data-test="tie"]').text()
    expect(tie).toContain('勾稽一致')
    expect(tie).toContain('贡献毛利额合计 553.9 万元')
    expect(tie).toContain('F4 净利润 553.9 万元')
    expect(tie).toContain('F5 净利润率 5.63%')
    expect(tie).toContain('贡献毛利率合计 5.63%')
    /* 5 渠道 + 合计 */
    expect(w.findAll('[data-test="matrix"] tbody tr')).toHaveLength(6)
    /* 2 张横条 + 8 张费用项趋势 */
    expect(w.findAll('svg')).toHaveLength(10)
    expect(w.text()).toContain('渠道效益分析说明：')
    expect(w.text()).toContain('月度（01月 ~ 09月）')
  })

  it('切到月度 3 月：贡献毛利额合计跟随当月 F4 刷新，趋势只画 1~3 月', async () => {
    const w = mount(AnaChannel)
    S.dim = 'month'
    S.curM = 3
    recompute()
    await nextTick()
    const tie = w.get('[data-test="tie"]').text()
    expect(tie).toContain('勾稽一致')
    expect(num(kpiVal(w, 'gross'))).toBeLessThan(554)
    expect(w.text()).toContain('月度（01月 ~ 03月）')
  })

  it('改了 F4 净利润后勾稽仍成立（费用池由财务指标决定）', async () => {
    const w = mount(AnaChannel)
    const f4 = S.IND.find((i) => i.code === 'F4')
    if (!f4) throw new Error('缺少 F4')
    f4.actual = 600
    recompute()
    await nextTick()
    const tie = w.get('[data-test="tie"]').text()
    expect(tie).toContain('勾稽一致')
    expect(tie).toContain('F4 净利润 600.0 万元')
  })
})

describe('流量分析', () => {
  it('合计行：UV × 转化率 ≡ 订单量，CPC = 营销费用 ÷ 付费 UV', () => {
    const w = mount(AnaTraffic)
    const cm = channelModel()
    expect(kpiVal(w, 'uv')).toBe((cm.uv / 10000).toLocaleString('zh-CN', { minimumFractionDigits: 1, maximumFractionDigits: 1 }) + '万')
    expect(cm.uv * cm.cvr / 100).toBeCloseTo(cm.orders, 6)
    expect(cm.mkt * 10000 / cm.paidUv).toBeCloseTo(cm.cpc, 6)
    const t = totalCells(w)
    expect(t[0]).toBe('合计')
    expect(t[2]).toBe('100.0%')
    expect(num(t[5])).toBe(Math.round(orderModel().total))
    expect(kpiFoot(w, 'cvr')).toContain('结构基准（S1.2 待填报）')
    expect(w.findAll('svg')).toHaveLength(4)
    expect(w.text()).toContain('流量分析口径：')
  })
})

describe('用户分析', () => {
  it('新客 + 老客订单 ≡ 渠道订单量；老客客单价 = 新客 × 1.12', () => {
    const w = mount(AnaUser)
    const t = totalCells(w)
    const total = Math.round(orderModel().total)
    expect(Math.abs(num(t[3]) + num(t[4]) - total)).toBeLessThanOrEqual(1)
    expect(num(t[8]) / num(t[7])).toBeCloseTo(1.12, 2)
    expect(kpiFoot(w, 'aovNew')).toContain('（+12%）')
    expect(w.findAll('tbody tr')).toHaveLength(6)
  })
})

describe('订单分析', () => {
  it('合计收入 9,840 万元，CR1 = Amazon 3,560 ÷ 9,840 = 36.2%', () => {
    const w = mount(AnaOrder)
    const t = totalCells(w)
    expect(t[3]).toBe('9,840')
    expect(w.text()).toContain('当前 CR1 = 36.2%（Amazon')
    expect(kpiVal(w, 'total')).toBe(totalCells(w)[1] + '单')
    /* 订单趋势 + 两张分布横条 */
    expect(w.findAll('svg')).toHaveLength(3)
  })
})

describe('品类分析', () => {
  it('件单比与原工具一致（年度口径叠加大促价格指数后为 1.02），SPU TOP / Bottom 各 10 行', () => {
    const w = mount(AnaCategory)
    expect(kpiFoot(w, 'qty')).toContain('件单比 1.02（1 单 1 件）')
    expect(totalCells(w)[4]).toBe('9,840')
    expect(w.findAll('[data-test="spu-top"] tbody tr')).toHaveLength(10)
    expect(w.findAll('[data-test="spu-bottom"] tbody tr')).toHaveLength(10)
    expect(w.text()).toContain('共 580 个 SPU')
    /* 3 张折线 + 2 张 100% 堆叠 */
    expect(w.findAll('svg')).toHaveLength(5)
  })
})

describe('CEO 只读', () => {
  it('五个子模块均无编辑控件', () => {
    store.canEdit = false
    for (const C of [AnaChannel, AnaTraffic, AnaUser, AnaOrder, AnaCategory]) {
      const w = mount(C)
      expect(w.findAll('input, select, textarea, button')).toHaveLength(0)
    }
  })
})
