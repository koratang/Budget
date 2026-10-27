<script setup lang="ts">
/**
 * 渠道×站点偏差 PAGE-F10-02（API-F10-02 GET /api/reports/channel-site、API-F10-05、API-F14-01）
 * - 对比基准三选一，默认最新调整后目标（AC-F10-01）；每行收入、毛利、毛利率的预算 / 实际 / 差额 / 达成率（AC-F10-02）
 * - 收入差额拆分：量差、价差、汇率差、口径差（AC-F10-03、DEC-024）；展开明细含各项费用与费率差（AC-F10-04）
 * - BI 未到：拆分列组与费率三列整体隐藏并提示（AC-F10-05）；B 端按客户分组（AC-F10-12）；未归属渠道单列
 * - 数值全部来自后端（十进制字符串），前端只格式化
 */
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, ApiError } from '@/api/client'
import AchievementBar from '@/components/AchievementBar.vue'
import ExportButton from '@/components/ExportButton.vue'
import PageState from '@/components/PageState.vue'
import NoteCell from '@/components/g4/NoteCell.vue'
import NoteDialog from '@/components/g4/NoteDialog.vue'
import { money, moneySigned, pct, pp, tone } from '@/components/g4/format'
import type { NoteKey, NoteTarget, VarianceNote } from '@/components/g4/types'
import { useUserStore } from '@/stores/user'
import '@/components/g4/report.css'

interface Metric { budget: string | null; actual: string | null; diff: string | null; rate: string | null }
interface Line extends Metric {
  key: string
  label: string
  direction: 'higher-better' | 'lower-better'
  budget_rate: string | null
  actual_rate: string | null
  rate_diff: string | null
}
interface Split {
  volume: string | null; price: string | null; fx: string | null; basis: string | null; total?: string | null
  missing_fx: boolean; missing_fx_text: string | null
  budget_qty?: string | null; budget_net_price?: string | null; actual_qty?: string | null
  actual_net_price?: string | null; budget_fx?: string | null; actual_fx?: string | null
}
interface Row {
  kind: 'store' | 'b2b' | 'unassigned'
  key: string
  note_key: NoteKey
  name: string
  channel: string | null
  site: string | null
  currency: string | null
  department?: string
  is_new_channel: boolean
  revenue: Metric
  revenue_local_budget: string | null
  revenue_local_actual: string | null
  split: Split | null
  gross_profit: Metric
  gross_margin: { budget: string | null; actual: string | null; diff_pp: string | null }
  lines: Line[]
  note: VarianceNote | null
}
interface Report {
  empty: boolean
  message?: string
  month: string | null
  months: string[]
  baseline: string
  baseline_options: { value: string; label: string }[]
  baseline_label?: string
  bi_latest: string | null
  bi_available?: boolean
  bi_notice?: string | null
  can_edit_note: boolean
  channel?: string
  channel_options?: { value: string; label: string }[]
  fx?: { budget: Record<string, string | null>; actual: Record<string, string | null> }
  rows?: Row[]
  b2b_rows?: Row[]
  unassigned?: Row | null
  total?: { label: string; revenue: Metric; split: Split | null; gross_profit: Metric; gross_margin: Row['gross_margin'] }
}

const SYM: Record<string, string> = { USD: '$', CAD: 'C$', EUR: '€', GBP: '£', CNY: '¥' }
const route = useRoute()
const router = useRouter()
const user = useUserStore()

const data = ref<Report | null>(null)
const loading = ref(true)
const error = ref<unknown>(null)
const open = ref<Record<string, boolean>>({})
const noteTarget = ref<NoteTarget | null>(null)

const q = (k: string) => (typeof route.query[k] === 'string' ? (route.query[k] as string) : undefined)
const month = ref<string | undefined>(q('month'))
const baseline = ref<string>(q('base') ?? 'adj')
const channel = ref<string>(q('channel') ?? 'all')

