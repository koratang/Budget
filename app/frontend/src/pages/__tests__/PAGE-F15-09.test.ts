import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import Page from '../PAGE-F15-09.vue'
import { S, find, recompute, seed, setMonthOverride } from '@/bizfin/engine'
import { commit, resetDemo, store } from '@/bizfin/persist'

/* 二次确认框：confirmOk 控制用户点「确认恢复」还是「取消」 */
const box = vi.hoisted(() => ({ ok: true, messages: [] as string[] }))
vi.mock('element-plus', () => ({
  ElMessageBox: {
    confirm: (message: string) => {
      box.messages.push(message)
      return box.ok ? Promise.resolve('confirm') : Promise.reject(new Error('cancel'))
    },
  },
}))

vi.mock('@/bizfin/persist', async (orig) => ({
  ...(await orig<typeof import('@/bizfin/persist')>()),
  commit: vi.fn(),
  resetDemo: vi.fn(() => Promise.resolve()),
}))

describe('PAGE-F15-09 业财数据管理', () => {
  beforeEach(() => {
    vi.mocked(commit).mockClear()
    vi.mocked(resetDemo).mockClear()
    S.dim = 'year'
    S.curM = 9
    seed()
    store.loaded = true
    store.canEdit = true
    store.canReset = false
    store.meta.indicators = { revision: 3, is_demo: false, updated_by: '李会计', updated_at: '2026-10-20T02:30:00Z' }
  })
  afterEach(() => vi.restoreAllMocks())

  it('粘贴导入：写入引擎、保存指标与维度两部分并去掉示例标记', async () => {
    const w = mount(Page)
    await flushPromises()
    await w.get('textarea').setValue('编码\t目标值\t实际值\nF1\t12000\t10500\nS1.1\t\t\n')
    await w.get('[data-paste-import]').trigger('click')
    expect(find('F1')?.actual).toBe(10500)
    expect(commit).toHaveBeenCalledWith(['indicators', 'biz_dim'], true)
    expect(w.text()).toContain('导入完成：成功更新 2 条指标')
    expect((w.get('textarea').element as HTMLTextAreaElement).value).toBe('')
  })

  it('导入失败（编码均未匹配）提示原文案且不保存', async () => {
    const w = mount(Page)
    await flushPromises()
    await w.get('textarea').setValue('编码\t实际值\nX9\t100')
    await w.get('[data-paste-import]').trigger('click')
    expect(commit).not.toHaveBeenCalled()
    expect(w.text()).toContain('导入失败：共 1 行，均未匹配到已有指标编码')
  })

  it('选择 CSV 文件导入', async () => {
    const w = mount(Page)
    await flushPromises()
    const input = w.get('input[data-file]')
    const file = new File(['编码,实际值\nF7,900'], '九月经营数据.csv', { type: 'text/csv' })
    Object.defineProperty(input.element, 'files', { value: [file] })
    await input.trigger('change')
    await flushPromises()
    await vi.waitFor(() => expect(find('F7')?.actual).toBe(900))
    expect(commit).toHaveBeenCalledWith(['indicators', 'biz_dim'], true)
  })

  it('导出全部指标：生成 CSV 并按原文件名下载', async () => {
    const create = vi.fn(() => 'blob:mock')
    URL.createObjectURL = create
    URL.revokeObjectURL = vi.fn()
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)
    let name = ''
    click.mockImplementation(function (this: HTMLAnchorElement) { name = this.download })
    const w = mount(Page)
    await flushPromises()
    const btn = w.findAll('button').find((b) => b.text() === '导出全部指标（CSV）')
    await btn?.trigger('click')
    expect(create).toHaveBeenCalled()
    expect(name).toMatch(/^业财指标_年度口径_全部_\d{8}_\d{4}\.csv$/)
    expect(w.text()).toContain('已导出全部指标（年度口径）')
  })

  it('清空当月手工覆盖并保存', async () => {
    const f1 = find('F1')
    if (f1) setMonthOverride(f1, 'actual', 8, 1300)
    recompute()
    const w = mount(Page)
    await flushPromises()
    expect(w.get('[data-ov-count]').text()).toBe('1')
    await w.get('[data-clear-ov]').trigger('click')
    expect(w.get('[data-ov-count]').text()).toBe('0')
    expect(find('F1')?.actual).toBe(9840)
    expect(commit).toHaveBeenCalledWith('indicators')
  })

  it('显示各部分最后保存人与时间', async () => {
    const w = mount(Page)
    await flushPromises()
    const row = w.get('[data-section="indicators"]').text()
    expect(row).toContain('财务与业务指标')
    expect(row).toContain('正式数据')
    expect(row).toContain('李会计')
    expect(row).toContain('2026-10-20 10:30')
    expect(w.get('[data-section="policy"]').text()).toContain('示例数据')
  })

  it('恢复示例数据仅财务负责人可见，二次确认后调用重置', async () => {
    let w = mount(Page)
    await flushPromises()
    expect(w.find('[data-reset]').exists()).toBe(false)
    store.canReset = true
    w = mount(Page)
    await flushPromises()
    box.ok = true
    box.messages = []
    await w.get('[data-reset]').trigger('click')
    await flushPromises()
    expect(box.messages[0]).toContain('清空服务器上已保存的全部业财数据')
    expect(resetDemo).toHaveBeenCalled()
  })

  it('取消确认不重置', async () => {
    store.canReset = true
    const w = mount(Page)
    await flushPromises()
    box.ok = false
    await w.get('[data-reset]').trigger('click')
    await flushPromises()
    expect(resetDemo).not.toHaveBeenCalled()
  })

  it('总经理（只读）看不到导入与清空控件，仍可导出', async () => {
    store.canEdit = false
    const w = mount(Page)
    await flushPromises()
    expect(w.find('textarea').exists()).toBe(false)
    expect(w.find('[data-paste-import]').exists()).toBe(false)
    expect(w.find('[data-clear-ov]').exists()).toBe(false)
    expect(w.find('[data-readonly]').exists()).toBe(true)
    expect(w.findAll('button').some((b) => b.text() === '导出全部指标（CSV）')).toBe(true)
  })

  it('页头维度切换与页内「月度 / 年度维度管理」操作同一状态', async () => {
    const w = mount(Page)
    await flushPromises()
    await w.get('[aria-label="维度"]').findAll('button')[1].trigger('click')
    expect(S.dim).toBe('month')
    expect(w.get('[aria-label="维度管理：维度"]').findAll('button')[1].attributes('aria-pressed')).toBe('true')
    await w.get('[aria-label="维度管理：月份"]').findAll('button')[4].trigger('click')
    expect(S.curM).toBe(5)
    expect((w.get('select[aria-label="月份"]').element as HTMLSelectElement).value).toBe('5')
    await w.get('[aria-label="维度管理：维度"]').findAll('button')[0].trigger('click')
    expect(w.get('[aria-label="维度"]').findAll('button')[0].attributes('aria-pressed')).toBe('true')
  })
})
