<script setup lang="ts">
/**
 * PAGE-F09-02 BI 与金蝶核对：按「月 × 店铺 × 站点」BI 本币 × 当月平均汇率折人民币，与金蝶收入比较，
 * |差异率| > 3% 标红；缺当月平均汇率不计算并提示补录（API-F09-05；AC-F09-07、AC-F02-08）。
 */
import { computed, onMounted, ref } from 'vue'
import { api, ApiError } from '@/api/client'
import PageState from '@/components/PageState.vue'
import '@/components/g3/g3.css'

interface Row {
  store_id: number; store: string; site: string; channel: string; channel_id: number; currency: string
  bi_local_display: string; rate: string | null; bi_cny_display: string; kingdee_display: string
  diff: string | null; diff_display: string; diff_rate_display: string; over: boolean; note: string | null; counted: boolean
}
interface Data {
  month: string; ready_months: string[]; bi_imported: boolean; kingdee_imported: boolean; rows: Row[]
  rates: { currency: string; rate: string }[]; channels?: { id: number; name: string }[]
  kpis: null | { combos: number; over: number; bi_cny_total_display: string; kingdee_total_display: string }
}

const month = ref<string | undefined>(undefined)
const channel = ref<number | ''>('')
const overOnly = ref(false)
const data = ref<Data | null>(null)
const loading = ref(true)
const error = ref<unknown>(null)

const months = computed(() => {
  const set = new Set(data.value?.ready_months ?? [])
  if (data.value) set.add(data.value.month)
  return [...set].sort().reverse()
})
const rows = computed(() => (data.value?.rows ?? []).filter((r) =>
  (channel.value === '' || r.channel_id === channel.value) && (!overOnly.value || r.over)))
const forbiddenText = computed(() =>
  error.value instanceof ApiError && error.value.isForbidden ? 'BI 与金蝶核对仅对财务BP、财务负责人和 CEO 开放。' : undefined)

async function load(): Promise<void> {
  error.value = null
  try {
    data.value = await api.get<Data>('/api/reconciliation', { month: month.value })
    month.value = data.value.month
  } catch (e) {
    error.value = e
  } finally {
    loading.value = false
  }
}
onMounted(load)
</script>

<template>
  <div data-page-id="PAGE-F09-02" class="g3">
    <div class="page-head"><h1 class="page-title">BI 与金蝶核对</h1></div>
    <PageState v-if="loading" state="loading" />
    <PageState v-else-if="error" :error="error" :description="forbiddenText" @retry="load" />
    <template v-else-if="data">
      <div v-if="!data.ready_months.length && !data.kpis" class="card state">
        <div class="state-title">还没有可核对的月份</div>
        <p>同一月份的 BI 与金蝶实际都导入后，这里按「月 × 店铺 × 站点」列出收入差异率。</p>
        <RouterLink class="btn" :to="{ name: 'import' }">去导入实际数</RouterLink>
      </div>
      <template v-else>
        <div class="row section">
          <label class="small muted" for="f-m">月份</label>
          <select id="f-m" v-model="month" class="select" @change="load">
            <option v-for="m in months" :key="m" :value="m">{{ m }}</option>
          </select>
          <label class="small muted" for="f-ch">渠道</label>
          <select id="f-ch" v-model="channel" class="select">
            <option value="">全部渠道</option>
            <option v-for="c in data.channels ?? []" :key="c.id" :value="c.id">{{ c.name }}</option>
          </select>
          <label class="row small" style="gap: var(--space-1)"><input v-model="overOnly" type="checkbox"> 只看差异率超过 3%</label>
        </div>

        <div v-if="!data.kpis" class="card state">
          <div class="state-title">{{ data.month }} 还不能核对</div>
          <p>同一月份的 BI 与金蝶实际都导入后才会生成核对结果。当前状态：金蝶 {{ data.month }} {{ data.kingdee_imported ? '已导入' : '未导入' }}；BI {{ data.month }} {{ data.bi_imported ? '已导入' : '未导入' }}。</p>
          <RouterLink class="btn" :to="{ name: 'import' }">去导入实际数</RouterLink>
        </div>
        <template v-else>
          <div class="grid-4 section">
            <div class="card fade-in"><div class="kpi-label">核对组合（店铺 × 站点）</div><div class="kpi-value num">{{ data.kpis.combos }}</div></div>
            <div class="card fade-in"><div class="kpi-label">差异率绝对值超过 3%</div><div class="kpi-value num" :class="{ bad: data.kpis.over > 0 }">{{ data.kpis.over }}</div></div>
            <div class="card fade-in"><div class="kpi-label">BI 折人民币合计</div><div class="kpi-value num" style="font-size: var(--text-xl)">{{ data.kpis.bi_cny_total_display }}</div></div>
            <div class="card fade-in"><div class="kpi-label">金蝶收入合计</div><div class="kpi-value num" style="font-size: var(--text-xl)">{{ data.kpis.kingdee_total_display }}</div></div>
          </div>
          <p class="small muted" style="margin-top: 0">差异率 = (BI 销售额折人民币 − 金蝶收入) ÷ 金蝶收入；BI 销售额按该月当月平均汇率折算为人民币（{{ data.rates.map((r) => `${r.currency} ${r.rate}`).join('、') || '无' }}）；金蝶收入为 0 时差异率无法计算，标红并显示「金蝶无收入」；缺当月平均汇率的组合不计算，提示补录。</p>
          <div class="table-wrap">
            <table class="table">
              <thead><tr><th>店铺 · 站点</th><th class="num">BI 本币销售额</th><th class="num">当月平均汇率</th><th class="num">BI 折人民币</th><th class="num">金蝶收入</th><th class="num">差额</th><th class="num">差异率</th><th>标记</th></tr></thead>
              <tbody>
                <tr v-for="r in rows" :key="`${r.store_id}`" :class="{ 'is-bad': r.over }">
                  <td>{{ r.store }} · {{ r.site }}<br><span class="small muted">{{ r.channel }}</span></td>
                  <td class="num">{{ r.bi_local_display }}</td>
                  <td class="num">{{ r.rate ?? '未录入' }}</td>
                  <td class="num">{{ r.bi_cny_display }}</td>
                  <td class="num">{{ r.kingdee_display }}</td>
                  <td class="num" :class="{ bad: r.diff?.startsWith('-') }">{{ r.diff_display }}</td>
                  <td class="num" :class="{ bad: r.over }">{{ r.diff_rate_display }}</td>
                  <td class="w-n">
                    <span v-if="r.over && r.note" class="badge badge-bad">{{ r.note }}</span>
                    <span v-else-if="r.over" class="badge badge-bad">超过 3%</span>
                    <RouterLink v-else-if="!r.counted" class="link small" :to="{ name: 'fx' }">{{ r.note }}</RouterLink>
                    <span v-else class="muted">—</span>
                  </td>
                </tr>
              </tbody>
            </table>
            <div v-if="!rows.length" class="state"><div class="state-title">没有差异率超过 3% 的组合</div><p>取消「只看差异率超过 3%」可查看全部组合。</p></div>
          </div>
          <p class="small muted">差异较大的组合可在 <RouterLink class="link" :to="{ name: 'report-channel' }">渠道×站点偏差</RouterLink> 中查看收入明细，或回到 <RouterLink class="link" :to="{ name: 'import' }">实际数导入</RouterLink> 核对源文件。</p>
        </template>
      </template>
    </template>
  </div>
</template>

<style scoped>
.table tbody td { padding-top: var(--space-1); padding-bottom: var(--space-1); }
</style>
