import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import Page from '../PAGE-F15-02.vue'
import { S, find, recompute, seed } from '@/bizfin/engine'
import { commit, store } from '@/bizfin/persist'

vi.mock('@/bizfin/persist', async (orig) => ({ ...(await orig<typeof import('@/bizfin/persist')>()), commit: vi.fn() }))

describe('PAGE-F15-02 财务指标', () => {
  beforeEach(() => {
    vi.mocked(commit).mockClear()
    S.dim = 'year'
    S.curM = 9
    seed()
    store.loaded = true
    store.canEdit = true
  })

  it('KPI 与明细表数字与原工具一致', async () => {
    const w = mount(Page)
    await flushPromises()
    expect(w.get('[data-kpi="F1"]').text()).toContain('9,840')
    expect(w.get('[data-kpi="F3"]').text()).toContain('31.4')
    expect(w.get('[data-kpi="F6"]').text()).toContain('—')
    const row = w.get('tr[data-code="F1"]')
    expect((row.get('input').element as HTMLInputElement).value).toBe('9840')
    expect(row.text()).toContain('+15.0%')
    expect(w.text()).toContain('毛利率缺口 3.6pt')
    expect(w.text()).toContain('净利润达成率仅 42%')
  })

  it('筛选与搜索：仅一级 7 行；搜索「营销」命中营销费用率', async () => {
    const w = mount(Page)
    await flushPromises()
    await w.findAll('[aria-label="层级筛选"] button')[1].trigger('click')
    expect(w.findAll('[data-testid="fin-table"] tbody tr')).toHaveLength(7)
    await w.findAll('[aria-label="层级筛选"] button')[0].trigger('click')
    await w.get('input[placeholder="搜索指标 / 部门"]').setValue('营销')
    expect(w.find('tr[data-code="F4.1"]').exists()).toBe(true)
    expect(w.find('tr[data-code="F1.1"]').exists()).toBe(false)
  })

  it('编辑实际值写入引擎并保存「指标」部分；无效数字恢复原值', async () => {
    const w = mount(Page)
    await flushPromises()
    const input = w.get('tr[data-code="F7"] input')
    await input.setValue('1200')
    expect(find('F7')?.actual).toBe(1200)
    expect(commit).toHaveBeenCalledWith('indicators')
    expect(w.text()).toContain('F7 实际值 已更新，相关指标与建议已重新计算')

    vi.mocked(commit).mockClear()
    await input.setValue('一千')
    expect(find('F7')?.actual).toBe(1200)
    expect((input.element as HTMLInputElement).value).toBe('1200')
    expect(commit).not.toHaveBeenCalled()
    expect(w.text()).toContain('请输入有效数字，已恢复原值')
  })

  it('月度维度下编辑写入当月覆盖并标「手工填报」', async () => {
    S.dim = 'month'
    S.curM = 9
    recompute()
    const w = mount(Page)
    await flushPromises()
    await w.get('tr[data-code="F7"] input').setValue('150')
    expect(find('F7')?.actual).toBe(150)
    expect(commit).toHaveBeenCalledWith('indicators')
    expect(w.get('tr[data-code="F7"]').text()).toContain('手工填报')
    expect(w.text()).toContain('F7 的 2026年 09月 月度实际值已更新')
  })

  it('总经理（只读）看不到编辑输入框', async () => {
    store.canEdit = false
    const w = mount(Page)
    await flushPromises()
    expect(w.find('[data-testid="fin-table"] input').exists()).toBe(false)
    expect(w.get('tr[data-code="F1"]').text()).toContain('9,840')
  })

  it('派生值（F4.9 期间费用率合计）带「派生」标签且不给输入框；明细显示千分位', async () => {
    const w = mount(Page)
    await flushPromises()
    const row = w.get('tr[data-code="F4.9"]')
    expect(row.find('input').exists()).toBe(false)
    expect(row.find('[data-derived]').exists()).toBe(true)
    expect(w.get('tr[data-code="F7.5"]').find('[data-derived]').exists()).toBe(true)
    expect(w.get('tr[data-code="F1"]').find('[data-derived]').exists()).toBe(false)
  })

  it('期间费用率超标按 F4.9（实际 − 目标）计算，而非净利润 F4', async () => {
    const w = mount(Page)
    await flushPromises()
    const f49 = find('F4.9')
    const over = (f49?.actual ?? 0) - (f49?.target ?? 0)
    expect(w.text()).toContain('期间费用率超标 ' + over.toFixed(1) + 'pt')
    expect(w.text()).not.toContain('期间费用率超标 -766.1pt')
  })
})
