<script setup lang="ts">
/**
 * 公司汇总 PAGE-F10-01（API-F10-01 GET /api/reports/company、API-F14-01）
 * - 累计净利润达成率双口径（AC-F10-08）：目标合计 ≤ 0 显示「—」且不画达成条
 * - 部门费用增速 vs 收入增速（AC-F10-09）：费用增速更快时标红；上年同期未导入时提示
 * - 季度预测准确度（AC-F10-10）：|快照预测净利润率 − 实际净利润率| > 1.5 个百分点标红
 */
import { computed, onMounted, ref } from 'vue'
import { api, ApiError } from '@/api/client'
import AchievementBar from '@/components/AchievementBar.vue'
import ExportButton from '@/components/ExportButton.vue'
import PageState from '@/components/PageState.vue'
import { money, pct, pctSigned, pp } from '@/components/g4/format'
import { useUserStore } from '@/stores/user'
import '@/components/g4/report.css'

interface VersionBrief { id: number; name: string; type_label: string; published_on: string | null; approved_at: string | null }
interface Achievement {
  through: string
  period_label: string
  actual_sum: string
  original: { version: VersionBrief | null; target_sum: string; rate: string | null }
  adjusted: { version: VersionBrief | null; has_adjustment: boolean; target_sum: string; rate: string | null }
  months: { month: string; original_target: string; adjusted_target: string; actual: string; rate_original: string | null; rate_adjusted: string | null }[]
}
interface GrowthItem { prior: string; current: string; increase: string; growth: string | null }
interface Growth {
  available: boolean
  message?: string
  period: string
  prior_period: string
  revenue?: GrowthItem
  dept_expense?: GrowthItem
  gap_pp?: string | null
  expense_faster?: boolean
}
interface Accuracy {
  month: string
  snapshot: string
  forecast_margin: string | null
  actual_imported: boolean
  actual_margin: string | null
  deviation_pp: string | null
  flagged: boolean
}
interface Company {
  year: number
  empty: boolean
  message?: string
  through?: string
  achievement?: Achievement
  growth?: Growth
  accuracy?: Accuracy[]
}

const user = useUserStore()
const data = ref<Company | null>(null)
const loading = ref(true)
const error = ref<unknown>(null)
const isBP = computed(() => user.me?.roles.includes('finance_bp') ?? false)
const isForbidden = computed(() => error.value instanceof ApiError && error.value.isForbidden)
const ready = computed(() => !loading.value && !error.value && !!data.value && !data.value.empty)

async function load(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    data.value = await api.get<Company>('/api/reports/company')
  } catch (e) {
    error.value = e
  } finally {
    loading.value = false
  }
}
onMounted(load)

const ach = computed(() => data.value?.achievement)
const monthCount = computed(() => ach.value?.months.length ?? 0)
const adjBadge = computed(() => {
  const a = ach.value?.adjusted
  if (!a) return ''
  if (!a.has_adjustment || !a.version) return '本年度暂无调整，按年初原始目标'
  return a.version.approved_at ? `${a.version.name}（${a.version.approved_at} 生效）` : a.version.name
})
function rateClass(v: string | null): string {
  if (v === null) return 'muted'
  return v.startsWith('-') || Number(v) < 100 ? 'bad' : 'good'
}

// 偏差柱状图：纵轴 0–2.5 个百分点统一比例尺，1.5 处红色虚线阈值（标签在右侧留白处，不与柱子重叠）
const W = 640, H = 240, L = 36, R = 64, T = 16, B = 28, MAX = 2.5, THRESHOLD = 1.5
const yOf = (v: number) => T + (H - T - B) * (1 - Math.min(v, MAX) / MAX)
const bars = computed(() => {
  const list = (data.value?.accuracy ?? []).filter((a) => a.actual_imported && a.deviation_pp !== null)
  const bw = (W - L - R) / Math.max(list.length, 1)
  return list.map((a, i) => {
    // 仅用于绘图位置；显示数值仍为后端字符串格式化结果
    const v = Number(a.deviation_pp)
    const x = L + i * bw + bw * 0.25
    return { m: a.month, label: pp(a.deviation_pp).replace(/^\+/, ''), bad: a.flagged, x, w: bw * 0.5, y: yOf(v), h: yOf(0) - yOf(v) }
  })
})
const ticks = [0, 0.5, 1, 1.5, 2, 2.5]
</script>