const isBP = computed(() => user.me?.roles.includes('finance_bp') ?? false)
const bi = computed(() => data.value?.bi_available ?? false)
const colCount = computed(() => (bi.value ? 21 : 17))
const exportFilters = computed(() => ({ month: data.value?.month, baseline: baseline.value, channel: channel.value }))
const ready = computed(() => !loading.value && !error.value && !!data.value && !data.value.empty)

function local(v: string | null, cur: string | null): string {
  if (v === null || !cur) return '—'
  return `${SYM[cur] ?? ''} ${money(v)} ${cur}`.trim()
}

async function load(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    const res = await api.get<Report>('/api/reports/channel-site', {
      month: month.value,
      baseline: baseline.value,
      channel: channel.value === 'all' ? undefined : channel.value,
    })
    data.value = res
    month.value = res.month ?? undefined
    if (res.channel) channel.value = res.channel
    void router.replace({ query: { ...route.query, month: res.month ?? undefined, base: baseline.value,
      channel: channel.value === 'all' ? undefined : channel.value } })
  } catch (e) {
    error.value = e
    data.value = null
  } finally {
    loading.value = false
  }
}

onMounted(load)

function toggle(key: string): void {
  open.value = { ...open.value, [key]: !open.value[key] }
}

function openNote(row: Row): void {
  if (!data.value?.month) return
  noteTarget.value = { report_type: 'channel-site', month: data.value.month, ...row.note_key, label: row.name, note: row.note }
}

function onSaved(note: VarianceNote): void {
  const t = noteTarget.value
  const d = data.value
  if (t && d) {
    for (const r of [...(d.rows ?? []), ...(d.b2b_rows ?? []), ...(d.unassigned ? [d.unassigned] : [])]) {
      if (r.note_key.object_type === t.object_type && r.note_key.object_key === t.object_key) r.note = note
    }
  }
  noteTarget.value = null
}

const fxText = computed(() => {
  const fx = data.value?.fx
  if (!fx) return { budget: '', actual: '' }
  const cur = Object.keys(fx.budget)
  return {
    budget: cur.map((c) => `${c} ${money(fx.budget[c], 4)}`).join(' · '),
    actual: cur.map((c) => `${c} ${fx.actual[c] === null ? '未录入' : money(fx.actual[c], 4)}`).join(' · '),
  }
})

const forbiddenText = '你没有被分配任何渠道或店铺，无法查看渠道×站点偏差。如需查看请联系财务负责人分配数据范围。'
const isForbidden = computed(() => error.value instanceof ApiError && error.value.isForbidden)
</script>

