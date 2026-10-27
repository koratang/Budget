import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import type { ColumnGrouping, ColumnRegular } from '@revolist/revogrid'
import BudgetGrid from './BudgetGrid.vue'
import {
  buildColumns,
  cellKey,
  collectChanges,
  isCellEditable,
  ROW_KEY,
  toModels,
  type GridColumnDef,
  type GridRow,
} from './budgetGrid'

// RevoGrid 是 Web Component，单测中用桩组件替代，只验证 BudgetGrid 对其事件的处理
vi.mock('@revolist/vue3-datagrid', async () => {
  const { defineComponent, h } = await import('vue')
  return {
    default: defineComponent({
      name: 'VGridStub',
      props: ['columns', 'source', 'pinnedBottomSource', 'readonly'],
      emits: ['beforeedit', 'beforerangeedit'],
      setup() {
        return () => h('div', { class: 'vgrid-stub' })
      },
    }),
  }
})

// 平台渠道填报的简化列定义：2 个维度列 + 2027-01 的销量（可编辑）/ 单价（可编辑）/ 收入（派生只读）+ 佣金率
const columns: GridColumnDef[] = [
  { key: 'store', label: '店铺', kind: 'dim', type: 'text' },
  { key: 'category', label: '品类', kind: 'dim', type: 'text' },
  { key: '2027-01:qty', label: '销量', type: 'number', editable: true, group: '2027-01' },
  { key: '2027-01:price', label: '单价', type: 'money', editable: true, group: '2027-01' },
  { key: '2027-01:revenue', label: '收入', type: 'money', editable: false, group: '2027-01' },
  { key: 'commission_rate', label: '佣金率', type: 'ratio', editable: true },
]

const rows: GridRow[] = [
  {
    key: 'u1|Amazon-US-01|浴室柜',
    values: { store: 'Amazon-US-01', category: '浴室柜', '2027-01:qty': '120', '2027-01:price': '389.00', '2027-01:revenue': '46680.00', commission_rate: '15' },
  },
  {
    key: 'u1|Amazon-US-01|淋浴房',
    values: { store: 'Amazon-US-01', category: '淋浴房', '2027-01:qty': '35', '2027-01:price': '1299.00', '2027-01:revenue': '45465.00', commission_rate: '15' },
    readonly_fields: ['2027-01:qty'],
  },
  { key: 'calc|毛利', kind: 'calc', values: { store: '毛利', category: '', '2027-01:revenue': '30123.45' } },
  { key: 'total', kind: 'total', values: { store: '合计', category: '', '2027-01:revenue': '92145.00' } },
]

