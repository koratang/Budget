import { beforeEach, describe, expect, it } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import Page from '../PAGE-F15-04.vue'
import { LINKAGE, S, seed } from '@/bizfin/engine'
import { store } from '@/bizfin/persist'

describe('PAGE-F15-04 业财联动关系', () => {
  beforeEach(() => {
    S.dim = 'year'
    S.curM = 9
    seed()
    store.loaded = true
    store.canEdit = true
  })

  it('图谱节点、达成率与业务健康度（示例数据业务指标待填报）', async () => {
    const w = mount(Page)
    await flushPromises()
    expect(w.findAll('g[data-side="biz"]')).toHaveLength(4)
    expect(w.findAll('g[data-side="fin"]')).toHaveLength(7)
    expect(w.get('g[data-side="fin"][data-code="F1"]').text()).toContain('82%')
    expect(w.get('g[data-side="biz"][data-code="S1"]').text()).toContain('待填报')
    expect(w.get('[data-health]').text()).toBe('业务指标待填报')
  })

  it('悬停业务节点高亮其关联路径', async () => {
    const w = mount(Page)
    await flushPromises()
    await w.get('g[data-side="biz"][data-code="S1"]').trigger('mouseenter')
    expect(w.get('g[data-side="fin"][data-code="F1"]').classes()).toContain('hl')
    expect(w.get('g[data-side="fin"][data-code="F7"]').classes()).toContain('dim')
    expect(w.findAll('g.gedge.hl')).toHaveLength(3)
    await w.get('svg').trigger('mouseleave')
    expect(w.findAll('g.gedge.dim')).toHaveLength(0)
  })

  it('反向归因与明细表搜索', async () => {
    const w = mount(Page)
    await flushPromises()
    expect(w.get('[data-reverse]').text()).toContain('毛利率缺口 3.6pt（损失约 354 万元）')
    expect(w.findAll('[data-testid="link-table"] tbody tr')).toHaveLength(LINKAGE.length)
    await w.get('input[placeholder="搜索指标 / 部门"]').setValue('不存在的关键词')
    expect(w.text()).toContain('没有匹配的关联关系。')
  })
})
