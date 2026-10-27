<script setup lang="ts">
/**
 * PAGE-F09-01 实际数导入：金蝶月度 / BI 双月 / 历史金蝶；校验未通过逐行列出问题（整份不写入）；
 * 校验通过显示摘要、覆盖提示与二次确认；导入记录保留被替换文件（API-F09-01~04，DEC-008）。
 * 批次结构的 overwrite 为列表（BI 一份文件可覆盖多个月份），因此本页不复用 ImportResultPanel。
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { api, ApiError, upload } from '@/api/client'
import PageState from '@/components/PageState.vue'
import G3Modal from '@/components/g3/G3Modal.vue'
import { errorText, useToast } from '@/components/g3/useG3'
import '@/components/g3/g3.css'

type Tab = 'kingdee' | 'bi' | 'kingdee-history'
interface Issue { row: number | string; type: string; code: string; name: string | null; action: string | null; link: string | null }
interface Overwrite { periods: string[]; file_name: string; imported_by: string; imported_at: string | null }
interface Batch {
  id: number; source: string; status: string; status_label: string; file_name: string; row_count: number | null
  issues: Issue[]; issue_counts?: { type: string; count: number }[]; unmapped_skus?: string[]
  needs_overwrite: boolean; overwrite: Overwrite[]; periods: string[]; validation_seconds: string | null
  summary: null | {
    revenue_total_display?: string; cost_total_display?: string; unassigned?: { code: string; name: string; rows: number; amount_display: string }[]
    unassigned_total_display?: string; sku_count?: number; rule?: string
    preview?: { month: string; store: string; site: string; category: string; is_new_label: string; qty: string; sales_local_display: string }[]
  }
  alerts?: { created: number; updated: number }
}
interface RecordRow {
  id: number; source: string; source_label: string; period_text: string; file_name: string; row_count: number | null
  imported_by: string; imported_at: string | null; status: string; status_label: string
  replaced: { period: string; by_file_name: string; by: string; at: string | null }[]
}
interface Overview {
  records: RecordRow[]; kingdee_latest: string | null; bi_latest: string | null
  history_grid: { month: string; imported: boolean }[]; history_imported: number; has_records: boolean; can_upload: boolean
}

const TABS: { key: Tab; label: string; title: string; cols: string }[] = [
  { key: 'kingdee', label: '金蝶月度', title: '上传金蝶月度实际', cols: '必需列：期间（YYYY-MM）、金蝶科目、部门、平台/店铺、站点、发生额；可选列：科目名称、客户、摘要。科目余额表或利润表导出均可。' },
  { key: 'bi', label: 'BI 双月', title: '上传 BI 双月销售数据', cols: '必需列：月份（YYYY-MM）、店铺、站点、SKU、销量、本币销售额、币种、广告费、平台费用。一份文件可含多个月份。' },
  { key: 'kingdee-history', label: '历史金蝶（最多 24 个月）', title: '上传历史金蝶数据', cols: '与金蝶月度同一模板，单个文件最多包含 24 个期间，按期间逐月入库。' },
]
const tab = ref<Tab>('kingdee')
const overview = ref<Overview | null>(null)
const loading = ref(true)
const error = ref<unknown>(null)
const file = ref<File | null>(null)
const fileInput = ref<HTMLInputElement | null>(null)
const phase = ref<'idle' | 'uploading' | 'checking' | 'failed' | 'passed' | 'confirming'>('idle')
const batch = ref<Batch | null>(null)
const actionError = ref('')
const confirmOpen = ref(false)
const { toast, show } = useToast()
let timer: ReturnType<typeof setTimeout> | null = null

const current = computed(() => TABS.find((t) => t.key === tab.value)!)
const latestText = computed(() => {
  const o = overview.value
  if (!o) return ''
  const p = tab.value === 'bi' ? o.bi_latest : o.kingdee_latest
  return p ? `最近导入期间：${p}` : '尚未导入'
})
const overwriteText = computed(() =>
  (batch.value?.overwrite ?? []).map((o) => `${o.periods.join('、')} 已有导入数据：${o.file_name}（${o.imported_by}，${o.imported_at}）`).join('；'),
)
const records = computed(() => (overview.value?.records ?? []).filter((r) =>
  tab.value === 'bi' ? r.source === 'bi' : r.source !== 'bi'))

async function loadOverview(): Promise<void> {
  error.value = null
  try {
    overview.value = await api.get<Overview>('/api/imports')
  } catch (e) {
    error.value = e
  } finally {
    loading.value = false
  }
}
onMounted(loadOverview)
onBeforeUnmount(() => timer && clearTimeout(timer))

function switchTab(t: Tab): void {
  if (phase.value === 'checking' || phase.value === 'confirming') return
  tab.value = t
  reset()
}
function reset(): void {
  if (timer) clearTimeout(timer)
  phase.value = 'idle'
  batch.value = null
  file.value = null
  actionError.value = ''
  if (fileInput.value) fileInput.value.value = ''
}
function onPick(e: Event): void {
  file.value = (e.target as HTMLInputElement).files?.[0] ?? null
}

function apply(b: Batch): void {
  batch.value = b
  if (b.status === 'validating') {
    phase.value = 'checking'
    timer = setTimeout(poll, 2000)
  } else if (b.status === 'failed') {
    phase.value = 'failed'
  } else if (b.status === 'passed') {
    phase.value = 'passed'
  } else {
    phase.value = 'failed'
    actionError.value = b.status_label
  }
}
async function poll(): Promise<void> {
  if (!batch.value) return
  try {
    apply(await api.get<Batch>(`/api/imports/${batch.value.id}`))
  } catch (e) {
    phase.value = 'idle'
    actionError.value = errorText(e)
  }
}
async function check(): Promise<void> {
  if (!file.value) {
    actionError.value = '请先选择 Excel 文件'
    return
  }
  actionError.value = ''
  phase.value = 'uploading'
  const form = new FormData()
  form.append('file', file.value)
  form.append('source', tab.value)
  try {
    const created = await upload<{ id: number }>('/api/imports', form)
    batch.value = { id: created.id } as Batch
    phase.value = 'checking'
    await poll()
  } catch (e) {
    phase.value = 'idle'
    actionError.value = errorText(e)
  }
}
async function discard(): Promise<void> {
  if (!batch.value) return
  try {
    await api.post(`/api/imports/${batch.value.id}/discard`)
    show('已放弃本次上传，未写入任何数据')
  } catch (e) {
    show(errorText(e))
  }
  reset()
}
function onImportClick(): void {
  if (batch.value?.needs_overwrite) confirmOpen.value = true
  else void doImport(false)
}
async function doImport(overwrite: boolean): Promise<void> {
  if (!batch.value) return
  confirmOpen.value = false
  phase.value = 'confirming'
  try {
    const done = await api.post<Batch>(`/api/imports/${batch.value.id}/confirm`, { overwrite })
    const alerts = done.alerts ? `；预警评估新增 ${done.alerts.created} 条、更新 ${done.alerts.updated} 条` : ''
    show(`已导入 ${done.file_name}${alerts}`)
    reset()
    await loadOverview()
  } catch (e) {
    phase.value = 'passed'
    actionError.value = errorText(e)
  }
}
function rowText(row: number | string): string {
  return typeof row === 'number' ? `第 ${row.toLocaleString('en-US')} 行` : row
}
</script>

<template>
  <div data-page-id="PAGE-F09-01" class="g3">
    <div class="page-head"><h1 class="page-title">实际数导入</h1></div>
    <PageState v-if="loading" state="loading" />
    <PageState v-else-if="error" :error="error" :description="error instanceof ApiError && error.isForbidden ? '实际数导入仅对财务BP开放。如需查看实际数，请前往报表页面。' : undefined" @retry="loadOverview" />
    <template v-else-if="overview">
      <div class="tabs" role="tablist">
        <a v-for="t in TABS" :key="t.key" class="tab" href="#" role="tab" :aria-selected="tab === t.key" @click.prevent="switchTab(t.key)">{{ t.label }}</a>
      </div>

      <div v-if="!overview.has_records && phase === 'idle' && tab !== 'kingdee-history'" class="notice section">
        还没有导入过实际数。建议先导入最多 24 个月的历史金蝶数据，用于历史参考和同比；之后每月关账后导入金蝶月度实际，每两个月导入 BI 数据。
        <button class="link" type="button" @click="switchTab('kingdee-history')">导入历史金蝶数据</button>
      </div>

      <section v-if="overview.can_upload" class="card section" aria-labelledby="up-t">
        <div class="row" style="margin-bottom: var(--space-3)">
          <h2 id="up-t" class="section-title" style="margin: 0">{{ current.title }}</h2>
          <span class="spacer"></span>
          <span class="small muted">{{ latestText }}</span>
        </div>
        <div class="upload">
          <div>
            <label class="drop">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><path d="M12 16V4m0 0-4 4m4-4 4 4M4 15v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3" /></svg>
              <span>选择 Excel 文件（.xlsx / .xls）<br><span class="small muted">5 万行以内 60 秒内给出校验结果</span></span>
              <input ref="fileInput" type="file" accept=".xlsx,.xls" aria-label="选择 Excel 文件" :disabled="phase === 'checking' || phase === 'uploading'" @change="onPick">
            </label>
            <div class="cols">{{ current.cols }}</div>
          </div>
          <button class="btn btn-primary" type="button" :disabled="phase === 'checking' || phase === 'uploading' || phase === 'confirming'" @click="check">
            {{ phase === 'checking' || phase === 'uploading' ? '正在校验…' : '上传并校验' }}
          </button>
        </div>
        <p v-if="actionError && phase !== 'passed'" class="field-error" role="alert">{{ actionError }}</p>
      </section>
      <div v-else class="notice section">实际数导入仅对财务BP开放；你可以查看导入记录。</div>

      <section v-if="phase === 'checking' || phase === 'uploading' || phase === 'confirming'" class="section" aria-busy="true">
        <div class="card"><div class="row"><div class="skeleton" style="width: 220px"></div>
          <span class="small muted">{{ phase === 'confirming' ? '正在写入并评估预警…' : `正在校验 ${file?.name ?? ''}…` }}</span></div></div>
      </section>

      <section v-if="phase === 'failed' && batch" class="section" aria-labelledby="fail-t">
        <div class="notice bad" role="alert">
          <strong id="fail-t">校验未通过，本文件没有写入任何数据。</strong>
          共 {{ batch.issues.length }} 个问题行<template v-if="batch.unmapped_skus?.length">、{{ batch.unmapped_skus.length }} 个 SKU 不在 SKU 对照表中</template>。修正后请重新上传整份文件。
        </div>
        <div class="type-sum">
          <span v-for="c in batch.issue_counts ?? []" :key="c.type" class="badge badge-bad">{{ c.type }} {{ c.count }}</span>
        </div>
        <div class="table-wrap">
          <table class="table">
            <thead><tr><th>行号</th><th>问题类型</th><th>{{ tab === 'bi' ? '涉及名称或 SKU' : '涉及编码或名称' }}</th><th>处理方式</th></tr></thead>
            <tbody>
              <tr v-for="(it, i) in batch.issues" :key="i">
                <td class="num">{{ rowText(it.row) }}</td>
                <td>{{ it.type }}</td>
                <td class="mono">{{ it.name ?? '—' }}</td>
                <td><RouterLink v-if="it.link" class="link" :to="it.link">{{ it.action }}</RouterLink><span v-else>{{ it.action ?? '—' }}</span></td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section v-if="phase === 'passed' && batch" class="section" aria-labelledby="pass-t">
        <div class="notice good"><strong id="pass-t">校验通过，尚未写入。</strong>请核对下方摘要后确认导入。</div>
        <div class="grid-2" style="margin-top: var(--space-4)">
          <div class="card">
            <h3 class="section-title">导入摘要</h3>
            <dl class="kv">
              <dt>期间</dt><dd class="num">{{ batch.periods.length > 2 ? `${batch.periods[0]} 至 ${batch.periods[batch.periods.length - 1]}（${batch.periods.length} 个期间）` : batch.periods.join('、') }}</dd>
              <dt>文件</dt><dd>{{ batch.file_name }}</dd>
              <dt>行数</dt><dd class="num">{{ batch.row_count?.toLocaleString('en-US') }}</dd>
              <template v-if="batch.source !== 'bi'">
                <dt>收入合计</dt><dd class="num">{{ batch.summary?.revenue_total_display }}</dd>
                <dt>成本费用合计</dt><dd class="num">{{ batch.summary?.cost_total_display }}</dd>
              </template>
              <template v-else>
                <dt>SKU 数</dt><dd class="num">{{ batch.summary?.sku_count }}</dd>
                <dt>新老品判定</dt><dd>{{ batch.summary?.rule }}</dd>
              </template>
              <dt>校验用时</dt><dd class="num">{{ batch.validation_seconds }} 秒</dd>
            </dl>
          </div>
          <div class="card">
            <template v-if="batch.source !== 'bi'">
              <h3 class="section-title">未归属渠道</h3>
              <p class="small muted" style="margin-top: 0">没有平台/店铺辅助核算、且不属于部门费用科目的成本费用行，计入该月「未归属渠道」，在渠道×站点偏差报告中单列。</p>
              <table v-if="batch.summary?.unassigned?.length" class="table">
                <thead><tr><th>金蝶科目</th><th class="num">行数</th><th class="num">金额</th></tr></thead>
                <tbody>
                  <tr v-for="u in batch.summary.unassigned" :key="u.code"><td>{{ u.code }} {{ u.name }}</td><td class="num">{{ u.rows }}</td><td class="num">{{ u.amount_display }}</td></tr>
                  <tr class="total"><td>合计</td><td></td><td class="num">{{ batch.summary.unassigned_total_display }}</td></tr>
                </tbody>
              </table>
              <p v-else class="small muted">本文件没有未归属渠道的行。</p>
            </template>
            <template v-else>
              <h3 class="section-title">归集预览（月 × 店铺 × 站点 × 品类 × 新品/老品）</h3>
              <div class="table-wrap" style="max-height: 280px">
                <table class="table">
                  <thead><tr><th>月</th><th>店铺 · 站点</th><th>品类</th><th>新/老</th><th class="num">销量</th><th class="num">本币销售额</th></tr></thead>
                  <tbody>
                    <tr v-for="(p, i) in batch.summary?.preview ?? []" :key="i">
                      <td class="num">{{ p.month }}</td><td>{{ p.store }} · {{ p.site }}</td><td>{{ p.category }}</td>
                      <td>{{ p.is_new_label }}</td><td class="num">{{ p.qty }}</td><td class="num">{{ p.sales_local_display }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </template>
          </div>
        </div>
        <div v-if="batch.needs_overwrite" class="notice warn" style="margin-top: var(--space-4)">{{ overwriteText }}。确认后用新文件替换{{ batch.source === 'bi' ? '这些月份的全部 BI 实际数' : '该期间的全部金蝶实际数' }}，原导入记录保留并标记「已被替换」。</div>
        <p v-if="actionError" class="field-error" role="alert">{{ actionError }}</p>
        <div class="row" style="margin-top: var(--space-4)">
          <span class="spacer"></span>
          <button class="btn" type="button" @click="discard">放弃本次上传</button>
          <button class="btn btn-primary" type="button" @click="onImportClick">{{ batch.needs_overwrite ? '确认覆盖导入' : '确认导入' }}</button>
        </div>
      </section>

      <section v-if="tab === 'kingdee-history'" class="card section" aria-labelledby="his-t">
        <h3 id="his-t" class="section-title">历史期间入库情况（{{ overview.history_grid[0]?.month }} 至 {{ overview.history_grid[overview.history_grid.length - 1]?.month }}）</h3>
        <div class="months">
          <div v-for="g in overview.history_grid" :key="g.month" :class="{ ok: g.imported }" :title="g.imported ? '已入库' : '未导入'">{{ g.month }}<br>{{ g.imported ? '已入库' : '未导入' }}</div>
        </div>
        <p class="small muted" style="margin-bottom: 0">按期间逐月入库，用于部门费用历史参考和同比计算。单个文件最多包含 24 个期间。已入库 {{ overview.history_imported }} / 24。</p>
      </section>

      <section class="section" aria-labelledby="rec-t">
        <div class="row" style="margin-bottom: var(--space-3)">
          <h2 id="rec-t" class="section-title" style="margin: 0">导入记录</h2>
          <span class="small muted">被覆盖的导入保留原文件名、导入人和导入时间，不能删除</span>
        </div>
        <div class="table-wrap">
          <table class="table">
            <thead><tr><th>类型</th><th class="num">期间</th><th>文件名</th><th class="num">行数</th><th>导入人</th><th class="num">导入时间</th><th>状态</th></tr></thead>
            <tbody>
              <tr v-for="r in records" :key="r.id">
                <td>{{ r.source_label }}</td><td class="num">{{ r.period_text }}</td><td>{{ r.file_name }}</td>
                <td class="num">{{ r.row_count?.toLocaleString('en-US') ?? '—' }}</td><td>{{ r.imported_by }}</td>
                <td class="num">{{ r.imported_at ?? '—' }}</td>
                <td class="w-n">
                  <span class="badge" :class="r.status === 'effective' ? 'badge-good' : ''">{{ r.status_label }}</span>
                  <div v-for="x in r.replaced" :key="x.period" class="small muted">{{ x.period }} 被 {{ x.by }} 于 {{ x.at }} 以「{{ x.by_file_name }}」覆盖</div>
                </td>
              </tr>
              <tr v-if="!records.length"><td colspan="7" class="muted">还没有导入记录</td></tr>
            </tbody>
          </table>
        </div>
      </section>
    </template>

    <G3Modal :open="confirmOpen" title="确认覆盖" @close="confirmOpen = false">
      <p>{{ overwriteText }}。确认后用新文件替换这些期间的全部数据。</p>
      <p class="small muted">原导入记录会保留在导入记录中，状态改为「已被替换」。导入完成后系统会用全部生效的预警规则重新评估受影响月份。</p>
      <template #actions>
        <button class="btn" type="button" @click="confirmOpen = false">取消</button>
        <button class="btn btn-primary" type="button" @click="doImport(true)">确认覆盖</button>
      </template>
    </G3Modal>
    <div v-if="toast" class="toast" role="status">{{ toast }}</div>
  </div>
</template>

<style scoped>
.upload { display: grid; grid-template-columns: 1fr auto; gap: var(--space-4); align-items: end; }
.drop { border: 1px dashed var(--border); border-radius: var(--radius-lg); padding: var(--space-5); background: var(--surface-warm); display: flex; align-items: center; gap: var(--space-3); transition: border-color var(--motion-fast) var(--ease-standard), background var(--motion-fast) var(--ease-standard); }
.drop:hover { border-color: var(--muted); background: var(--surface-raised); }
.drop:focus-within { border-color: var(--accent); box-shadow: var(--focus-ring); }
.drop svg { width: 28px; height: 28px; color: var(--muted); flex: none; }
.drop input[type=file] { font-size: var(--text-sm); }
.cols { font-size: var(--text-xs); color: var(--muted); margin-top: var(--space-2); }
.months { display: grid; grid-template-columns: repeat(12, minmax(0, 1fr)); gap: var(--space-1); }
.months div { border: 1px solid var(--border-soft); border-radius: var(--radius-sm); padding: var(--space-1); text-align: center; font-size: var(--text-xs); font-variant-numeric: tabular-nums; }
.months div.ok { background: color-mix(in oklab, var(--success), white 92%); color: var(--success); }
.type-sum { display: flex; gap: var(--space-2); flex-wrap: wrap; margin: var(--space-3) 0; }
</style>