describe('BudgetGrid 逻辑', () => {
  it('维度列冻结在左侧，同月列合并表头', () => {
    const cols = buildColumns(columns, { locked: false, rowByKey: new Map(rows.map((r) => [r.key, r])), errors: {}, flags: {} })
    expect((cols[0] as ColumnRegular).pin).toBe('colPinStart')
    expect((cols[1] as ColumnRegular).pin).toBe('colPinStart')
    const group = cols[2] as ColumnGrouping
    expect(group.name).toBe('2027-01')
    expect(group.children.map((c) => (c as ColumnRegular).prop)).toEqual(['2027-01:qty', '2027-01:price', '2027-01:revenue'])
    expect((cols[3] as ColumnRegular).prop).toBe('commission_rate')
  })

  it('只读列、只读字段、派生行、合计行与整表锁定均不可编辑', () => {
    const [store, , qty, price, revenue] = columns
    expect(isCellEditable(price, rows[0], false)).toBe(true)
    expect(isCellEditable(store, rows[0], false)).toBe(false) // 维度列
    expect(isCellEditable(revenue, rows[0], false)).toBe(false) // 服务端标记只读
    expect(isCellEditable(qty, rows[1], false)).toBe(false) // 行内只读字段（已提交月份）
    expect(isCellEditable(price, rows[2], false)).toBe(false) // 派生行
    expect(isCellEditable(price, rows[3], false)).toBe(false) // 合计行
    expect(isCellEditable(price, rows[0], true)).toBe(false) // 锁定
  })

  it('单格编辑生成一项变更并携带基准值；比率「12.5%」与金额千分位规范化为字符串', () => {
    expect(collectChanges([{ rowKey: rows[0].key, field: '2027-01:price', raw: '1,399.50' }], columns, rows, false)).toEqual([
      { row_key: rows[0].key, field: '2027-01:price', value: '1399.50', base: '389.00' },
    ])
    expect(collectChanges([{ rowKey: rows[0].key, field: 'commission_rate', raw: '12.5%' }], columns, rows, false)).toEqual([
      { row_key: rows[0].key, field: 'commission_rate', value: '12.5', base: '15' },
    ])
    // 清空 → null
    expect(collectChanges([{ rowKey: rows[0].key, field: '2027-01:qty', raw: '  ' }], columns, rows, false)[0].value).toBeNull()
  })

  it('整块粘贴：过滤只读格与未变化的格，其余一次返回', () => {
    const changes = collectChanges(
      [
        { rowKey: rows[0].key, field: '2027-01:qty', raw: '150' },
        { rowKey: rows[0].key, field: '2027-01:price', raw: '389.00' }, // 未变化
        { rowKey: rows[0].key, field: '2027-01:revenue', raw: '99999' }, // 只读列
        { rowKey: rows[1].key, field: '2027-01:qty', raw: '40' }, // 只读字段
        { rowKey: rows[1].key, field: '2027-01:price', raw: '1199' },
      ],
      columns,
      rows,
      false,
    )
    expect(changes).toEqual([
      { row_key: rows[0].key, field: '2027-01:qty', value: '150', base: '120' },
      { row_key: rows[1].key, field: '2027-01:price', value: '1199', base: '1299.00' },
    ])
    expect(collectChanges([{ rowKey: rows[0].key, field: '2027-01:qty', raw: '150' }], columns, rows, true)).toEqual([])
  })

  it('错误单元格标红并提示，超放量单元格标注，金额右对齐千分位显示', () => {
    const k = cellKey(rows[0].key, '2027-01:price')
    const f = cellKey(rows[1].key, '2027-01:price')
    const cols = buildColumns(columns, {
      locked: false,
      rowByKey: new Map(rows.map((r) => [r.key, r])),
      errors: { [k]: '该数据已被 王浩 于 2026-12-03 14:20 修改，请刷新后再改' },
      flags: { [f]: '超出新渠道放量规则' },
    })
    const price = (cols[2] as ColumnGrouping).children[1] as ColumnRegular
    const models = toModels(rows)
    const p0 = price.cellProperties!({ model: models[0], prop: price.prop, column: price, rowIndex: 0, colIndex: 3, colType: 'rgCol', type: 'rgRow', data: models } as never) as Record<string, unknown>
    expect(p0['aria-invalid']).toBe('true')
    expect(p0.title).toContain('该数据已被 王浩')
    expect((p0.class as Record<string, boolean>)['bg-error']).toBe(true)
    expect((p0.class as Record<string, boolean>)['bg-num']).toBe(true)
    const p1 = price.cellProperties!({ model: models[1], prop: price.prop, column: price, rowIndex: 1, colIndex: 3, colType: 'rgCol', type: 'rgRow', data: models } as never) as Record<string, unknown>
    expect((p1.class as Record<string, boolean>)['bg-flag']).toBe(true)
    expect(p1.title).toBe('超出新渠道放量规则')

    const vnode = price.cellTemplate!(((tag: unknown, props: unknown, text: unknown) => ({ tag, props, text })) as never, {
      model: { ...models[1] },
      prop: price.prop,
      column: price,
      rowIndex: 1,
      colIndex: 3,
      colType: 'rgCol',
      type: 'rgRow',
      data: models,
      value: '1299.00',
    } as never) as unknown as { text: string }
    expect(vnode.text).toBe('1,299.00')
    expect(models[0][ROW_KEY]).toBe(rows[0].key)
  })
})

function grid(w: ReturnType<typeof mountGrid>) {
  return w.findComponent({ name: 'VGridStub' })
}

function mountGrid(extra: Record<string, unknown> = {}) {
  return mount(BudgetGrid, {
    props: { columns, rows, ...extra },
  })
}

