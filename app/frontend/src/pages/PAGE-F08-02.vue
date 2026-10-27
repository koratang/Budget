<script setup lang="ts">
/**
 * PAGE-F08-02 版本对比：任选两版本按维度对比全年收入、毛利及差额；净利润只在公司合计行（AC-F08-08）。
 * 结果按数据范围在服务端过滤（API-F08-05）。URL 同步 a、b、dims。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '@/api/client'
import PageState from '@/components/PageState.vue'
import '@/components/g3/g3.css'

interface VersionRow { id: number; label: string; type_label: string }
type Money = Record<string, string>
interface CompareData {
  a: VersionRow; b: VersionRow; dims: string; dims_label: string; scope_text: string; all_company: boolean
  kpis: Money; rows: (Money & { key: string; store?: string; site?: string; channel?: string; category?: string; is_new_label?: string; customer?: string; department?: string; currency?: string })[]
  total: Money; company: Money | null
}

const route = useRoute()
const router = useRouter()
const versions = ref<VersionRow[]>([])
const a = ref<number | null>(null)
const b = ref<number | null>(null)
const dims = ref<string>(String(route.query.dims ?? 'channel'))
const data = ref<CompareData | null>(null)
const loading = ref(true)
const error = ref<unknown>(null)
const busy = ref(false)

const same = computed(() => a.value !== null && a.value === b.value)
const dimHead = computed(() => ({ channel: '渠道 / 店铺 / 站点', category: '品类 / 新品老品', customer: 'B端客户' })[dims.value] ?? '')

function neg(v: string | undefined): boolean {
  return !!v && v.startsWith('-')
}

async function init(): Promise<void> {
  error.value = null
  try {
    const page = await api.get<{ versions: VersionRow[] }>('/api/versions')
    versions.value = page.versions
    const qa = Number(route.query.a)
    const qb = Number(route.query.b)
    a.value = qa || versions.value[0]?.id || null
    const current = page.versions.find((v) => (v as VersionRow & { current?: boolean }).current)
    b.value = qb || current?.id || versions.value[1]?.id || null
    if (versions.value.length >= 2) await compare()
  } catch (e) {
    error.value = e
  } finally {
    loading.value = false
  }
}

async function compare(): Promise<void> {
  if (a.value === null || b.value === null || same.value) {
    data.value = null
    return
  }
  busy.value = true
  error.value = null
  try {
    data.value = await api.get<CompareData>('/api/versions/compare', { a: a.value, b: b.value, dims: dims.value })
  } catch (e) {
    error.value = e
  } finally {
    busy.value = false
  }
}

watch([a, b, dims], () => {
  router.replace({ query: { a: a.value ? String(a.value) : undefined, b: b.value ? String(b.value) : undefined, dims: dims.value } })
  if (!loading.value) void compare()
})
onMounted(init)
</script>

<template>
  <div data-page-id="PAGE-F08-02" class="g3">
    <div class="page-head"><h1 class="page-title">版本对比</h1></div>
    <PageState v-if="loading" state="loading" />
    <PageState v-else-if="error && !data" :error="error" @retry="init" />
    <div v-else-if="versions.length < 2" class="card state">
      <div class="state-title">至少需要两个预算版本才能对比</div>
      <p>当前年度不足两个版本。季度目标调整生效或发布滚动预测快照后即可对比。</p>
      <RouterLink class="btn" :to="{ name: 'versions' }">返回版本管理</RouterLink>
    </div>
    <template v-else>
      <div class="row section">
        <label class="small muted" for="va">版本 A</label>
        <select id="va" v-model.number="a" class="select">
          <option v-for="v in versions" :key="v.id" :value="v.id">{{ v.label }} · {{ v.type_label }}</option>
        </select>
        <label class="small muted" for="vb">版本 B</label>
        <select id="vb" v-model.number="b" class="select">
          <option v-for="v in versions" :key="v.id" :value="v.id">{{ v.label }} · {{ v.type_label }}</option>
        </select>
        <label class="small muted" for="dim">维度</label>
        <select id="dim" v-model="dims" class="select">
          <option value="channel">渠道 × 店铺 × 站点</option>
          <option value="category">品类 × 新品/老品</option>
          <option value="customer">B端客户</option>
        </select>
        <span class="small muted">期间：全年（1–12 月）</span>
      </div>
      <div v-if="same" class="notice bad section" role="alert">请选择两个不同的版本。</div>
      <PageState v-else-if="busy && !data" state="loading" />
      <template v-else-if="data">
        <p class="small muted" style="margin-top: 0">按你的数据范围显示：{{ data.scope_text }}。差额 = 版本 B − 版本 A。</p>
        <div class="grid-3 section cmp-kpi">
          <div v-for="k in [{ p: 'revenue', t: '收入差额' }, { p: 'gross', t: '毛利差额' }, { p: 'net', t: '净利润差额' }]" :key="k.p" class="card fade-in">
            <div class="kpi-label">{{ data.all_company ? '公司' : '范围内' }}{{ k.t }}</div>
            <template v-if="data.kpis[`${k.p}_diff`] !== undefined">
              <div class="kpi-value num" :class="{ bad: neg(data.kpis[`${k.p}_diff`]) }">{{ data.kpis[`${k.p}_diff_display`] }}</div>
              <div class="line"><span>{{ data.a.label }}</span><span>{{ data.kpis[`${k.p}_a_display`] }}</span></div>
              <div class="line"><span>{{ data.b.label }}</span><span>{{ data.kpis[`${k.p}_b_display`] }}</span></div>
            </template>
            <template v-else>
              <div class="kpi-value">—</div>
              <div class="line"><span>净利润只在公司合计层计算</span></div>
            </template>
          </div>
        </div>
        <div class="table-wrap">
          <table class="table">
            <thead>
              <tr><th rowspan="2">{{ dimHead }}</th><th class="grp" colspan="3">收入</th><th class="grp" colspan="3">毛利</th><th class="grp" colspan="3">净利润（仅公司合计行）</th></tr>
              <tr>
                <th class="num bl">{{ data.a.label }}</th><th class="num">{{ data.b.label }}</th><th class="num">差额</th>
                <th class="num bl">{{ data.a.label }}</th><th class="num">{{ data.b.label }}</th><th class="num">差额</th>
                <th class="num bl">{{ data.a.label }}</th><th class="num">{{ data.b.label }}</th><th class="num">差额</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="r in data.rows" :key="r.key">
                <td class="dim">
                  <template v-if="data.dims === 'channel'">{{ r.store }} · {{ r.site }}<br><span class="small muted">{{ r.channel }}</span></template>
                  <template v-else-if="data.dims === 'category'">{{ r.category }} · {{ r.is_new_label }}</template>
                  <template v-else>{{ r.customer }}<br><span class="small muted">{{ r.department }} · {{ r.currency }}</span></template>
                </td>
                <td class="num bl">{{ r.revenue_a_display }}</td><td class="num">{{ r.revenue_b_display }}</td>
                <td class="num" :class="{ bad: neg(r.revenue_diff) }">{{ r.revenue_diff_display }}</td>
                <td class="num bl">{{ r.gross_a_display }}</td><td class="num">{{ r.gross_b_display }}</td>
                <td class="num" :class="{ bad: neg(r.gross_diff) }">{{ r.gross_diff_display }}</td>
                <td class="num bl muted">—</td><td class="num muted">—</td><td class="num muted">—</td>
              </tr>
              <tr v-if="!data.rows.length"><td colspan="10" class="muted">范围内没有可对比的维度组合</td></tr>
              <tr class="total">
                <td>{{ data.dims_label }}合计</td>
                <td class="num bl">{{ data.total.revenue_a_display }}</td><td class="num">{{ data.total.revenue_b_display }}</td>
                <td class="num" :class="{ bad: neg(data.total.revenue_diff) }">{{ data.total.revenue_diff_display }}</td>
                <td class="num bl">{{ data.total.gross_a_display }}</td><td class="num">{{ data.total.gross_b_display }}</td>
                <td class="num" :class="{ bad: neg(data.total.gross_diff) }">{{ data.total.gross_diff_display }}</td>
                <td class="num bl muted">—</td><td class="num muted">—</td><td class="num muted">—</td>
              </tr>
              <tr v-if="data.company" class="total">
                <td>公司合计（含 B端、部门费用与公司层其他损益）</td>
                <td class="num bl muted">—</td><td class="num muted">—</td><td class="num muted">—</td>
                <td class="num bl muted">—</td><td class="num muted">—</td><td class="num muted">—</td>
                <td class="num bl">{{ data.company.net_a_display }}</td><td class="num">{{ data.company.net_b_display }}</td>
                <td class="num" :class="{ bad: neg(data.company.net_diff) }">{{ data.company.net_diff_display }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p class="small muted">净利润 = 平台渠道毛利 + B端毛利 − 部门费用 + 公司层其他损益。公共费用与公司层其他损益不分摊到渠道、品类或客户，因此净利润只在公司合计行（及上方卡片）显示，维度行与维度合计行显示「—」。</p>
      </template>
    </template>
  </div>
</template>

<style scoped>
.cmp-kpi .kpi-value { font-size: var(--text-xl); }
.cmp-kpi .line { display: flex; justify-content: space-between; font-size: var(--text-sm); color: var(--fg-2); font-variant-numeric: tabular-nums; margin-top: var(--space-1); }
.table td.dim { white-space: normal; line-height: var(--leading-tight); padding-top: var(--space-1); padding-bottom: var(--space-1); }
.table th.grp { text-align: center; border-left: 1px solid var(--border-soft); }
.table td.bl, .table th.bl { border-left: 1px solid var(--border-soft); }
</style>
