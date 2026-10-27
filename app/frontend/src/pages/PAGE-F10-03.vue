<script setup lang="ts">
/**
 * 品类×新老品偏差 PAGE-F10-03（API-F10-03 GET /api/reports/category、API-F10-05、API-F14-01）
 * - 只对已有 BI 实际的月份生成；SPU 数、销量、折后品效、收入的预算 / 实际 / 差额（AC-F10-06）
 * - 跨店铺跨币种的行、小计与合计品效按人民币汇总（DEC-025）
 */
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, ApiError } from '@/api/client'
import ExportButton from '@/components/ExportButton.vue'
import PageState from '@/components/PageState.vue'
import NoteCell from '@/components/g4/NoteCell.vue'
import NoteDialog from '@/components/g4/NoteDialog.vue'
import { money, moneySigned, tone } from '@/components/g4/format'
import type { NoteKey, NoteTarget, VarianceNote } from '@/components/g4/types'
import { useUserStore } from '@/stores/user'
import '@/components/g4/report.css'

interface Triple { budget: string | null; actual: string | null; diff: string | null }
interface CatRow {
  category: string
  kind: string
  spu: Triple
  qty: Triple
  efficiency: Triple
  revenue: Triple
  missing_fx: boolean
  note_key?: NoteKey
  note?: VarianceNote | null
}
interface Report {
  empty: boolean
  message?: string
  month: string | null
  months: string[]
  bi_latest: string | null
  can_edit_note: boolean
  baseline_label?: string
  scope_label?: string
  groups?: { category: string; rows: CatRow[]; subtotal: CatRow }[]
  total?: CatRow
}

const route = useRoute()
const router = useRouter()
const user = useUserStore()
const data = ref<Report | null>(null)
const loading = ref(true)
const error = ref<unknown>(null)
const month = ref<string | undefined>(typeof route.query.month === 'string' ? route.query.month : undefined)
const noteTarget = ref<NoteTarget | null>(null)
const isBP = computed(() => user.me?.roles.includes('finance_bp') ?? false)
const isForbidden = computed(() => error.value instanceof ApiError && error.value.isForbidden)
const ready = computed(() => !loading.value && !error.value && !!data.value && !data.value.empty)

async function load(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    const res = await api.get<Report>('/api/reports/category', { month: month.value })
    data.value = res
    month.value = res.month ?? undefined
    void router.replace({ query: { ...route.query, month: res.month ?? undefined } })
  } catch (e) {
    error.value = e
  } finally {
    loading.value = false
  }
}
onMounted(load)

function openNote(row: CatRow): void {
  if (!data.value?.month || !row.note_key) return
  noteTarget.value = { report_type: 'category', month: data.value.month, ...row.note_key, label: `${row.category} · ${row.kind}`, note: row.note }
}
function onSaved(note: VarianceNote): void {
  const t = noteTarget.value
  for (const g of data.value?.groups ?? []) {
    for (const r of g.rows) if (t && r.note_key?.object_key === t.object_key) r.note = note
  }
  noteTarget.value = null
}
</script>