function customEvent<T>(detail: T) {
  let prevented = false
  return {
    event: { detail, preventDefault: () => (prevented = true) } as unknown as CustomEvent<T>,
    prevented: () => prevented,
  }
}

describe('BudgetGrid 组件', () => {
  it('合计行固定在底部，其余行进入主体', () => {
    const w = mountGrid()
    const stub = grid(w)
    expect(stub.props('source')).toHaveLength(3)
    expect(stub.props('pinnedBottomSource')).toHaveLength(1)
    expect(stub.props('readonly')).toBe(false)
  })

  it('单元格编辑失焦 → save 事件（1 项，含基准值）', async () => {
    const w = mountGrid()
    const models = toModels(rows)
    const { event } = customEvent({ type: 'rgRow', prop: '2027-01:qty', model: models[0], val: '130' })
    grid(w).vm.$emit('beforeedit', event)
    expect(w.emitted('save')).toEqual([[[{ row_key: rows[0].key, field: '2027-01:qty', value: '130', base: '120' }], 'edit']])
  })

  it('编辑只读格被阻止且不保存', () => {
    const w = mountGrid()
    const models = toModels(rows)
    const { event, prevented } = customEvent({ type: 'rgRow', prop: '2027-01:revenue', model: models[0], val: '1' })
    grid(w).vm.$emit('beforeedit', event)
    expect(prevented()).toBe(true)
    expect(w.emitted('save')).toBeUndefined()
  })

  it('整块粘贴 → 一次批量 save；只读格在表格中恢复原值', () => {
    const w = mountGrid()
    const models = toModels(rows)
    const data: Record<number, Record<string, string>> = {
      0: { '2027-01:qty': '200', '2027-01:revenue': '1' },
      1: { '2027-01:qty': '50', '2027-01:price': '1,250.00' },
    }
    const { event } = customEvent({ type: 'rgRow', data, models: { 0: models[0], 1: models[1] }, newRange: null, oldRange: null })
    grid(w).vm.$emit('beforerangeedit', event)
    const saves = w.emitted('save')!
    expect(saves).toHaveLength(1)
    expect(saves[0]).toEqual([
      [
        { row_key: rows[0].key, field: '2027-01:qty', value: '200', base: '120' },
        { row_key: rows[1].key, field: '2027-01:price', value: '1250.00', base: '1299.00' },
      ],
      'paste',
    ])
    expect(data[0]['2027-01:revenue']).toBe('46680.00')
    expect(data[1]['2027-01:qty']).toBe('35')
    expect(data[1]['2027-01:price']).toBe('1250.00')
  })

  it('锁定态：整表只读，粘贴被阻止', () => {
    const w = mountGrid({ locked: true })
    expect(grid(w).props('readonly')).toBe(true)
    const models = toModels(rows)
    const { event, prevented } = customEvent({ type: 'rgRow', data: { 0: { '2027-01:qty': '1' } }, models: { 0: models[0] }, newRange: null, oldRange: null })
    grid(w).vm.$emit('beforerangeedit', event)
    expect(prevented()).toBe(true)
    expect(w.emitted('save')).toBeUndefined()
  })

  it('错误清单与超放量标注（插槽可替换）', () => {
    const w = mountGrid({
      errors: { [cellKey(rows[0].key, '2027-01:price')]: '允许范围 0.01 ~ 99,999.99' },
      flags: { [cellKey(rows[1].key, '2027-01:price')]: '上限 ¥ 40,000.00' },
    })
    expect(w.get('[data-grid-errors]').text()).toContain('Amazon-US-01 · 浴室柜 · 单价：允许范围 0.01 ~ 99,999.99')
    expect(w.text()).toContain('1 个单元格超出新渠道放量规则')

    const w2 = mount(BudgetGrid, {
      props: { columns, rows, flags: { [cellKey(rows[1].key, '2027-01:price')]: '上限' } },
      slots: { 'over-limit': '<div class="custom-flag">自定义标注</div>' },
      })
    expect(w2.find('.custom-flag').exists()).toBe(true)
  })
})
