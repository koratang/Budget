<script setup lang="ts">
/**
 * 预算表格 BudgetGrid（CMP-F04-01，封装 RevoGrid）
 * - 按服务端列定义渲染（物流物控只拿到四个比例列等裁剪由服务端完成）；维度列冻结在左侧
 * - 单元格编辑失焦即触发 save（applyOnClose），每格携带基准值（DEC-007）
 * - 从 Excel 整块粘贴 / 区域填充 → 一次批量 save
 * - errors：单元格错误标红并就地提示（title + 表格下方清单）
 * - 只读列 / 只读字段 / 派生行 / 合计行 / 整表锁定（locked）
 * - flags：新渠道超放量标注；over-limit 插槽可自定义汇总提示
 * 金额与比率均为字符串，表格不做任何计算（DEC-005）。
 */
import { computed, ref, watch } from 'vue'
import VGrid from '@revolist/vue3-datagrid'
import type { BeforeRangeSaveDataDetails, BeforeSaveDataDetails, RowDefinition } from '@revolist/revogrid'
import {
  buildColumns,
  cellKey,
  collectChanges,
  isCellEditable,
  ROW_CLASS,
  ROW_KEY,
  SUB_ROW_SIZE,
  toModels,
  type CellChange,
  type CellMap,
  type GridColumnDef,
  type GridModel,
  type GridRow,
  type RawEdit,
} from './budgetGrid'

const props = withDefaults(
  defineProps<{
    columns: GridColumnDef[]
    rows: GridRow[]
    /** 整表锁定（已提交 / 已锁定版本）：全部只读、禁止粘贴 */
    locked?: boolean
    /** 单元格错误：key = `${row_key}::${field}`，值为提示文字（越界允许范围、冲突「该数据已被…修改」等） */
    errors?: CellMap
    /** 超放量标注：key 同上，值为说明文字 */
    flags?: CellMap
    height?: string
  }>(),
  { locked: false, errors: () => ({}), flags: () => ({}), height: '62vh' },
)

const emit = defineEmits<{
  /** 保存变更：单格编辑为 1 项；整块粘贴为多项、一次发送 */
  save: [changes: CellChange[], source: 'edit' | 'paste']
}>()

const bodyRows = computed(() => props.rows.filter((r) => r.kind !== 'total'))
const totalRows = computed(() => props.rows.filter((r) => r.kind === 'total'))
const rowByKey = computed(() => new Map(props.rows.map((r) => [r.key, r])))

const source = ref<GridModel[]>([])
const pinnedBottom = ref<GridModel[]>([])
watch(
  () => props.rows,
  () => {
    source.value = toModels(bodyRows.value)
    pinnedBottom.value = toModels(totalRows.value)
  },
  { immediate: true, deep: true },
)

// 带次级灰字的行加高（主体行与底部合计行分别按各自索引）
const rowDefinitions = computed<RowDefinition[]>(() => [
  ...bodyRows.value.flatMap((r, index) => (r.sub ? [{ type: 'rgRow' as const, index, size: SUB_ROW_SIZE }] : [])),
  ...totalRows.value.flatMap((r, index) => (r.sub ? [{ type: 'rowPinEnd' as const, index, size: SUB_ROW_SIZE }] : [])),
])

const gridColumns = computed(() =>
  buildColumns(props.columns, {
    locked: props.locked,
    rowByKey: rowByKey.value,
    errors: props.errors,
    flags: props.flags,
  }),
)

const dimColumns = computed(() => props.columns.filter((c) => c.kind === 'dim'))
const colLabel = computed(() => new Map(props.columns.map((c) => [c.key, c.label])))

function describe(key: string): string {
  const [rowKey, field] = key.split('::')
  const row = rowByKey.value.get(rowKey)
  const dims = row ? dimColumns.value.map((c) => row.values[c.key]).filter(Boolean) : []
  return [...dims, colLabel.value.get(field) ?? field].join(' · ')
}

const errorList = computed(() => Object.entries(props.errors).map(([k, msg]) => ({ key: k, where: describe(k), msg })))
const flagList = computed(() => Object.entries(props.flags).map(([k, msg]) => ({ key: k, where: describe(k), msg })))

function onBeforeEdit(e: CustomEvent<BeforeSaveDataDetails>): void {
  const d = e.detail
  if (d.type !== 'rgRow') {
    e.preventDefault()
    return
  }
  const rowKey = String((d.model as GridModel)[ROW_KEY])
  const field = String(d.prop)
  if (!isCellEditable(props.columns.find((c) => c.key === field), rowByKey.value.get(rowKey), props.locked)) {
    e.preventDefault()
    return
  }
  const changes = collectChanges([{ rowKey, field, raw: d.val }], props.columns, props.rows, props.locked)
  if (changes.length) {
    d.val = changes[0].value ?? ''
    emit('save', changes, 'edit')
  }
}