<template>
  <div data-page-id="PAGE-F10-03" class="g4-report">
    <div class="page-head">
      <div>
        <h1 class="page-title">品类×新老品偏差</h1>
        <div class="meta">按品类与新品/老品对比 SPU 数、销量、品效和收入 · 每两个月随 BI 数据更新 · 金额单位：人民币元</div>
      </div>
      <ExportButton class="btn-primary" view="report-category" :filters="{ month: data?.month }" :disabled="!ready" />
    </div>

    <div v-if="!isForbidden && (data?.months ?? []).length" class="filters">
      <label>月份
        <select v-model="month" class="select" :disabled="loading" @change="load">
          <option v-for="m in data?.months ?? []" :key="m" :value="m">{{ m }}</option>
        </select>
      </label>
      <div class="hint">只能选择已有 BI 实际的月份。最近 BI 数据截至 {{ data?.bi_latest }}。</div>
    </div>

    <PageState v-if="loading" state="loading" :rows="8" />
    <PageState v-else-if="isForbidden" state="forbidden" description="你没有被分配任何渠道或店铺，无法查看品类报告。如需查看请联系财务负责人分配数据范围。" />
    <PageState v-else-if="error" :error="error" title="品类报告加载失败" description="服务器未返回数据，可能是网络中断。请重试。" @retry="load" />
    <PageState v-else-if="data?.empty" :title="data.message" description="品类报告只对已有 BI 实际的月份生成。BI 双月数据导入后这里显示对比。">
      <template #action>
        <RouterLink v-if="isBP" class="btn btn-primary" :to="{ name: 'import' }">去导入 BI 数据</RouterLink>
      </template>
    </PageState>

    <template v-else-if="data && data.groups && data.total">
      <div class="info-strip">
        <span>BI 数据截至：<b>{{ data.bi_latest }}</b></span>
        <span>本表月份：<b>{{ data.month }}</b></span>
        <span>对比基准：<b>{{ data.baseline_label }}</b></span>
        <span>数据范围：<b>{{ data.scope_label }}</b></span>
        <span>汇率口径：预算按预算汇率，实际按当月平均汇率折人民币</span>
      </div>
      <div class="table-wrap">
        <table class="table" data-testid="category-table">
          <thead>
            <tr>
              <th rowspan="2" class="dim-h">品类</th>
              <th rowspan="2">新品/老品</th>
              <th class="grp" colspan="3">SPU 数</th>
              <th class="grp" colspan="3">销量（件）</th>
              <th class="grp" colspan="3">品效（折后 · 人民币元/SPU）</th>
              <th class="grp" colspan="3">收入</th>
              <th class="sep" rowspan="2">偏差说明</th>
            </tr>
            <tr>
              <th class="num sep">预算</th><th class="num">实际</th><th class="num">差额</th>
              <th class="num sep">预算</th><th class="num">实际</th><th class="num">差额</th>
              <th class="num sep">预算</th><th class="num">实际</th><th class="num">差额</th>
              <th class="num sep">预算</th><th class="num">实际</th><th class="num">差额</th>
            </tr>
          </thead>
          <tbody>
            <template v-for="g in data.groups" :key="g.category">
              <tr v-for="r in [...g.rows, g.subtotal]" :key="r.kind" :class="{ subtotal: r.kind === '小计' }">
                <td class="dim">{{ r.category }}</td>
                <td>{{ r.kind }}</td>
                <td class="num sep">{{ money(r.spu.budget, 0) }}</td>
                <td class="num">{{ money(r.spu.actual, 0) }}</td>
                <td class="num">{{ moneySigned(r.spu.diff, 0) }}</td>
                <td class="num sep">{{ money(r.qty.budget, 0) }}</td>
                <td class="num">{{ money(r.qty.actual, 0) }}</td>
                <td class="num" :class="tone(r.qty.diff)">{{ moneySigned(r.qty.diff, 0) }}</td>
                <td class="num sep">{{ money(r.efficiency.budget) }}</td>
                <td class="num">{{ money(r.efficiency.actual) }}</td>
                <td class="num" :class="tone(r.efficiency.diff)">{{ moneySigned(r.efficiency.diff) }}</td>
                <td class="num sep">{{ money(r.revenue.budget) }}</td>
                <td class="num">{{ r.missing_fx ? '缺少汇率' : money(r.revenue.actual) }}</td>
                <td class="num" :class="tone(r.revenue.diff)">{{ moneySigned(r.revenue.diff) }}</td>
                <td class="sep">
                  <NoteCell v-if="r.note_key" :note="r.note" :can-edit="data.can_edit_note" @open="openNote(r)" />
                </td>
              </tr>
            </template>
            <tr class="total">
              <td class="dim">合计</td>
              <td>品效按人民币汇总</td>
              <td class="num sep">{{ money(data.total.spu.budget, 0) }}</td>
              <td class="num">{{ money(data.total.spu.actual, 0) }}</td>
              <td class="num">{{ moneySigned(data.total.spu.diff, 0) }}</td>
              <td class="num sep">{{ money(data.total.qty.budget, 0) }}</td>
              <td class="num">{{ money(data.total.qty.actual, 0) }}</td>
              <td class="num" :class="tone(data.total.qty.diff)">{{ moneySigned(data.total.qty.diff, 0) }}</td>
              <td class="num sep">{{ money(data.total.efficiency.budget) }}</td>
              <td class="num">{{ money(data.total.efficiency.actual) }}</td>
              <td class="num" :class="tone(data.total.efficiency.diff)">{{ moneySigned(data.total.efficiency.diff) }}</td>
              <td class="num sep">{{ money(data.total.revenue.budget) }}</td>
              <td class="num">{{ money(data.total.revenue.actual) }}</td>
              <td class="num" :class="tone(data.total.revenue.diff)">{{ moneySigned(data.total.revenue.diff) }}</td>
              <td class="sep"></td>
            </tr>
          </tbody>
        </table>
      </div>
      <p class="foot">品效按折后口径：预算品效 = 单 SPU 平均销量 × 平均单价 × (1 − 折扣率)；实际品效 = 实际销售额（本币）÷ SPU 数。单一店铺站点内按本币计算；本表各行、小计与合计跨店铺、跨币种，按人民币汇总：Σ(销量 × 折后单价 × 汇率) ÷ ΣSPU 数，即人民币收入 ÷ SPU 数（预算用预算汇率，实际用当月平均汇率）。SPU 数跨店铺站点累加。新品/老品按 SKU 对照表中的首次上架日期判定。销量、品效、收入高于预算为有利。</p>
    </template>

    <NoteDialog :target="noteTarget" :can-edit="data?.can_edit_note ?? false" @close="noteTarget = null" @saved="onSaved" />
  </div>
</template>

<style scoped>
tr.subtotal td { font-weight: 600; background: var(--surface-warm); }
/* 小计差额保留有利绿 / 不利红，其余小计数字用次级色 */
tr.subtotal td:not(.good):not(.bad) { color: var(--fg-2); }
</style>
