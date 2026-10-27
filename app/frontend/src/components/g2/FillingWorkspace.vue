<script setup lang="ts">
/**
 * 填报工作区（PAGE-F04-02~05、PAGE-F05-01 共用骨架）：页头 / 提示区 / 关键数插槽 / 标签 / 工具栏 / BudgetGrid / 弹窗。
 * - 失焦或整块粘贴 → PATCH /api/filling-units/{id}/cells（每格带基准值，DEC-007）→ 用返回的表格刷新计算行与合计
 * - 越界、冲突写入 errors 标红；超放量写入 flags
 * - 填充全年、下载模板、上传模板、提交（汇率 / 超放量理由 / 调整原因校验由服务端给出）
 * 金额、比率均为服务端字符串，本组件不做任何计算（DEC-005）。
 */
import { computed, onMounted, ref, watch } from 'vue'
import BudgetGrid from '@/components/BudgetGrid.vue'
import PageState from '@/components/PageState.vue'
import type { CellChange, GridColumnDef, GridRow } from '@/components/budgetGrid'
import { api, ApiError, download, upload } from '@/api/client'
import { useUiStore } from '@/stores/ui'
import G2Modal from './G2Modal.vue'
import { errorText, nowClock, toast, UNIT_STATUS_BADGE, type UnitInfo } from './util'
import './g2.css'

export interface GridResponse {
  unit: UnitInfo
  columns: GridColumnDef[]
  rows: GridRow[]
  flags: Record<string, string>
  tab?: string
  actual_months?: string[]
}

interface CellErr {
  row_key: string
  field: string
  code: string
  message: string
}

interface UploadErr {
  sheet?: string
  row: number
  field: string
  message: string
}

const props = withDefaults(
  defineProps<{
    unitId: number
    titlePrefix: string
    dims: string
    loadingText: string
    errorTitle: string
    forbiddenText: string
    tabs?: { key: string; label: string; desc?: string }[]
    gridUrl?: (unitId: number) => string
    /** 单位接口前缀；滚动预测单位为 /api/filling-units/rolling/{版本}/{单位键} */
    apiBase?: string
    fillYear?: boolean
    channelFilter?: boolean
    foot?: string
    footRight?: string
  }>(),
  { tabs: () => [], gridUrl: undefined, apiBase: undefined, fillYear: true, channelFilter: false, foot: '', footRight: '' },
)

const emit = defineEmits<{ loaded: [grid: GridResponse] }>()

const ui = useUiStore()
const grid = ref<GridResponse | null>(null)
const loadError = ref<unknown>(null)
const loading = ref(true)
const tab = ref<string>(props.tabs[0]?.key ?? '')
const errors = ref<Record<string, string>>({})
const conflict = ref<string | null>(null)
const submitError = ref<{ message: string; items: string[] } | null>(null)
const saveState = ref('')
const channel = ref('')
const adjustReason = ref('')
const adjustReasonError = ref('')

const unit = computed(() => grid.value?.unit ?? null)
const locked = computed(() => !unit.value?.editable)
const isAdjust = computed(() => !!unit.value?.adjustment)
const tabInfo = computed(() => props.tabs.find((t) => t.key === tab.value))

const channels = computed(() => {
  const set = new Set<string>()
  for (const r of grid.value?.rows ?? []) if (r.values.channel) set.add(String(r.values.channel))
  return [...set]
})
const rows = computed(() =>
  (grid.value?.rows ?? []).filter((r) => !channel.value || !r.values.channel || r.values.channel === channel.value),
)

const base = computed(() => props.apiBase ?? `/api/filling-units/${props.unitId}`)
const isRolling = computed(() => !!unit.value?.rolling)
function url(): string {
  return props.gridUrl && !props.apiBase ? props.gridUrl(props.unitId) : `${base.value}/grid`
}

function setGrid(g: GridResponse): void {
  grid.value = g
  ui.setCrumbTitle(g.unit.name)
  emit('loaded', g)
}

async function load(): Promise<void> {
  loading.value = grid.value === null
  loadError.value = null
  try {
    setGrid(await api.get<GridResponse>(url(), tab.value ? { tab: tab.value } : undefined))
    if (!adjustReason.value && grid.value?.unit.adjust_reason) adjustReason.value = grid.value.unit.adjust_reason
  } catch (e) {
    loadError.value = e
  } finally {
    loading.value = false
  }
}

async function refresh(): Promise<void> {
  conflict.value = null
  errors.value = {}
  await load()
}

defineExpose({ reload: load, refresh })

onMounted(load)
watch(() => [props.unitId, props.apiBase], () => {
  grid.value = null
  errors.value = {}
  conflict.value = null
  submitError.value = null
  void load()
})
watch(tab, () => {
  channel.value = ''
  void load()
})

