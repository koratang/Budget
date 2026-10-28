import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, RouterLinkStub } from '@vue/test-utils'
import { LINKAGE, S, find, recompute, seed } from '@/bizfin/engine'
import { commit, store } from '@/bizfin/persist'
import Page from '../PAGE-F15-03.vue'

vi.mock('@/bizfin/persist', async (orig) => ({ ...(await orig<typeof import('@/bizfin/persist')>()), commit: vi.fn() }))

async function mountPage() {
  const w = mount(Page, { global: { stubs: { RouterLink: RouterLinkStub } } })
  await flushPromises()
  return w
}

describe('PAGE-F15-03 业务指标', () => {
  beforeEach(() => {
    seed()
    S.dim = 'year'
    S.curM = 9
    recompute()
    store.loaded = true
    store.canEdit = true
    vi.mocked(commit).mockClear()
  })

  it('数据状态与原工具口径一致：31 项二级、76 个维度单元格，S3 品类 / S4 服务商不展开矩阵', async () => {
    const w = await mountPage()
    expect(w.get('[data-testid="filled-stat"]').text()).toBe('0 / 31')
    expect(w.get('[data-testid="dim-stat"]').text()).toBe('0 / 76')
    const mats = w.findAll('[data-matrix]').map((m) => m.attributes('data-matrix'))
    expect(mats).toEqual(['S1-channel', 'S2-category', 'S4-lane'])
    expect(w.get('[data-matrix="S1-channel"]').findAll('tbody tr')).toHaveLength(6) /* 5 个渠道 + 合计行 */
    expect(w.get('[data-board="S1"]').get('[data-testid="board-fill"]').text()).toBe('0 / 13 项二级已填报')
    expect(w.get('[data-testid="linkage-summary"]').findAll('tbody tr')).toHaveLength(LINKAGE.length)
  })

  it('维度单元格填报：聚合回填整体值，保存维度与指标两部分', async () => {
    const w = await mountPage()
    const cell = w.get('input[aria-label="Amazon · UV 实际值"]')
    await cell.setValue('120')
    expect(find('S1.1')?.actual).toBe(120)
    expect(find('S1.1')?._dimAgg).toBe(true)
    expect(commit).toHaveBeenCalledWith(['biz_dim', 'indicators'])
    expect(w.get('[role="status"]').text()).toBe('S1.1 的渠道【Amazon】实际值已更新，指标整体值与板块达成率已同步重算')
    expect(w.get('[data-agg="S1.1"]').text()).toBe('整体值 120.0 万')
    expect(w.get('[data-testid="dim-stat"]').text()).toBe('1 / 76')
    /* 维度派生的指标整体值不再提供手工输入 */
    const row = w.get('[data-board="S1"] tr[data-code="S1.1"]')
    expect(row.find('input').exists()).toBe(false)
    expect(row.text()).toContain('维度派生')
  })

  it('维度单元格输入无效数字：提示并恢复，不保存', async () => {
    const w = await mountPage()
    const cell = w.get('input[aria-label="美东 · 单位头程成本 实际值"]')
    await cell.setValue('约三元')
    expect(w.get('[role="status"]').text()).toBe('请输入有效数字，已恢复原值')
    expect((cell.element as HTMLInputElement).value).toBe('')
    expect(commit).not.toHaveBeenCalled()
  })

  it('指标实际值编辑：保存指标部分，板块一级自动汇总', async () => {
    const w = await mountPage()
    S.IND.forEach((i) => { if (i.code === 'S3.1') i.target = 95 })
    await w.get('input[aria-label="S3.1 交货准时率（新品） 实际值"]').setValue('92.5')
    expect(find('S3.1')?.actual).toBe(92.5)
    expect(commit).toHaveBeenCalledWith('indicators')
    expect(w.get('[role="status"]').text()).toBe('S3.1 实际值 已更新，相关指标与建议已重新计算')
    expect(w.get('[data-board="S3"] .badge-warn').text()).toBe('填报中 1/6')
  })

  it('月度维度下编辑实际值：写月度覆盖并提示反算', async () => {
    S.IND.forEach((i) => { if (i.code === 'S4.3') { i.actual = 18; i.target = 17 } })
    S.dim = 'month'
    S.curM = 9
    recompute()
    const w = await mountPage()
    await w.get('input[aria-label="S4.3 单位尾程成本 实际值"]').setValue('16.5')
    expect(commit).toHaveBeenCalledWith('indicators')
    expect(find('S4.3')?.actual).toBe(16.5)
    expect(w.get('[role="status"]').text()).toBe('S4.3 的 2026年 09月 月度实际值已更新，年度累计值已同步反算，其余月份保持不变')
  })

  it('CEO（只读）看不到任何编辑控件', async () => {
    store.canEdit = false
    const w = await mountPage()
    expect(w.findAll('input')).toHaveLength(0)
    expect(w.get('[data-matrix="S1-channel"]').text()).toContain('未填报 → 整体值待填报')
  })

  it('宽矩阵按实际溢出显示横向滚动提示与右缘遮罩，滚到最右去掉遮罩；指标列 ≤ 3 的矩阵收紧表宽', async () => {
    const w = await mountPage()
    const box = w.get('[data-matrix="S1-channel"] .mx')
    expect(box.classes()).not.toContain('ovf') /* 未溢出时不显示提示 */
    const wrap = box.get('.table-wrap')
    const el = wrap.element as HTMLElement
    Object.defineProperty(el, 'scrollWidth', { configurable: true, value: 2000 })
    Object.defineProperty(el, 'clientWidth', { configurable: true, value: 960 })
    el.scrollLeft = 0
    await wrap.trigger('scroll')
    expect(box.classes()).toEqual(expect.arrayContaining(['ovf', 'more']))
    expect(box.get('.scroll-hint').text()).toContain('左右滑动查看更多列')
    el.scrollLeft = 1040
    await wrap.trigger('scroll')
    expect(box.classes()).toContain('ovf')
    expect(box.classes()).not.toContain('more')

    expect(box.classes()).not.toContain('compact')
    expect(w.get('[data-matrix="S2-category"] .mx').classes()).toContain('compact')
    expect(w.get('[data-matrix="S4-lane"] .mx').classes()).toContain('compact')
  })
})