<template>
  <div data-page-id="PAGE-F10-02" class="g4-report">
    <div class="page-head">
      <div>
        <h1 class="page-title">渠道×站点偏差</h1>
        <div class="meta">按店铺站点逐行对比预算与金蝶实际 · 金额单位：人民币元</div>
      </div>
      <ExportButton class="btn-primary" view="report-channel" :filters="exportFilters" :disabled="!ready" />
    </div>

    <div v-if="!isForbidden" class="filters">
      <label>月份
        <select v-model="month" class="select" :disabled="loading" @change="load">
          <option v-for="m in data?.months ?? []" :key="m" :value="m">{{ m }}</option>
          <option v-if="month && !(data?.months ?? []).includes(month)" :value="month">{{ month }}</option>
        </select>
      </label>
      <label>对比基准
        <select v-model="baseline" class="select" :disabled="loading" @change="load">
          <option v-for="o in data?.baseline_options ?? [{ value: 'orig', label: '年初原始目标' }, { value: 'adj', label: '最新调整后目标' }, { value: 'roll', label: '最新滚动预测' }]" :key="o.value" :value="o.value">{{ o.label }}</option>
        </select>
      </label>
      <label>渠道
        <select v-model="channel" class="select" :disabled="loading" @change="load">
          <option v-for="o in data?.channel_options ?? [{ value: 'all', label: '全部' }]" :key="o.value" :value="o.value">{{ o.label }}</option>
        </select>
      </label>
    </div>

    <PageState v-if="loading" state="loading" :rows="6" />
    <PageState v-else-if="isForbidden" state="forbidden" :description="forbiddenText" />
    <PageState v-else-if="error" :error="error" title="偏差报告加载失败" description="服务器未返回数据，可能是网络中断。请重试。" @retry="load" />
    <PageState v-else-if="data?.empty" :title="data.message ?? '还没有金蝶实际'" description="该月金蝶实际导入后生成偏差报告。">
      <template #action>
        <RouterLink v-if="isBP" class="btn btn-primary" :to="{ name: 'import' }">去导入实际数</RouterLink>
      </template>
    </PageState>

    <template v-else-if="data">
      <div class="info-strip">
        <span>对比基准：<b>{{ data.baseline_label }}</b></span>
        <span>金蝶实际：<b>{{ data.month }}</b></span>
        <span>BI 数据截至：<b>{{ data.bi_latest ?? '—' }}</b></span>
        <span>预算汇率：{{ fxText.budget }}</span>
        <span>{{ data.month }} 当月平均汇率：{{ fxText.actual }}</span>
      </div>
      <div v-if="!bi" class="bi-banner" role="status">
        {{ data.bi_notice }}。本月只显示金额差异，拆分区域（含费率差）隐藏。
      </div>

      <div class="table-wrap">
        <table class="table" data-testid="channel-table">
          <thead>
            <tr>
              <th rowspan="2" class="dim-h">店铺</th>
              <th rowspan="2">渠道</th>
              <th rowspan="2">站点</th>
              <th class="grp" colspan="6">收入</th>
              <th v-if="bi" class="grp" colspan="4">收入差额拆分</th>
              <th class="grp" colspan="4">毛利</th>
              <th class="grp" colspan="3">毛利率</th>
              <th class="grp" rowspan="2">偏差说明</th>
            </tr>
            <tr>
              <th class="num sep">预算</th><th class="num">实际</th><th class="num">实际（本币）</th><th class="num">差额</th><th class="num">达成率</th><th>达成条</th>
              <template v-if="bi"><th class="num sep">量差</th><th class="num">价差</th><th class="num">汇率差</th><th class="num">口径差</th></template>
              <th class="num sep">预算</th><th class="num">实际</th><th class="num">差额</th><th class="num">达成率</th>
              <th class="num sep">预算</th><th class="num">实际</th><th class="num">差（百分点）</th>
            </tr>
          </thead>
          <tbody>
            <template v-for="(row, idx) in [...(data.rows ?? []), ...(data.b2b_rows ?? []), ...(data.unassigned ? [data.unassigned] : [])]" :key="row.key">
              <tr v-if="row.kind === 'b2b' && idx === (data.rows ?? []).length" class="group-row">
                <td class="dim" colspan="3">B 端（按客户）</td><td :colspan="colCount - 3"></td>
              </tr>
              <tr :class="{ unassigned: row.kind === 'unassigned' }">
                <td class="dim">
                  <button type="button" class="xbtn" :aria-expanded="!!open[row.key]" :aria-label="`展开 ${row.name} 明细`" @click="toggle(row.key)">
                    <svg width="12" height="12" viewBox="0 0 256 256" fill="currentColor" aria-hidden="true"><path d="M181.66,133.66l-80,80a8,8,0,0,1-11.32-11.32L164.69,128,90.34,53.66a8,8,0,0,1,11.32-11.32l80,80A8,8,0,0,1,181.66,133.66Z" /></svg>
                  </button>{{ row.name }}<span v-if="row.is_new_channel" class="badge" style="margin-left: 4px">新渠道</span>
                </td>
                <td :class="{ muted: !row.channel }">{{ row.channel ?? '—' }}</td>
                <td :class="{ muted: !row.site }">{{ row.site ?? '—' }}</td>
                <template v-if="row.kind === 'unassigned'">
                  <td class="num sep muted">—</td><td class="num muted">—</td><td class="num muted">—</td><td class="num muted">—</td><td class="num muted">—</td><td></td>
                  <template v-if="bi"><td class="num sep muted">—</td><td class="num muted">—</td><td class="num muted">—</td><td class="num muted">—</td></template>
                  <td class="num sep muted">—</td><td class="num">{{ money(row.gross_profit.actual) }}</td><td class="num muted">—</td><td class="num muted">—</td>
                  <td class="num sep muted">—</td><td class="num muted">—</td><td class="num muted">—</td>
                </template>
                <template v-else>
                  <td class="num sep">{{ money(row.revenue.budget) }}</td>
                  <td class="num">{{ money(row.revenue.actual) }}</td>
                  <td class="num">
                    <span v-if="row.kind === 'b2b'" class="muted">—</span>
                    <span v-else-if="!bi" class="muted">待 BI</span>
                    <template v-else>{{ local(row.revenue_local_actual, row.currency) }}</template>
                  </td>
                  <td class="num" :class="tone(row.revenue.diff)">{{ moneySigned(row.revenue.diff) }}</td>
                  <td class="num">{{ pct(row.revenue.rate) }}</td>
                  <td><AchievementBar :rate="row.revenue.rate" progress="100" kind="revenue" /></td>
                  <template v-if="bi">
                    <td v-if="row.kind === 'b2b'" class="num sep muted" colspan="4">B 端不做量价拆分</td>
                    <template v-else-if="row.split">
                      <td class="num sep" :class="tone(row.split.volume)">{{ moneySigned(row.split.volume) }}</td>
                      <td class="num" :class="tone(row.split.price)">{{ moneySigned(row.split.price) }}</td>
                      <td v-if="row.split.missing_fx" class="num bad">{{ row.split.missing_fx_text }}</td>
                      <td v-else class="num" :class="tone(row.split.fx)">{{ moneySigned(row.split.fx) }}</td>
                      <td class="num" :class="row.split.missing_fx ? 'muted' : tone(row.split.basis)">{{ row.split.missing_fx ? '—' : moneySigned(row.split.basis) }}</td>
                    </template>
                    <template v-else><td class="num sep muted">—</td><td class="num muted">—</td><td class="num muted">—</td><td class="num muted">—</td></template>
                  </template>
                  <td class="num sep">{{ money(row.gross_profit.budget) }}</td>
                  <td class="num">{{ money(row.gross_profit.actual) }}</td>
                  <td class="num" :class="tone(row.gross_profit.diff)">{{ moneySigned(row.gross_profit.diff) }}</td>
                  <td class="num">{{ pct(row.gross_profit.rate) }}</td>
                  <td class="num sep">{{ pct(row.gross_margin.budget) }}</td>
                  <td class="num">{{ pct(row.gross_margin.actual) }}</td>
                  <td class="num" :class="tone(row.gross_margin.diff_pp)">{{ pp(row.gross_margin.diff_pp) }}</td>
                </template>
                <td class="sep"><NoteCell :note="row.note" :can-edit="data.can_edit_note" @open="openNote(row)" /></td>
              </tr>
              <tr v-if="open[row.key]" class="detail">
                <td :colspan="colCount">
                  <div class="detail-grid">
                    <div class="table-wrap">
                      <table class="table">
                        <thead>
                          <tr>
                            <th>项目</th><th class="num">预算</th><th class="num">实际</th><th class="num">差额</th><th class="num">达成率</th><th>达成条</th>
                            <template v-if="bi && row.kind !== 'unassigned'"><th class="num">预算费率</th><th class="num">实际费率</th><th class="num">费率差</th></template>
                          </tr>
                        </thead>
                        <tbody>
                          <tr v-if="row.kind !== 'unassigned'">
                            <td>收入 <span class="cur">{{ row.currency }}</span></td>
                            <td class="num">{{ money(row.revenue.budget) }}<div class="cur">{{ local(row.revenue_local_budget, row.currency) }}</div></td>
                            <td class="num">{{ money(row.revenue.actual) }}<div class="cur">{{ row.kind === 'b2b' ? '金蝶人民币收入' : (bi ? local(row.revenue_local_actual, row.currency) : '本币待 BI') }}</div></td>
                            <td class="num" :class="tone(row.revenue.diff)">{{ moneySigned(row.revenue.diff) }}</td>
                            <td class="num">{{ pct(row.revenue.rate) }}</td>
                            <td><AchievementBar :rate="row.revenue.rate" progress="100" kind="revenue" /></td>
                            <template v-if="bi"><td class="num muted">—</td><td class="num muted">—</td><td class="num muted">—</td></template>
                          </tr>
                          <template v-for="line in row.lines" :key="line.key">
                            <tr v-if="row.kind === 'unassigned'">
                              <td>{{ line.label }}</td><td class="num muted">—</td><td class="num">{{ money(line.actual) }}</td><td class="num muted">—</td><td class="num muted">—</td><td><span class="muted">—</span></td>
                            </tr>
                            <tr v-else-if="line.budget !== '0' || line.actual !== '0'">
                              <td>{{ line.label }}</td>
                              <td class="num">{{ money(line.budget) }}</td>
                              <td class="num">{{ money(line.actual) }}</td>
                              <td class="num" :class="tone(line.diff, line.direction === 'higher-better')">{{ moneySigned(line.diff) }}</td>
                              <td class="num">{{ pct(line.rate) }}</td>
                              <td><AchievementBar :rate="line.rate" progress="100" :kind="line.direction === 'higher-better' ? 'revenue' : 'expense'" /></td>
                              <template v-if="bi">
                                <td class="num">{{ pct(line.budget_rate, 1) }}</td>
                                <td class="num">{{ pct(line.actual_rate, 1) }}</td>
                                <td class="num" :class="tone(line.rate_diff, line.direction === 'higher-better')">{{ moneySigned(line.rate_diff) }}</td>
                              </template>
                            </tr>
                          </template>
                          <tr class="total">
                            <template v-if="row.kind === 'unassigned'">
                              <td>毛利影响</td><td class="num muted">—</td><td class="num">{{ money(row.gross_profit.actual) }}</td><td class="num muted">—</td><td class="num muted">—</td><td></td>
                            </template>
                            <template v-else>
                              <td>毛利</td>
                              <td class="num">{{ money(row.gross_profit.budget) }}</td>
                              <td class="num">{{ money(row.gross_profit.actual) }}</td>
                              <td class="num" :class="tone(row.gross_profit.diff)">{{ moneySigned(row.gross_profit.diff) }}</td>
                              <td class="num">{{ pct(row.gross_profit.rate) }}</td>
                              <td><AchievementBar :rate="row.gross_profit.rate" progress="100" kind="revenue" /></td>
                              <template v-if="bi"><td class="num muted">—</td><td class="num muted">—</td><td class="num muted">—</td></template>
                            </template>
                          </tr>
                        </tbody>
                      </table>
                    </div>
                    <div class="card split-card">
                      <template v-if="row.kind === 'unassigned'">
                        <h4>未归属渠道</h4>
                        <div class="formula">金蝶中没有店铺核算的成本费用行，单列在此，不分摊到任何店铺。只有实际，没有预算。</div>
                      </template>
                      <template v-else-if="!bi">
                        <h4>收入差额拆分</h4>
                        <div class="bi-banner" style="margin: 0">{{ data.bi_notice }}</div>
                        <div class="formula">本月只显示金额差异。</div>
                      </template>
                      <template v-else-if="row.kind === 'b2b'">
                        <h4>{{ row.name }} · {{ row.department }}</h4>
                        <div class="formula">B 端客户没有 BI 销量数据，不做量价拆分，只看金额差异与费率差。实际收入与费用取自金蝶。</div>
                      </template>
                      <template v-else-if="row.split">
                        <h4>收入差额拆分</h4>
                        <dl class="split-list">
                          <dt>预算销量 × 预算净单价</dt><dd>{{ money(row.split.budget_qty, 0) }} × {{ money(row.split.budget_net_price, 4) }}</dd>
                          <dt>实际销量 × 实际净单价</dt><dd>{{ money(row.split.actual_qty, 0) }} × {{ money(row.split.actual_net_price, 4) }}</dd>
                          <dt>预算汇率 / 当月平均汇率</dt><dd>{{ money(row.split.budget_fx, 4) }} / {{ row.split.actual_fx === null ? '未录入' : money(row.split.actual_fx, 4) }}</dd>
                          <dt>量差</dt><dd :class="tone(row.split.volume)">{{ moneySigned(row.split.volume) }}</dd>
                          <dt>价差</dt><dd :class="tone(row.split.price)">{{ moneySigned(row.split.price) }}</dd>
                          <dt>汇率差</dt><dd :class="row.split.missing_fx ? 'bad' : tone(row.split.fx)">{{ row.split.missing_fx ? row.split.missing_fx_text : moneySigned(row.split.fx) }}</dd>
                          <dt>口径差（金蝶 − BI 折人民币）</dt><dd :class="row.split.missing_fx ? 'muted' : tone(row.split.basis)">{{ row.split.missing_fx ? '—' : moneySigned(row.split.basis) }}</dd>
                          <dt class="sum">收入差额</dt><dd class="sum" :class="tone(row.split.total)">{{ moneySigned(row.split.total) }}</dd>
                        </dl>
                        <div class="formula">量差 = (实际销量 − 预算销量) × 预算净单价 × 预算汇率<br />价差 = (实际净单价 − 预算净单价) × 实际销量 × 预算汇率<br />汇率差 = 实际本币收入 × (当月平均汇率 − 预算汇率)<br />口径差 = 金蝶实际收入 − BI 本币收入 × 当月平均汇率<br />量差 + 价差 + 汇率差 + 口径差 = 收入差额<br />净单价 = 平均单价 × (1 − 折扣率)；费率差 = (实际费率 − 预算费率) × 实际人民币收入</div>
                        <div v-if="row.split.missing_fx" class="formula warn">该月 {{ row.currency }} 当月平均汇率未录入，汇率差与口径差暂不计算，见 <RouterLink :to="{ name: 'fx' }">汇率</RouterLink>。</div>
                        <div v-else-if="row.split.basis !== null && money(row.split.basis) !== '0.00'" class="formula warn">口径差来自金蝶收入与 BI 收入不一致，见 <RouterLink :to="{ name: 'reconcile' }">BI 与金蝶核对</RouterLink>。</div>
                      </template>
                      <template v-else>
                        <h4>收入差额拆分</h4>
                        <div class="formula">该店铺本月没有预算销量，不做量价拆分。</div>
                      </template>
                    </div>
                  </div>
                </td>
              </tr>
            </template>
            <tr v-if="data.total" class="total">
              <td class="dim">{{ data.total.label }}</td><td></td><td></td>
              <td class="num sep">{{ money(data.total.revenue.budget) }}</td>
              <td class="num">{{ money(data.total.revenue.actual) }}</td>
              <td class="num muted">—</td>
              <td class="num" :class="tone(data.total.revenue.diff)">{{ moneySigned(data.total.revenue.diff) }}</td>
              <td class="num">{{ pct(data.total.revenue.rate) }}</td>
              <td><AchievementBar :rate="data.total.revenue.rate" progress="100" kind="revenue" /></td>
              <template v-if="bi">
                <template v-if="data.total.split">
                  <td class="num sep" :class="tone(data.total.split.volume)">{{ moneySigned(data.total.split.volume) }}</td>
                  <td class="num" :class="tone(data.total.split.price)">{{ moneySigned(data.total.split.price) }}</td>
                  <td v-if="data.total.split.missing_fx" class="num bad">{{ data.total.split.missing_fx_text }}</td>
                  <td v-else class="num" :class="tone(data.total.split.fx)">{{ moneySigned(data.total.split.fx) }}</td>
                  <td class="num" :class="data.total.split.missing_fx ? 'muted' : tone(data.total.split.basis)">{{ data.total.split.missing_fx ? '—' : moneySigned(data.total.split.basis) }}</td>
                </template>
                <template v-else><td class="num sep muted">—</td><td class="num muted">—</td><td class="num muted">—</td><td class="num muted">—</td></template>
              </template>
              <td class="num sep">{{ money(data.total.gross_profit.budget) }}</td>
              <td class="num">{{ money(data.total.gross_profit.actual) }}</td>
              <td class="num" :class="tone(data.total.gross_profit.diff)">{{ moneySigned(data.total.gross_profit.diff) }}</td>
              <td class="num">{{ pct(data.total.gross_profit.rate) }}</td>
              <td class="num sep">{{ pct(data.total.gross_margin.budget) }}</td>
              <td class="num">{{ pct(data.total.gross_margin.actual) }}</td>
              <td class="num" :class="tone(data.total.gross_margin.diff_pp)">{{ pp(data.total.gross_margin.diff_pp) }}</td>
              <td class="sep"></td>
            </tr>
          </tbody>
        </table>
      </div>
      <p class="foot">点击店铺或客户左侧箭头展开退款与各项费用明细、费率差和收入拆分计算。收入差额 = 量差 + 价差 + 汇率差 + 口径差；口径差 = 金蝶实际收入 − BI 本币收入 × 当月平均汇率。B 端客户无 BI 销量数据，不做量价拆分。达成条刻度线 = 100%（当月对当月）。收入、毛利、库存索赔高于预算为有利；退款与费用高于预算为不利。</p>
    </template>

    <NoteDialog :target="noteTarget" :can-edit="data?.can_edit_note ?? false" @close="noteTarget = null" @saved="onSaved" />
  </div>