function applyErrors(changes: CellChange[], errs: CellErr[]): void {
  const next = { ...errors.value }
  for (const c of changes) delete next[`${c.row_key}::${c.field}`]
  for (const e of errs) next[`${e.row_key}::${e.field}`] = e.message
  errors.value = next
  const c = errs.find((e) => e.code === 'conflict')
  conflict.value = c ? c.message : null
}

async function onSave(changes: CellChange[], source: 'edit' | 'paste'): Promise<void> {
  saveState.value = '正在保存…'
  try {
    const res = await api.patch<{ saved: number; errors: CellErr[]; grid: GridResponse }>(
      `${base.value}/cells`,
      changes,
      { query: tab.value ? { tab: tab.value } : undefined },
    )
    applyErrors(changes, res.errors)
    setGrid(res.grid)
    saveState.value = res.errors.length ? `${res.errors.length} 个单元格未保存` : `已保存 · ${nowClock()}`
    if (source === 'paste') {
      const bad = res.errors.filter((e) => e.code === 'out_of_range').length
      toast(`已粘贴 ${changes.length} 个单元格，其中 ${bad} 个超出取值范围未保存`)
    }
  } catch (e) {
    saveState.value = '保存失败'
    submitError.value = { message: errorText(e), items: [] }
    await load()
  }
}

// ---- 填充全年（AC-F04-06）----
const fillOpen = ref(false)
const fillRow = ref('')
const fillValue = ref('')
const fillError = ref('')
const ratioRows = computed(() =>
  (grid.value?.rows ?? [])
    .filter((r) => r.kind === 'input' && /rate$/.test(r.key.split('|')[1] ?? ''))
    .map((r) => {
      const cols = (grid.value?.columns ?? []).filter((c) => c.kind === 'dim')
      const parts = cols.map((c) => r.values[c.key]).filter(Boolean)
      if (!cols.some((c) => c.key === 'item') && r.values.item) parts.push(r.values.item)
      return { key: r.key, label: parts.join(' · ') }
    }),
)
function openFill(): void {
  fillRow.value = ratioRows.value[0]?.key ?? ''
  fillValue.value = ''
  fillError.value = ''
  fillOpen.value = true
}
async function doFill(): Promise<void> {
  const v = fillValue.value.trim().replace(/%$/, '')
  if (v === '' || Number.isNaN(Number(v)) || Number(v) < 0 || Number(v) > 100) {
    fillError.value = '允许范围：0% 到 100%'
    return
  }
  try {
    const res = await api.post<{ errors: CellErr[]; grid: GridResponse }>(
      `${base.value}/fill-year`,
      { row_key: fillRow.value, value: v },
      { query: tab.value ? { tab: tab.value } : undefined },
    )
    setGrid(res.grid)
    fillOpen.value = false
    const skipped = res.errors.length
    toast(skipped ? `已写入可编辑月份，${skipped} 个已导入实际的月份未改动` : '已填充全年并刷新合计')
  } catch (e) {
    fillError.value = errorText(e)
  }
}

// ---- 模板 ----
const fileInput = ref<HTMLInputElement | null>(null)
const uploadErrors = ref<UploadErr[] | null>(null)
async function downloadTemplate(): Promise<void> {
  try {
    await download(`${base.value}/template`, undefined, `${unit.value?.name ?? '填报'}_模板.xlsx`)
  } catch (e) {
    toast(errorText(e))
  }
}
async function onFile(ev: Event): Promise<void> {
  const input = ev.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  const form = new FormData()
  form.append('file', file)
  try {
    const res = await upload<{ status: string; errors: UploadErr[]; written: number }>(
      `${base.value}/template-upload`,
      form,
    )
    if (res.status === 'failed') {
      uploadErrors.value = res.errors
    } else {
      toast(`校验通过，已写入 ${res.written} 个单元格并刷新合计`)
      await load()
    }
  } catch (e) {
    toast(errorText(e))
  }
}

