/**
 * BudgetGrid（CMP-F04-01）的纯逻辑：服务端列定义 → RevoGrid 列；编辑/粘贴 → 保存变更（携带基准值）。
 * 与 RevoGrid 解耦，便于单测。
 */
import type { CellProps, CellTemplateProp, ColumnDataSchemaModel, ColumnGrouping, ColumnRegular, HyperFunc, VNode } from '@revolist/revogrid'
import { formatDecimal, normalizeInput } from '@/utils/decimal'

/** 服务端返回的列定义（API-F04-02 grid.columns；按角色裁剪后下发） */
export interface GridColumnDef {
  /** 字段 key，也是行 values 的 key 与保存时的 field */
  key: string
  label: string
  /** dim = 维度列（冻结在左侧）；value = 数值/输入列 */
  kind?: 'dim' | 'value'
  /** money 金额（2 位小数）/ ratio 百分数字符串 / number 整数或数量 / text 文本 */
  type?: 'money' | 'ratio' | 'number' | 'text'
  /** 本人可编辑（服务端按角色裁剪） */
  editable?: boolean
  width?: number
  /** 表头分组（如「2027-01」下的「销量」「单价」），相邻同组列合并表头 */
  group?: string
}

/** 服务端返回的行（API-F04-02 grid.rows） */
export interface GridRow {
  /** 单元键：保存时原样回传 */
  key: string
  values: Record<string, string | null>
  /** input 输入行 / calc 派生行（只读）/ total 合计行（固定在底部，只读） */
  kind?: 'input' | 'calc' | 'total'
  /** 本行只读的字段（如已提交月份） */
  readonly_fields?: string[]
}

/** 保存变更（API-F04-03 PATCH /filling-units/{id}/cells 的一项） */
export interface CellChange {
  row_key: string
  field: string
  value: string | null
  /** 基准值：打开页面（或最近一次服务端返回）时的值，用于单元格级乐观锁（DEC-007） */
  base: string | null
}

export type CellMap = Record<string, string>

export const ROW_KEY = '__rowKey'
export const ROW_KIND = '__rowKind'
export const ROW_CLASS = '__rowClass'

export type GridModel = Record<string, string | null | undefined> & { [ROW_KEY]: string }

export function cellKey(rowKey: string, field: string): string {
  return `${rowKey}::${field}`
}

export function toModels(rows: GridRow[]): GridModel[] {
  return rows.map((r) => ({
    ...r.values,
    [ROW_KEY]: r.key,
    [ROW_KIND]: r.kind ?? 'input',
    [ROW_CLASS]: r.kind === 'calc' ? 'row-calc' : r.kind === 'total' ? 'row-total' : '',
  }))
}

export function isCellEditable(col: GridColumnDef | undefined, row: GridRow | undefined, locked: boolean): boolean {
  if (locked || !col || !row) return false
  if (col.kind === 'dim' || !col.editable) return false
  if (row.kind === 'calc' || row.kind === 'total') return false
  return !(row.readonly_fields ?? []).includes(col.key)
}

/** 编辑或粘贴的原始值 → 发送给服务端的字符串（比率允许「12.5%」；金额去千分位；服务端负责校验） */
export function normalizeValue(col: GridColumnDef, raw: unknown): string | null {
  if (col.type === 'text') {
    if (raw === null || raw === undefined) return null
    const s = String(raw).trim()
    return s === '' ? null : s
  }
  return normalizeInput(raw, { percent: col.type === 'ratio' })
}

export function formatCell(col: GridColumnDef, value: string | null | undefined): string {
  if (value === null || value === undefined || value === '') return ''
  if (col.type === 'money') return formatDecimal(value, 2)
  if (col.type === 'ratio') return `${value}%`
  return String(value)
}

export interface RawEdit {
  rowKey: string
  field: string
  raw: unknown
}

/**
 * 把一组原始编辑转为保存变更：过滤只读格、值未变化的格；基准值取 baseline（服务端最近一次给出的行）。
 */
export function collectChanges(
  edits: RawEdit[],
  columns: GridColumnDef[],
  baseline: GridRow[],
  locked: boolean,
): CellChange[] {
  const colByKey = new Map(columns.map((c) => [c.key, c]))
  const rowByKey = new Map(baseline.map((r) => [r.key, r]))
  const out: CellChange[] = []
  for (const e of edits) {
    const col = colByKey.get(e.field)
    const row = rowByKey.get(e.rowKey)
    if (!col || !row || !isCellEditable(col, row, locked)) continue
    const value = normalizeValue(col, e.raw)
    const base = row.values[e.field] ?? null
    if (value === base) continue
    out.push({ row_key: e.rowKey, field: e.field, value, base })
  }
  return out
}

export interface BuildContext {
  locked: boolean
  rowByKey: Map<string, GridRow>
  errors: CellMap
  flags: CellMap
}

/** 服务端列定义 → RevoGrid 列（维度列冻结在左侧；只读/锁定；错误标红；超放量标注） */
export function buildColumns(defs: GridColumnDef[], ctx: BuildContext): (ColumnRegular | ColumnGrouping)[] {
  const regular = defs.map<ColumnRegular>((col) => {
    const isDim = col.kind === 'dim'
    const isNum = !isDim && col.type !== 'text'
    return {
      prop: col.key,
      name: col.label,
      size: col.width ?? (isDim ? 140 : 112),
      pin: isDim ? 'colPinStart' : undefined,
      readonly: (p: ColumnDataSchemaModel) => !isCellEditable(col, ctx.rowByKey.get(String(p.model[ROW_KEY])), ctx.locked),
      cellTemplate: (h: HyperFunc<VNode>, p: CellTemplateProp) => {
        const model = p.model as GridModel
        const key = cellKey(String(model[ROW_KEY]), col.key)
        const text = isDim ? String(p.value ?? '') : formatCell(col, (p.value as string | null | undefined) ?? null)
        return h('span', { class: 'bg-cell-text', 'data-cell': key }, text)
      },
      cellProperties: (p: ColumnDataSchemaModel) => {
        const model = p.model as GridModel
        const rowKey = String(model[ROW_KEY])
        const key = cellKey(rowKey, col.key)
        const error = ctx.errors[key]
        const flag = ctx.flags[key]
        const editable = isCellEditable(col, ctx.rowByKey.get(rowKey), ctx.locked)
        const props: CellProps = {
          class: {
            'bg-dim': isDim,
            'bg-num': isNum,
            'bg-edit': editable,
            'bg-locked': !isDim && !editable,
            'bg-error': !!error,
            'bg-flag': !!flag,
          },
        }
        if (error) {
          props['aria-invalid'] = 'true'
          props.title = error
        } else if (flag) {
          props.title = flag
        }
        return props
      },
    }
  })

  // 相邻同 group 的列合并表头；维度列不分组
  const out: (ColumnRegular | ColumnGrouping)[] = []
  for (let i = 0; i < defs.length; i++) {
    const g = defs[i].group
    if (!g || defs[i].kind === 'dim') {
      out.push(regular[i])
      continue
    }
    const children: ColumnRegular[] = [regular[i]]
    while (i + 1 < defs.length && defs[i + 1].group === g && defs[i + 1].kind !== 'dim') {
      i++
      children.push(regular[i])
    }
    out.push({ name: g, children } as ColumnGrouping)
  }
  return out
}