</template>

<style scoped>
.bi-banner { display: flex; align-items: center; gap: var(--space-2); padding: var(--space-2) var(--space-3); margin-bottom: var(--space-3); border-radius: var(--radius-md); background: color-mix(in oklab, var(--warn), white 90%); color: var(--warn); font-size: var(--text-sm); }
.table td.dim { min-width: 150px; }
.xbtn { display: inline-grid; place-items: center; width: 22px; height: 22px; margin-right: var(--space-1); border: 1px solid transparent; border-radius: var(--radius-sm); background: transparent; color: var(--fg-2); cursor: pointer; vertical-align: middle; transition: background var(--motion-fast) var(--ease-standard); }
.xbtn:hover { background: var(--surface-raised); border-color: var(--border); }
.xbtn:focus-visible { outline: none; box-shadow: var(--focus-ring); }
.xbtn svg { transition: transform var(--motion-fast) var(--ease-standard); }
.xbtn[aria-expanded='true'] svg { transform: rotate(90deg); }
tr.unassigned td { background: var(--surface-warm); }
tr.group-row td { background: var(--surface-warm); font-weight: 600; color: var(--fg-2); }
tr.detail > td { padding: var(--space-3) var(--space-4) var(--space-4); background: var(--bg); white-space: normal; }
tr.detail:hover > td { background: var(--bg); }
.detail-grid { position: sticky; left: 16px; max-width: min(1120px, calc(100vw - 304px)); display: grid; grid-template-columns: minmax(0, 1fr) 320px; gap: var(--space-4); align-items: start; }
.split-card h4 { margin: 0 0 var(--space-2); font-size: var(--text-sm); }
.split-list { display: grid; grid-template-columns: 1fr auto; gap: var(--space-1) var(--space-3); font-size: var(--text-sm); font-variant-numeric: tabular-nums; margin: 0; }
.split-list dt { color: var(--fg-2); }
.split-list dd { margin: 0; text-align: right; }
.split-list .sum { border-top: 1px solid var(--border-soft); padding-top: var(--space-1); font-weight: 600; }
.formula { font-size: var(--text-xs); color: var(--muted); margin-top: var(--space-2); line-height: 1.6; }
.formula.warn { color: var(--warn); }
.formula a { color: inherit; }
</style>