function onBeforeRangeEdit(e: CustomEvent<BeforeRangeSaveDataDetails>): void {
  const d = e.detail
  if (d.type !== 'rgRow' || props.locked) {
    e.preventDefault()
    return
  }
  const edits: RawEdit[] = []
  for (const [idx, changed] of Object.entries(d.data)) {
    const model = d.models[Number(idx)] as GridModel | undefined
    if (!model || !changed) continue
    for (const [field, raw] of Object.entries(changed)) {
      if (field === ROW_KEY || field.startsWith('__')) continue
      edits.push({ rowKey: String(model[ROW_KEY]), field, raw })
    }
  }
  const changes = collectChanges(edits, props.columns, props.rows, props.locked)
  // 不可编辑的格恢复原值，避免表格本地显示被粘贴覆盖
  const allowed = new Set(changes.map((c) => cellKey(c.row_key, c.field)))
  for (const [idx, changed] of Object.entries(d.data)) {
    const model = d.models[Number(idx)] as GridModel | undefined
    if (!model || !changed) continue
    for (const field of Object.keys(changed)) {
      if (!allowed.has(cellKey(String(model[ROW_KEY]), field))) {
        ;(changed as Record<string, unknown>)[field] = model[field]
      } else {
        const c = changes.find((x) => x.row_key === model[ROW_KEY] && x.field === field)
        ;(changed as Record<string, unknown>)[field] = c?.value ?? ''
      }
    }
  }
  if (changes.length) emit('save', changes, 'paste')
}

defineExpose({ describe })
</script>

<template>
  <div class="budget-grid-wrap" data-cmp="CMP-F04-01">
    <slot name="over-limit" :flags="flagList">
      <div v-if="flagList.length" class="bg-notice bg-notice-warn" role="status">
        <span class="t">{{ flagList.length }} 个单元格超出新渠道放量规则</span>：{{ flagList.map((f) => `${f.where}（${f.msg}）`).join('、') }}
      </div>
    </slot>
    <div class="budget-grid table-wrap" :class="{ 'is-locked': locked }" :style="{ height }">
      <VGrid
        :columns="gridColumns"
        :source="source"
        :pinned-bottom-source="pinnedBottom"
        :readonly="locked"
        :range="true"
        :use-clipboard="true"
        :apply-on-close="true"
        :row-size="32"
        :row-definitions="rowDefinitions"
        :row-class="ROW_CLASS"
        :resize="true"
        theme="default"
        @beforeedit="onBeforeEdit"
        @beforerangeedit="onBeforeRangeEdit"
      />
    </div>
    <div v-if="errorList.length" class="bg-notice bg-notice-bad" role="alert" data-grid-errors>
      <span class="t">{{ errorList.length }} 个单元格未保存</span>
      <ul class="bg-err-list">
        <li v-for="er in errorList" :key="er.key">{{ er.where }}：{{ er.msg }}</li>
      </ul>
    </div>
  </div>
</template>

<style>
/* RevoGrid 为轻 DOM，样式按 DESIGN.md「数据表格（含类 Excel 填报）」对齐 tokens */
.budget-grid { overflow: hidden; }
.budget-grid revo-grid { height: 100%; font-family: var(--font-body); font-size: var(--text-sm); color: var(--fg); }
.budget-grid revo-grid .rgHeaderCell { background: var(--surface-warm); color: var(--fg-2); font-weight: 600; }
.budget-grid revo-grid .rgCell { padding: 0 10px; border-bottom: 1px solid var(--border-soft); line-height: 32px; }
.budget-grid revo-grid .rgCell.bg-num { text-align: right; font-variant-numeric: tabular-nums; }
.budget-grid revo-grid .rgCell.bg-dim { background: var(--surface-warm); }
.budget-grid revo-grid .rgCell.bg-edit { cursor: cell; background: var(--surface); }
.budget-grid revo-grid .rgCell.bg-locked { color: var(--muted); background: var(--surface-warm); cursor: not-allowed; }
.budget-grid revo-grid .rgCell.bg-flag { box-shadow: inset 0 0 0 2px var(--danger); }
.budget-grid revo-grid .rgCell.bg-error { box-shadow: inset 0 0 0 2px var(--danger); background: color-mix(in oklab, var(--danger), white 94%); color: var(--fg); }
.budget-grid revo-grid .rgRow.row-calc .rgCell { color: var(--fg-2); background: var(--surface-warm); }
.budget-grid revo-grid .rgRow.row-total .rgCell { font-weight: 600; background: var(--surface-warm); border-top: 1px solid var(--border); }
.budget-grid revo-grid .rgRow.row-ref .rgCell { color: var(--fg-2); background: var(--surface-raised); }
.budget-grid.is-locked revo-grid .rgCell { cursor: default; }
.budget-grid revo-grid .rgRow.row-sub .rgCell { display: flex; flex-direction: column; justify-content: center; line-height: 1.3; }
.budget-grid revo-grid .rgRow.row-sub .rgCell.bg-num { align-items: flex-end; }
.budget-grid revo-grid .rgCell .bg-cell-sub { font-size: var(--text-xs); font-weight: 400; color: var(--muted); line-height: 1.2; }
.budget-grid-wrap { display: flex; flex-direction: column; gap: var(--space-3); }
.bg-notice { padding: var(--space-3) var(--space-4); border-radius: var(--radius-md); border: 1px solid var(--border); background: var(--surface); font-size: var(--text-sm); }
.bg-notice .t { font-weight: 600; color: var(--fg); }
.bg-notice-bad { border-color: color-mix(in oklab, var(--danger), white 60%); background: color-mix(in oklab, var(--danger), white 95%); }
.bg-notice-bad .t { color: var(--danger); }
.bg-notice-warn { border-color: color-mix(in oklab, var(--warn), white 60%); background: color-mix(in oklab, var(--warn), white 94%); }
.bg-err-list { margin: var(--space-2) 0 0; padding-left: var(--space-6); max-height: 140px; overflow: auto; }
</style>
