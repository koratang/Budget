import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, RouterLinkStub } from '@vue/test-utils'
import { ADVICE_SEED, S, seed } from '@/bizfin/engine'
import { commit, store } from '@/bizfin/persist'
import Page from '../PAGE-F15-07.vue'

vi.mock('@/bizfin/persist', async (orig) => ({ ...(await orig<typeof import('@/bizfin/persist')>()), commit: vi.fn() }))

async function mountPage() {
  const w = mount(Page, { global: { stubs: { RouterLink: RouterLinkStub } } })
  await flushPromises()
  return w
}

describe('PAGE-F15-07 经营建议', () => {
  beforeEach(() => {
    seed()
    store.loaded = true
    store.canEdit = true
    vi.mocked(commit).mockClear()
  })

  it('台账显示示例事件，页头显示年度 / 月度切换', async () => {
    const w = await mountPage()
    expect(w.get('[data-testid="count"]').text()).toBe(`${ADVICE_SEED.length} 条`)
    expect(w.findAll('tbody tr')).toHaveLength(ADVICE_SEED.length)
    expect(w.find('[aria-label="维度"]').exists()).toBe(true) /* 页面外壳统一显示维度切换 */
    expect((w.get('tbody tr select').element as HTMLSelectElement).value).toBe(ADVICE_SEED[0].seg)
  })

  it('新增、编辑、二次确认删除后保存政策部分', async () => {
    const w = await mountPage()
    const n = S.ADVICE_EVENTS.length
    await w.get('button.btn-primary').trigger('click')
    expect(S.ADVICE_EVENTS).toHaveLength(n + 1)
    expect(commit).toHaveBeenLastCalledWith('advice')
    expect(w.get('[role="status"]').text()).toBe('已新增建议行，请填写时间 / 业务板块 / 背景描述 / 管理建议 / 影响评估')

    const last = w.findAll('tbody tr')[n]
    await last.get('input[aria-label="时间"]').setValue('2026-10-01')
    await last.get('select').setValue('仓配履约板块')
    await last.get('textarea[aria-label="背景描述"]').setValue('独立站复购率连续两月低于目标')
    expect(S.ADVICE_EVENTS[n]).toEqual({ time: '2026-10-01', seg: '仓配履约板块', desc: '独立站复购率连续两月低于目标', advice: '', impact: '' })
    expect(commit).toHaveBeenCalledTimes(4)

    await last.get('button.btn-danger').trigger('click')
    expect(S.ADVICE_EVENTS).toHaveLength(n + 1) /* 第一次点击只进入确认 */
    /* 确认态「确认 / 取消」竖排在窄操作列内 */
    expect(w.findAll('tbody tr')[n].findAll('.op button').map((b) => b.text())).toEqual(['确认', '取消'])
    await w.findAll('tbody tr')[n].get('button.btn-danger').trigger('click')
    expect(S.ADVICE_EVENTS).toHaveLength(n)
    expect(w.get('[role="status"]').text()).toBe(`已删除第 ${n + 1} 行管理建议`)
    expect(commit).toHaveBeenCalledTimes(5)
  })

  it('CEO（只读）看不到编辑控件', async () => {
    store.canEdit = false
    const w = await mountPage()
    expect(w.findAll('input, textarea, select, button.btn-primary, button.btn-danger')).toHaveLength(0)
    expect(w.text()).toContain(ADVICE_SEED[0].desc)
  })
})