// ---- 提交 ----
const confirmOpen = ref(false)
const blockMsg = ref<string | null>(null)
const submitting = ref(false)
const submitLabel = computed(() =>
  isAdjust.value ? '提交调整' : isRolling.value ? '提交滚动更新' : unit.value?.status === 'returned' ? '重新提交审核' : '提交审核',
)
const confirmText = computed(() => {
  const reviewer = unit.value?.reviewer?.name ?? '部门负责人'
  if (isAdjust.value)
    return `提交后依次由部门负责人${reviewer}、财务负责人审核；全部单位通过后，CEO 对整次调整一次性终审，通过即生成新的「调整后目标」版本，年初原始目标保持不变。被退回之前不能再修改。`
  if (isRolling.value) return '提交后本季度滚动更新不能再修改；财务负责人发布季度快照时按最新提交的驱动计算。'
  return `提交后状态变为「已提交」，并通知${reviewer}审核。被退回之前，你和其他人都不能再修改本单位内容。`
})
function startSubmit(): void {
  submitError.value = null
  const bad = Object.keys(errors.value).length
  if (bad) {
    blockMsg.value = `仍有 ${bad} 个单元格超出取值范围或未保存，请修正后再提交。`
    return
  }
  if (isAdjust.value && !adjustReason.value.trim()) {
    adjustReasonError.value = '请填写调整原因'
    return
  }
  adjustReasonError.value = ''
  confirmOpen.value = true
}
async function doSubmit(): Promise<void> {
  if (submitting.value) return
  submitting.value = true
  try {
    await api.post(`${base.value}/submit`, isAdjust.value ? { adjust_reason: adjustReason.value } : {})
    confirmOpen.value = false
    toast(`已提交，已通知${unit.value?.reviewer?.name ?? '审核人'}审核`)
    await load()
  } catch (e) {
    confirmOpen.value = false
    const details = e instanceof ApiError ? e.details : {}
    const items: string[] = []
    for (const k of ['months', 'currencies'] as const) {
      const v = details[k]
      if (Array.isArray(v)) items.push(...v.map(String))
    }
    if (e instanceof ApiError && e.code === 'adjust_reason_required') adjustReasonError.value = e.message
    submitError.value = { message: errorText(e), items }
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="g2">
    <PageState v-if="loading" state="loading" :rows="8" />
    <PageState
      v-else-if="loadError"
      :error="loadError"
      :title="loadError instanceof ApiError && loadError.isForbidden ? '无权限' : errorTitle"
      :description="loadError instanceof ApiError && loadError.isForbidden ? forbiddenText : '已填写并保存的内容不会丢失。'"
      @retry="load"
    />
    <template v-else-if="grid && unit">
      <div class="page-head">
        <div>
          <h1 class="page-title">{{ titlePrefix }} · {{ unit.name }}</h1>
          <p class="sub">
            <template v-if="unit.adjustment">{{ unit.adjustment.name }} · 调整模式</template>
            <template v-else-if="unit.rolling">{{ unit.rolling.name }} · 只开放本季度及以后月份</template>
            <template v-else-if="unit.task">{{ unit.task.name }} · 截止 {{ unit.task.deadline }}</template>
            · {{ dims }}
          </p>
        </div>
        <div class="toolbar">
          <span :class="UNIT_STATUS_BADGE[unit.status] ?? 'badge'" data-unit-status>{{ unit.status_label }}</span>
          <span class="save-state" aria-live="polite">{{ saveState }}</span>
        </div>
      </div>

      <slot name="info" />

      <div v-if="unit.adjustment" class="notice notice-info" role="status">
        <span class="t">调整模式 · {{ unit.adjustment.name }}</span> ·
        <template v-if="grid.actual_months?.length">{{ grid.actual_months.join('、') }} 已导入金蝶实际，不可修改；</template>
        提交时须填写调整原因，经部门负责人、财务负责人审核后，由 CEO 对整次调整一次性终审。
      </div>
      <div v-if="unit.status === 'returned'" class="notice notice-bad" role="status" data-returned>
        <span class="t">已退回</span> · {{ unit.returned_by }} {{ unit.returned_at }}：{{ unit.return_reason }}
      </div>
      <div v-else-if="unit.locked" class="notice notice-info" role="status" data-locked>
        <span class="t">{{ unit.status === 'approved' ? '已通过，内容已锁定' : '已提交，内容已锁定' }}</span> ·
        <template v-if="unit.submitted_at">{{ unit.submitted_at }} 提交</template>
        <template v-if="unit.status === 'submitted' && !isRolling">，等待{{ unit.reviewer?.name }}审核</template>；被退回之前任何人不能修改本单位内容。
      </div>
      <div v-if="conflict" class="notice notice-bad" role="alert" data-conflict>
        {{ conflict }} <button type="button" class="btn" @click="refresh">刷新</button>
      </div>
      <div v-if="submitError" class="notice notice-bad" role="alert" data-submit-error>
        <span class="t">{{ submitError.message }}</span>
        <ul v-if="submitError.items.length" class="err-list">
          <li v-for="it in submitError.items" :key="it">{{ it }}</li>
        </ul>
      </div>

      <slot name="kpis" />

      <div v-if="tabs.length" class="tabs" role="tablist">
        <a
          v-for="t in tabs"
          :key="t.key"
          class="tab"
          href="#"
          role="tab"
          :aria-selected="tab === t.key ? 'true' : 'false'"
          @click.prevent="tab = t.key"
          >{{ t.label }}</a
        >
      </div>

      <div class="toolbar" style="justify-content: space-between; margin-bottom: var(--space-3)">
        <div class="toolbar">
          <button v-if="fillYear && ratioRows.length" class="btn" type="button" :disabled="locked" @click="openFill">填充全年</button>
          <template v-if="!isRolling">
            <button class="btn" type="button" @click="downloadTemplate">下载填报模板</button>
            <button class="btn" type="button" :disabled="locked" @click="fileInput?.click()">上传填报文件</button>
          </template>
          <input ref="fileInput" type="file" accept=".xlsx" hidden @change="onFile" />
          <slot name="toolbar" />
          <label v-if="channelFilter && channels.length" class="sub" style="margin: 0">
            渠道
            <select v-model="channel" class="select">
              <option value="">全部渠道</option>
              <option v-for="c in channels" :key="c" :value="c">{{ c }}</option>
            </select>
          </label>
        </div>
        <button v-if="unit.editable" class="btn btn-primary" type="button" data-submit @click="startSubmit">{{ submitLabel }}</button>
      </div>

      <div v-if="unit.adjustment && unit.editable" class="field">
        <label for="adj-reason">调整原因<span class="req">*</span></label>
        <textarea id="adj-reason" v-model="adjustReason" class="input" :aria-invalid="adjustReasonError ? 'true' : 'false'"></textarea>
        <div v-if="adjustReasonError" class="field-error">{{ adjustReasonError }}</div>
      </div>

      <p v-if="tabInfo?.desc" class="sub" style="margin-bottom: var(--space-3)">{{ tabInfo.desc }}</p>

      <BudgetGrid :columns="grid.columns" :rows="rows" :locked="locked" :errors="errors" :flags="grid.flags" @save="onSave" />
      <div class="grid-foot">
        <span>{{ foot || '白底单元格可编辑：失焦即保存并刷新合计；可从 Excel 复制整块粘贴。比率按百分数录入，输入 15 即 15%。' }}</span>
        <span>{{ footRight || '金额四舍五入保留 2 位小数，合计 = 明细显示值之和' }}</span>
      </div>

      <slot name="after" />
    </template>

    <G2Modal v-if="fillOpen" title="填充全年" @close="fillOpen = false">
      <div class="field">
        <label for="fill-row">维度组合与比率</label>
        <select id="fill-row" v-model="fillRow" class="select">
          <option v-for="r in ratioRows" :key="r.key" :value="r.key">{{ r.label }}</option>
        </select>
      </div>
      <div class="field">
        <label for="fill-val">比率（%）<span class="req">*</span></label>
        <input id="fill-val" v-model="fillValue" class="input" inputmode="decimal" placeholder="例如 30" />
        <div v-if="fillError" class="field-error">{{ fillError }}</div>
      </div>
      <p class="sub">写入该组合 12 个月中尚未提交（可编辑）的月份。</p>
      <template #actions>
        <button class="btn" type="button" @click="fillOpen = false">取消</button>
        <button class="btn btn-primary" type="button" data-fill-ok @click="doFill">填充</button>
      </template>
    </G2Modal>

    <G2Modal v-if="uploadErrors" title="校验未通过，本文件没有写入任何数据" wide @close="uploadErrors = null">
      <p>共 {{ uploadErrors.length }} 处错误，请修正后重新上传：</p>
      <ul class="err-list">
        <li v-for="(e, i) in uploadErrors" :key="i">
          <template v-if="e.sheet">{{ e.sheet }} · </template>第 {{ e.row }} 行 · {{ e.field }} · {{ e.message }}
        </li>
      </ul>
      <template #actions>
        <button class="btn btn-primary" type="button" @click="uploadErrors = null">知道了</button>
      </template>
    </G2Modal>

    <G2Modal v-if="confirmOpen" :title="`${submitLabel}？`" @close="confirmOpen = false">
      <p>{{ confirmText }}</p>
      <template #actions>
        <button class="btn" type="button" @click="confirmOpen = false">取消</button>
        <button class="btn btn-primary" type="button" data-confirm-submit :disabled="submitting" @click="doSubmit">确认提交</button>
      </template>
    </G2Modal>

    <G2Modal v-if="blockMsg" title="还不能提交" @close="blockMsg = null">
      <p>{{ blockMsg }}</p>
      <template #actions>
        <button class="btn btn-primary" type="button" @click="blockMsg = null">知道了</button>
      </template>
    </G2Modal>
  </div>
</template>