<template>
  <div data-page-id="PAGE-F10-01" class="g4-report">
    <div class="page-head">
      <div>
        <h1 class="page-title">公司汇总</h1>
        <div v-if="data?.through" class="meta">截至 {{ data.through }}（最近金蝶导入期间）· 预算年度 {{ data.year }} · 金额单位：人民币元</div>
        <div v-else class="meta">累计净利润达成率、部门费用增速与季度预测准确度 · 金额单位：人民币元</div>
      </div>
      <ExportButton class="btn-primary" view="report-company" :filters="{ year: data?.year }" :disabled="!ready" />
    </div>

    <PageState v-if="loading" state="loading" :rows="8" />
    <PageState v-else-if="isForbidden" state="forbidden" description="公司汇总包含全公司数据，只对 CEO、财务负责人和财务BP 开放。如需查看请联系财务负责人。" />
    <PageState v-else-if="error" :error="error" title="公司汇总加载失败" description="服务器未返回数据，可能是网络中断。数据未受影响，请重试。" @retry="load" />
    <PageState v-else-if="data?.empty" :title="data.message" description="导入第一个月的金蝶实际后，这里显示净利润达成率、增速对比和预测准确度。">
      <template #action>
        <RouterLink v-if="isBP" class="btn btn-primary" :to="{ name: 'import' }">去导入实际数</RouterLink>
      </template>
    </PageState>

    <template v-else-if="data && ach">
      <section class="grid-kpi" aria-label="累计净利润达成率">
        <div class="card fade-in" data-testid="kpi-original">
          <div class="kpi-label">累计净利润达成率 · 按年初原始目标</div>
          <div class="kpi-row">
            <div class="kpi-value">{{ pct(ach.original.rate, 1) }}</div>
            <span class="badge">{{ ach.original.version?.name ?? '尚无年初原始目标' }}</span>
          </div>
          <AchievementBar v-if="ach.original.rate !== null" class="attain-lg" :rate="ach.original.rate" progress="100" kind="revenue" />
          <div class="kpi-sub" style="margin-top: 12px"><span>累计实际</span> ¥ <b>{{ money(ach.actual_sum) }}</b> <span>÷ 累计目标</span> ¥ <b>{{ money(ach.original.target_sum) }}</b></div>
          <div class="kpi-sub"><span>口径：年初至最近导入月实际净利润合计 ÷ 同期目标净利润合计；同期目标合计 ≤ 0 时显示「—」</span></div>
        </div>
        <div class="card fade-in" data-testid="kpi-adjusted">
          <div class="kpi-label">累计净利润达成率 · 按最新调整后目标</div>
          <div class="kpi-row">
            <div class="kpi-value">{{ pct(ach.adjusted.rate, 1) }}</div>
            <span class="badge">{{ adjBadge }}</span>
          </div>
          <AchievementBar v-if="ach.adjusted.rate !== null" class="attain-lg" :rate="ach.adjusted.rate" progress="100" kind="revenue" />
          <div class="kpi-sub" style="margin-top: 12px"><span>累计实际</span> ¥ <b>{{ money(ach.actual_sum) }}</b> <span>÷ 累计目标</span> ¥ <b>{{ money(ach.adjusted.target_sum) }}</b></div>
          <div class="kpi-sub"><span>口径：年初至最近导入月实际净利润合计 ÷ 同期目标净利润合计；同期目标合计 ≤ 0 时显示「—」</span></div>
        </div>
      </section>

      <section class="section" aria-labelledby="t-np">
        <div class="section-head">
          <h2 id="t-np" class="section-title">净利润按月构成</h2>
          <div class="meta">达成条刻度线 = 100%（累计对累计）</div>
        </div>
        <div class="table-wrap">
          <table class="table">
            <thead>
              <tr>
                <th>月份</th><th class="num">年初原始目标净利润</th><th class="num">最新调整后目标净利润</th><th class="num">实际净利润</th>
                <th class="num">达成率（原始）</th><th class="num">达成率（调整后）</th><th>达成条（调整后）</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="m in ach.months" :key="m.month">
                <td>{{ m.month }}</td>
                <td class="num">{{ money(m.original_target) }}</td>
                <td class="num">{{ money(m.adjusted_target) }}</td>
                <td class="num">{{ money(m.actual) }}</td>
                <td class="num" :class="rateClass(m.rate_original)">{{ pct(m.rate_original, 1) }}</td>
                <td class="num" :class="rateClass(m.rate_adjusted)">{{ pct(m.rate_adjusted, 1) }}</td>
                <td><AchievementBar v-if="m.rate_adjusted !== null" :rate="m.rate_adjusted" progress="100" kind="revenue" /></td>
              </tr>
              <tr class="total">
                <td>1–{{ monthCount }} 月累计</td>
                <td class="num">{{ money(ach.original.target_sum) }}</td>
                <td class="num">{{ money(ach.adjusted.target_sum) }}</td>
                <td class="num">{{ money(ach.actual_sum) }}</td>
                <td class="num" :class="rateClass(ach.original.rate)">{{ pct(ach.original.rate, 1) }}</td>
                <td class="num" :class="rateClass(ach.adjusted.rate)">{{ pct(ach.adjusted.rate, 1) }}</td>
                <td><AchievementBar v-if="ach.adjusted.rate !== null" :rate="ach.adjusted.rate" progress="100" kind="revenue" /></td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section v-if="data.growth" class="section" aria-labelledby="t-growth">
        <div class="section-head">
          <h2 id="t-growth" class="section-title">部门费用增速 vs 收入增速</h2>
          <div class="meta">{{ data.growth.period }} 对比 {{ data.growth.prior_period }} 金蝶实际</div>
        </div>
        <div v-if="data.growth.available && data.growth.revenue && data.growth.dept_expense">
          <div class="growth-cmp">
            <div class="card">
              <div class="kpi-label">收入合计增速</div>
              <div class="kpi-value">{{ pctSigned(data.growth.revenue.growth) }}</div>
            </div>
            <div class="card">
              <div class="kpi-label">部门费用合计增速</div>
              <div class="kpi-value" :class="{ bad: data.growth.expense_faster }">{{ pctSigned(data.growth.dept_expense.growth) }}</div>
            </div>
            <div class="card">
              <div class="kpi-label">部门费用增速 − 收入增速</div>
              <div class="kpi-value" :class="data.growth.expense_faster ? 'bad' : 'good'">{{ pp(data.growth.gap_pp, 1) }} 个百分点</div>
              <div class="note">{{ data.growth.expense_faster ? '部门费用增长快于收入' : '部门费用增长未快于收入' }}</div>
            </div>
          </div>
          <div class="table-wrap">
            <table class="table">
              <thead>
                <tr><th>项目</th><th class="num">{{ data.growth.prior_period }} 实际</th><th class="num">{{ data.growth.period }} 实际</th><th class="num">增额</th><th class="num">增速</th><th>明细</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>收入合计</td><td class="num">{{ money(data.growth.revenue.prior) }}</td><td class="num">{{ money(data.growth.revenue.current) }}</td>
                  <td class="num">{{ money(data.growth.revenue.increase) }}</td><td class="num">{{ pctSigned(data.growth.revenue.growth) }}</td>
                  <td><RouterLink :to="{ name: 'report-channel' }">渠道×站点偏差</RouterLink></td>
                </tr>
                <tr>
                  <td>部门费用合计</td><td class="num">{{ money(data.growth.dept_expense.prior) }}</td><td class="num">{{ money(data.growth.dept_expense.current) }}</td>
                  <td class="num">{{ money(data.growth.dept_expense.increase) }}</td>
                  <td class="num" :class="{ bad: data.growth.expense_faster }">{{ pctSigned(data.growth.dept_expense.growth) }}</td>
                  <td>—</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
        <div v-else class="card state">
          <div class="state-title">{{ data.growth.message }}</div>
          <div>需要 {{ data.growth.prior_period }} 的金蝶实际。由财务BP在实际数导入中做历史导入后自动显示。</div>
          <div v-if="isBP" class="state-actions"><RouterLink class="btn" :to="{ name: 'import' }">去做历史导入</RouterLink></div>
        </div>
      </section>

      <section class="section" aria-labelledby="t-acc">
        <div class="section-head">
          <h2 id="t-acc" class="section-title">季度预测准确度</h2>
          <div class="meta">|快照预测净利润率 − 实际净利润率|，大于 1.5 个百分点标红</div>
        </div>
        <div v-if="!(data.accuracy ?? []).length" class="card state">
          <div class="state-title">尚无已发布的滚动预测快照</div>
          <div>季度滚动预测发布快照后，这里逐月显示预测净利润率与实际的偏差。</div>
        </div>
        <div v-else class="two-col">
          <div class="table-wrap">
            <table class="table">
              <thead>
                <tr><th>月份</th><th>所属季度快照</th><th class="num">快照预测净利润率</th><th class="num">实际净利润率</th><th class="num">偏差（百分点）</th><th>判定</th></tr>
              </thead>
              <tbody>
                <tr v-for="a in data.accuracy" :key="a.month">
                  <td>{{ a.month }}</td>
                  <td>{{ a.snapshot }}</td>
                  <td class="num">{{ pct(a.forecast_margin) }}</td>
                  <template v-if="a.actual_imported">
                    <td class="num">{{ pct(a.actual_margin) }}</td>
                    <td class="num" :class="{ bad: a.flagged }">{{ money(a.deviation_pp) }}</td>
                    <td><span class="badge" :class="{ 'badge-bad': a.flagged }">{{ a.flagged ? '超阈值' : '未超' }}</span></td>
                  </template>
                  <template v-else>
                    <td class="num muted">实际未导入</td><td class="num muted">—</td><td><span class="badge">待金蝶实际</span></td>
                  </template>
                </tr>
              </tbody>
            </table>
            <div class="note" style="padding: 0 10px 8px">净利润率 = 净利润 ÷ 人民币收入；按未四舍五入值与 1.5 比较，等于 1.5 不标红。</div>
          </div>
          <div class="card chart-card">
            <div class="kpi-label" style="margin-bottom: 8px">各月偏差（百分点）</div>
            <svg :viewBox="`0 0 ${W} ${H}`" role="img" aria-label="各月净利润率预测偏差柱状图">
              <template v-for="t in ticks" :key="t">
                <line class="grid" :x1="L" :x2="W - R" :y1="yOf(t)" :y2="yOf(t)" />
                <text :x="L - 6" :y="yOf(t) + 4" text-anchor="end">{{ t.toFixed(1) }}</text>
              </template>
              <template v-for="b in bars" :key="b.m">
                <rect class="bar" :class="{ 'is-bad': b.bad }" :x="b.x" :y="b.y" :width="b.w" :height="b.h" />
                <text class="val" :x="b.x + b.w / 2" :y="b.y - 4" text-anchor="middle">{{ b.label }}</text>
                <text :x="b.x + b.w / 2" :y="H - 10" text-anchor="middle">{{ b.m.slice(5) }} 月</text>
              </template>
              <line class="threshold" :x1="L" :x2="W - R" :y1="yOf(THRESHOLD)" :y2="yOf(THRESHOLD)" />
              <text class="thr" :x="W - R + 6" :y="yOf(THRESHOLD) + 4" text-anchor="start">阈值 1.5</text>
              <line class="axis" :x1="L" :x2="W - R" :y1="yOf(0)" :y2="yOf(0)" />
            </svg>
          </div>
        </div>
      </section>

      <div class="link-row">
        <RouterLink :to="{ name: 'report-channel' }">查看渠道×站点偏差</RouterLink>
        <RouterLink :to="{ name: 'versions' }">查看预算版本</RouterLink>
      </div>
    </template>
  </div>
