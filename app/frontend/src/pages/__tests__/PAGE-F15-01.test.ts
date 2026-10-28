import { beforeEach, describe, expect, it } from 'vitest'
import { flushPromises, mount, RouterLinkStub } from '@vue/test-utils'
import Page from '../PAGE-F15-01.vue'
import { S, recompute, seed } from '@/bizfin/engine'
import { store } from '@/bizfin/persist'

const mountPage = () => mount(Page, { global: { stubs: { RouterLink: RouterLinkStub } } })

describe('PAGE-F15-01 经营总览驾驶舱', () => {
  beforeEach(() => {
    S.dim = 'year'
    S.curM = 9
    seed()
    store.loaded = true
    store.canEdit = true
  })

  it('KPI 与原工具一致：营业收入 9,840、毛利率 31.4、净利润 553.9，年度维度同比 +15.0%', async () => {
    const w = mountPage()
    await flushPromises()
    expect(w.get('[data-kpi="F1"]').text()).toContain('9,840')
    expect(w.get('[data-kpi="F1"]').text()).toContain('同比 +15.0%')
    expect(w.get('[data-kpi="F1"]').text()).toContain('环比 —')
    expect(w.get('[data-kpi="F3"]').text()).toContain('31.4')
    expect(w.get('[data-kpi="F4"]').text()).toContain('553.9')
    expect(w.get('[data-kpi="F7"]').text()).toContain('820')
    /* 顶边色（达成率分档）与环比 / 同比（涨红跌绿）两套红色含义有图例说明 */
    const lg = w.get('[data-color-legend]').text()
    expect(lg).toContain('达成率分档')
    expect(lg).toContain('涨红跌绿')
  })

  it('渠道结构、传导链、勾稽校验与达成率预警', async () => {
    const w = mountPage()
    await flushPromises()
    const text = w.text()
    expect(text).toContain('Amazon 占比 36.2%')
    const chain = w.get('[data-chain]').findAll('li')
    expect(chain).toHaveLength(6)
    expect(chain[0].text()).toContain('销售费用率↓（5.7% → 5.1%）')
    expect(chain[2].text()).toContain('存货周转天数↓（78 → 60 天）')
    expect(chain[3].text()).toContain('营销板块 待填报')
    /* 预警表：低于 80% 的二级指标按达成率升序，共 13 项 */
    expect(text).toContain('共 13 项')
    const rows = w.get('[data-testid="risk-table"] tbody').findAll('tr')
    expect(rows).toHaveLength(13)
    expect(rows[0].text()).toMatch(/F2\.[348]/)
    expect(text).toContain('〔年度累计〕净销售额 一级 vs 渠道二级合计')
    const links = w.findAllComponents(RouterLinkStub).map((l) => l.props('to'))
    expect(links).toContainEqual({ name: 'bizfin-linkage' })
    expect(links).toContainEqual({ name: 'bizfin-advice' })
  })

  it('切到月度维度后自动刷新为当月口径（09 月净销售额 1,188，含环比）', async () => {
    const w = mountPage()
    await flushPromises()
    S.dim = 'month'
    S.curM = 9
    recompute()
    await flushPromises()
    const kpi = w.get('[data-kpi="F1"]').text()
    expect(kpi).toContain('1,188')
    expect(kpi).toContain('环比 -9.3%')
  })

  it('渠道毛利率：四条重合线末值只标一次并注明；传导链金额按涨红跌绿着色', async () => {
    const w = mountPage()
    await flushPromises()
    const notes = w.findAll('[data-gm-overlap]').map((n) => n.text())
    expect(notes.some((t) => t.includes("Amazon / Wayfair / HomeDepot / Lowe's 均为"))).toBe(true)
    const svg = w.findAll('.chart').map((c) => c.html()).find((h) => h.includes('线重合'))
    expect(svg).toBeDefined()
    expect((svg || '').match(/线重合/g)).toHaveLength(1)
    const first = w.get('[data-chain]').findAll('li')[0].get('.fin')
    expect(first.text()).toMatch(/^净利润 \+/)
    expect(first.classes()).toContain('up')
  })
})
