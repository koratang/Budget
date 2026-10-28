import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, RouterLinkStub } from '@vue/test-utils'
import { S, seed } from '@/bizfin/engine'
import { commit, store } from '@/bizfin/persist'
import Page from '../PAGE-F15-08.vue'

vi.mock('@/bizfin/persist', async (orig) => ({ ...(await orig<typeof import('@/bizfin/persist')>()), commit: vi.fn() }))

async function mountPage() {
  const w = mount(Page, { global: { stubs: { RouterLink: RouterLinkStub } } })
  await flushPromises()
  return w
}

describe('PAGE-F15-08 重点工作进度', () => {
  beforeEach(() => {
    seed()
    store.loaded = true
    store.canEdit = true
    vi.mocked(commit).mockClear()
  })

  it('KPI 与原工具一致：15 项、平均进度 60%、需关注 3 项（延误 2 · 阻滞 1）', async () => {
    const w = await mountPage()
    expect(w.get('[data-kpi="total"]').text()).toContain('15项')
    expect(w.get('[data-kpi="total"]').text()).toContain('已完成 2 · 平均进度 60%')
    expect(w.get('[data-kpi="hot"]').text()).toContain('3项')
    expect(w.get('[data-kpi="hot"]').text()).toContain('延误 2 · 阻滞 1')
    expect(w.get('[data-kpi="doing"]').text()).toContain('10项')
    expect(w.get('[data-kpi="cats"]').text()).toContain('核算 2')
    expect(w.get('[data-kpi="cats"]').text()).toContain('降本增收 7')
    expect(w.get('[data-kpi="cats"]').text()).toContain('已使用分类 4 / 6 项')
    expect(w.find('[aria-label="维度"]').exists()).toBe(false)
    const annual = w.get('[data-part="annual"]').findAll('tbody tr')
    expect(annual).toHaveLength(15)
    expect((annual[0].get('select[aria-label="工作状态"]').element as HTMLSelectElement).value).toBe('进行中')
    expect((annual[14].get('select[aria-label="工作状态"]').element as HTMLSelectElement).value).toBe('阻滞')
    expect(w.get('[data-part="watch"]').findAll('tbody tr')).toHaveLength(3)
  })

  it('进度限制在 0–100；在关注分区改的是对应台账行', async () => {
    const w = await mountPage()
    const blocked = S.KW_TASKS.find((t) => t.status === '阻滞')
    const watchRows = w.get('[data-part="watch"]').findAll('tbody tr')
    const row = watchRows[watchRows.length - 1]
    const prog = row.get('input[aria-label="目前进度"]')
    await prog.setValue('150')
    expect(blocked?.progress).toBe(100)
    expect((prog.element as HTMLInputElement).value).toBe('100')
    await prog.setValue('-5')
    expect(blocked?.progress).toBe(0)
    expect(commit).toHaveBeenLastCalledWith('keywork')

    await row.get('select[aria-label="工作状态"]').setValue('进行中')
    expect(blocked?.status).toBe('进行中')
    expect(w.get('[data-kpi="hot"]').text()).toContain('延误 2 · 阻滞 0')
    expect(w.get('[data-part="watch"]').findAll('tbody tr')).toHaveLength(2)
  })

  it('新增与二次确认删除', async () => {
    const w = await mountPage()
    await w.get('button.btn-primary').trigger('click')
    expect(S.KW_TASKS).toHaveLength(16)
    expect(S.KW_TASKS[15]).toEqual({ time: '', cat: '', goal: '', breakdown: '', eta: '', progress: 0, status: '进行中' })
    expect(w.get('[role="status"]').text()).toBe('已新增工作行，请填写时间 / 工作分类 / 工作目标 / 工作分解 / 预计完成时间 / 目前进度 / 工作状态')
    const first = S.KW_TASKS[0]
    const row = w.get('[data-part="annual"]').findAll('tbody tr')[0]
    await row.get('input[aria-label="工作目标"]').setValue('美国 STURDY 防倾倒标准合规改模（含镜柜）')
    expect(first.goal).toBe('美国 STURDY 防倾倒标准合规改模（含镜柜）')
    await row.get('button.btn-danger').trigger('click')
    await w.get('[data-part="annual"]').findAll('tbody tr')[0].get('button.btn-danger').trigger('click')
    expect(S.KW_TASKS).toHaveLength(15)
    expect(S.KW_TASKS.indexOf(first)).toBe(-1)
    expect(w.get('[role="status"]').text()).toBe('已删除第 1 行工作台账')
    expect(commit).toHaveBeenCalledTimes(3)
  })

  it('CEO（只读）看不到编辑控件，进度以进度条显示', async () => {
    store.canEdit = false
    const w = await mountPage()
    expect(w.findAll('input, select, button.btn-primary, button.btn-danger')).toHaveLength(0)
    expect(w.findAll('[data-progress]')[0].text()).toBe('62%')
  })
})