</template>

<style scoped>
.grid-kpi { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--space-4); margin-bottom: var(--space-6); }
.kpi-row { display: flex; align-items: baseline; justify-content: space-between; gap: var(--space-3); margin: var(--space-2) 0 var(--space-3); }
.kpi-sub { font-size: var(--text-sm); color: var(--fg-2); font-variant-numeric: tabular-nums; }
.kpi-sub span { color: var(--muted); }
.kpi-sub b { color: var(--fg); font-weight: 400; }
.attain-lg :deep(.attain) { width: 100%; }
.attain-lg { display: flex; width: 100%; }
.two-col { display: grid; grid-template-columns: minmax(0, 1fr) 320px; gap: var(--space-4); align-items: start; }
.growth-cmp { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: var(--space-4); margin-bottom: var(--space-4); }
.growth-cmp .kpi-value { font-size: var(--text-2xl); }
.note { font-size: var(--text-xs); color: var(--muted); margin-top: var(--space-2); }
.chart-card svg { display: block; width: 100%; height: auto; }
.chart-card .axis { stroke: var(--border); stroke-width: 1; }
.chart-card .grid { stroke: var(--border-soft); stroke-width: 1; }
.chart-card .threshold { stroke: var(--danger); stroke-width: 1; stroke-dasharray: 4 3; }
.chart-card .bar { fill: var(--fg-2); }
.chart-card .bar.is-bad { fill: var(--danger); }
.chart-card text { fill: var(--muted); font-size: 11px; font-family: var(--font-body); }
.chart-card text.val { fill: var(--fg); font-variant-numeric: tabular-nums; }
.chart-card text.thr { fill: var(--danger); }
.table a, .link-row a { color: var(--fg-2); }
.link-row { display: flex; gap: var(--space-4); font-size: var(--text-sm); }
@media (max-width: 1360px) { .two-col { grid-template-columns: 1fr; } }
</style>
