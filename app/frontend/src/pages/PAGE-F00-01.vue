<script setup lang="ts">
/**
 * 工作台 PAGE-F00-01（API-F00-01 GET /api/workbench，DEC-001）
 * - 我的待办（全部角色）：待填报、待审批、未处理预警，各最多 5 条
 * - 关键数（CEO、财务负责人）：达成率双口径（与公司汇总同一函数）、最近季度预测偏差、编制任务提交率
 * - 导入与核对（财务BP）：金蝶 / BI 最近导入期间、BI 与金蝶差异超 3% 的组合数
 * 无权限区块不渲染（不置灰）；页面不提供编辑操作。
 */
import { computed, onMounted, ref } from 'vue'
import { api, ApiError } from '@/api/client'
import AchievementBar from '@/components/AchievementBar.vue'
import PageState from '@/components/PageState.vue'
import { money, pct } from '@/components/g4/format'
import { fmtTime } from '@/components/g2/util'
import { useUserStore } from '@/stores/user'

interface TodoBlock<T> { count: number; items: T[] }
interface FillingItem { id: number; task_name: string; unit_name: string; status_label: string; deadline: string | null; link: string }
interface ApprovalItem { type: string; id: number; title: string; kind_label?: string; prev_step?: string; submitted_at: string | null; link: string }
interface AlertItem { id: number; object_name: string; period: string; rule_name: string; rule_version: string; link: string }
interface Side { version: { name: string } | null; target_sum: string; rate: string | null; has_adjustment?: boolean }
interface Workbench {
  user: { name: string; role_names: string[] }
  today: string
  year: number
  budget_year: number
  kingdee_latest: string | null
  filling_list_link: string
  todo: { filling: TodoBlock<FillingItem>; approvals: TodoBlock<ApprovalItem>; alerts: TodoBlock<AlertItem> }
  key_metrics: null | {
    achievement: null | { period_label: string; through: string; actual_sum: string; original: Side; adjusted: Side }
    forecast: null | { quarter: number; snapshot: string; months: { month: string; deviation_pp: string | null; flagged: boolean }[] }
    submit: { task: null | { id: number; name: string; status_label: string }; in_progress: boolean; submitted?: number; total?: number; rate?: string | null }
  }
  imports: null | {
    kingdee_latest: string | null
    bi_latest: string | null
    bi_recent_months: string[]
    reconcile: { month: string | null; count: number }
  }
}

const user = useUserStore()
const data = ref<Workbench | null>(null)
const loading = ref(true)
const error = ref<unknown>(null)
const noRole = computed(() => error.value instanceof ApiError && (error.value.code === 'no_role' || error.value.isForbidden))

async function load(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    data.value = await api.get<Workbench>('/api/workbench')
  } catch (e) {
    error.value = e
  } finally {
    loading.value = false
  }
}
onMounted(load)

const todos = computed(() => {
  const d = data.value
  if (!d) return []
  return [
    {
      title: '待填报', all: d.filling_list_link, block: d.todo.filling, empty: '当前没有需要你填报的单位',
      items: d.todo.filling.items.map((it) => ({
        key: `f${it.id}`, link: it.link, t1: `${it.task_name} · ${it.unit_name}`,
        t2: [it.status_label, it.deadline ? `截止 ${it.deadline}` : ''].filter(Boolean).join(' · '),
      })),
    },
    {
      title: '待审批', all: '/approvals', block: d.todo.approvals, empty: '当前没有待你审批的事项',
      items: d.todo.approvals.items.map((it) => ({
        key: `a${it.type}${it.id}`, link: it.link || `/approvals/${it.type}/${it.id}`, t1: it.title,
        t2: [it.kind_label, it.prev_step ? `上一环节：${it.prev_step}` : '', it.submitted_at ? `提交于 ${fmtTime(it.submitted_at)}` : ''].filter(Boolean).join(' · '),
      })),
    },
    {
      title: '未处理预警', all: '/alerts', block: d.todo.alerts, empty: '你的数据范围内没有未处理预警',
      items: d.todo.alerts.items.map((it) => ({
        key: `w${it.id}`, link: it.link, t1: `${it.object_name} · ${it.rule_name}`, t2: `${it.period} · ${it.rule_name} ${it.rule_version}`,
      })),
    },
  ]
})

const km = computed(() => data.value?.key_metrics ?? null)
const isFinanceHead = computed(() => user.me?.roles.includes('finance_head') ?? false)
const submitLink = computed(() => {
  const s = km.value?.submit
  return s?.in_progress && s.task ? `/tasks/${s.task.id}` : '/tasks'
})
</script>

<template>
  <div data-page-id="PAGE-F00-01">
    <div class="page-head wb-head">
      <h1 class="page-title">工作台</h1>
      <span v-if="data" class="meta">{{ data.today }} · 预算年度 {{ data.budget_year }} · 最近金蝶导入期间 {{ data.kingdee_latest ?? '尚未导入' }}</span>
    </div>

    <div v-if="loading" class="grid-3" aria-busy="true">
      <div v-for="i in 3" :key="i" class="card">
        <div class="skeleton" style="width: 40%"></div>
        <div class="skeleton" style="width: 30%; height: 28px; margin: 16px 0"></div>
        <div class="skeleton"></div>
        <div class="skeleton" style="margin-top: 12px"></div>
      </div>
    </div>
    <PageState v-else-if="noRole" state="forbidden" title="未开通预算权限，请联系财务负责人" description="你的预算角色已被撤销，本次请求未返回任何数据。">
      <template #action><RouterLink class="btn" :to="{ name: 'login' }">返回登录页</RouterLink></template>
    </PageState>
    <PageState v-else-if="error" state="error" title="工作台数据加载失败" description="网络异常或服务暂时不可用，请重试" @retry="load" />

    <template v-else-if="data">
      <h2 class="sec-title" style="margin-top: 0">我的待办</h2>
      <div class="grid-3">
        <div v-for="t in todos" :key="t.title" class="card" :data-testid="`todo-${t.title}`">
          <div class="todo-head">
            <span class="kpi-label">{{ t.title }}</span>
            <RouterLink v-if="t.block.count > 0" :to="t.all">查看全部</RouterLink>
          </div>
          <div class="todo-count">{{ t.block.count }}</div>
          <ul v-if="t.items.length" class="todo-list">
            <li v-for="it in t.items" :key="it.key">
              <RouterLink :to="it.link"><div class="t1">{{ it.t1 }}</div><div class="t2">{{ it.t2 }}</div></RouterLink>
            </li>
          </ul>
          <div v-else class="todo-empty">{{ t.empty }}</div>
        </div>
      </div>

      <template v-if="km">
        <h2 class="sec-title">关键数</h2>
        <div v-if="!km.achievement && !km.forecast && !km.submit.task" class="card state">
          <div class="state-title">还没有可计算的关键数</div>
          <p>年初原始目标经 CEO 审批、且导入第一个月金蝶实际后，这里显示净利润达成率与预测偏差。</p>
          <RouterLink v-if="isFinanceHead" class="btn btn-primary" :to="{ name: 'tasks' }">发布编制任务</RouterLink>
        </div>
        <div v-else class="grid-4">
          <div class="card kpi-card fade-in" data-testid="kpi-original">
            <div class="kpi-label">累计净利润达成率 · 年初原始目标</div>
            <template v-if="km.achievement">
              <div class="kpi-value">{{ pct(km.achievement.original.rate, 1) }}</div>
              <div class="kpi-row">
                <AchievementBar v-if="km.achievement.original.rate !== null" :rate="km.achievement.original.rate" kind="revenue" />
                <span class="kpi-sub" style="margin: 0">{{ km.achievement.period_label }}</span>
              </div>
              <div class="kpi-sub">实际 ¥ {{ money(km.achievement.actual_sum) }} / 目标 ¥ {{ money(km.achievement.original.target_sum) }}</div>
            </template>
            <div v-else class="kpi-value small">—</div>
            <div class="kpi-sub">年初至最近导入月实际净利润合计 ÷ 同期目标合计；目标合计 ≤ 0 时显示「—」</div>
          </div>
          <div class="card kpi-card fade-in" data-testid="kpi-adjusted">
            <div class="kpi-label">累计净利润达成率 · 调整后目标</div>
            <template v-if="km.achievement">
              <div class="kpi-value">{{ pct(km.achievement.adjusted.rate, 1) }}</div>
              <div class="kpi-row">
                <AchievementBar v-if="km.achievement.adjusted.rate !== null" :rate="km.achievement.adjusted.rate" kind="revenue" />
                <span class="kpi-sub" style="margin: 0">{{ km.achievement.adjusted.has_adjustment ? km.achievement.adjusted.version?.name : '尚无调整版本' }}</span>
              </div>
              <div class="kpi-sub">实际 ¥ {{ money(km.achievement.actual_sum) }} / 目标 ¥ {{ money(km.achievement.adjusted.target_sum) }}</div>
            </template>
            <div v-else class="kpi-value small">—</div>
            <div class="kpi-sub">年初至最近导入月实际净利润合计 ÷ 同期目标合计；目标合计 ≤ 0 时显示「—」</div>
          </div>
          <div class="card kpi-card fade-in" data-testid="kpi-forecast">
            <template v-if="km.forecast">
              <div class="kpi-label">最近季度预测偏差 · {{ data.year }} 第 {{ km.forecast.quarter }} 季度快照</div>
              <table v-if="km.forecast.months.length" class="mini" aria-label="各月预测偏差（百分点）">
                <tbody>
                  <tr v-for="m in km.forecast.months" :key="m.month">
                    <td>{{ m.month }}</td>
                    <td class="num" :class="{ bad: m.flagged }">{{ money(m.deviation_pp) }} 个百分点</td>
                  </tr>
                </tbody>
              </table>
              <div v-else class="kpi-sub">该季度各月金蝶实际尚未导入</div>
            </template>
            <template v-else>
              <div class="kpi-label">最近季度预测偏差</div>
              <div class="kpi-value small">尚无已发布的滚动预测快照</div>
            </template>
            <div class="kpi-sub">|快照预测净利润率 − 实际净利润率|，大于 1.5 个百分点标红 · <RouterLink :to="{ name: 'report-company' }">公司汇总</RouterLink></div>
          </div>
          <div class="card kpi-card fade-in" data-testid="kpi-submit">
            <div class="kpi-label">编制任务提交率</div>
            <template v-if="km.submit.task && km.submit.in_progress">
              <div class="kpi-value">{{ pct(km.submit.rate ?? null, 1) }}</div>
              <div class="kpi-sub">{{ km.submit.task.name }}<br />提交率 {{ pct(km.submit.rate ?? null, 1) }}（{{ km.submit.submitted }} / {{ km.submit.total }} 个单位）</div>
            </template>
            <template v-else>
              <div class="kpi-value small">无进行中的任务</div>
              <div v-if="km.submit.task" class="kpi-sub">最近：{{ km.submit.task.name }} · {{ km.submit.task.status_label }}<br />提交率 {{ pct(km.submit.rate ?? null, 1) }}（{{ km.submit.submitted }} / {{ km.submit.total }} 个单位）</div>
            </template>
            <div class="kpi-sub"><RouterLink :to="submitLink">编制任务</RouterLink></div>
          </div>
        </div>
      </template>

      <template v-if="data.imports">
        <h2 class="sec-title">导入与核对</h2>
        <div class="grid-4">
          <div class="card kpi-card">
            <div class="kpi-label">金蝶实际 · 最近导入期间</div>
            <div class="kpi-value">{{ data.imports.kingdee_latest ?? '—' }}</div>
            <div class="kpi-sub"><RouterLink :to="{ name: 'import' }">实际数导入</RouterLink></div>
          </div>
          <div class="card kpi-card">
            <div class="kpi-label">BI 数据 · 最近导入批次</div>
            <div class="kpi-value">{{ data.imports.bi_latest ?? '—' }}</div>
            <div class="kpi-sub">
              <template v-if="data.imports.bi_latest">截至 {{ data.imports.bi_latest }}，最近批次覆盖 {{ data.imports.bi_recent_months.join('～') }}</template>
              <template v-else>尚未导入 BI 数据</template>
              · <RouterLink :to="{ name: 'import' }">实际数导入</RouterLink>
            </div>
          </div>
          <div class="card kpi-card">
            <div class="kpi-label">BI 与金蝶差异超 3% 的组合</div>
            <div class="kpi-value" :class="{ bad: data.imports.reconcile.count > 0 }">{{ data.imports.reconcile.count }}</div>
            <div class="kpi-sub">{{ data.imports.reconcile.month ?? '暂无两方都已导入的月份' }} · 店铺 × 站点 · <RouterLink :to="{ name: 'reconcile' }">去核对</RouterLink></div>
          </div>
        </div>
      </template>
    </template>
  </div>
</template>

<style scoped>
.wb-head { display: flex; align-items: baseline; gap: var(--space-4); margin-bottom: var(--space-4); }
.wb-head .page-title { margin: 0; }
.meta { color: var(--muted); font-size: var(--text-sm); }
.sec-title { font-size: var(--text-lg); font-weight: 600; margin: var(--space-6) 0 var(--space-3); }
.grid-3 { display: grid; grid-template-columns: repeat(3, 1fr); gap: var(--space-4); }
.grid-4 { display: grid; grid-template-columns: repeat(4, 1fr); gap: var(--space-4); }
.todo-head { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: var(--space-3); }
.todo-head a { font-size: var(--text-sm); color: var(--fg-2); }
.todo-count { font-size: var(--text-3xl); font-variant-numeric: tabular-nums; letter-spacing: var(--tracking-display); line-height: var(--leading-tight); margin-bottom: var(--space-3); }
.todo-list { list-style: none; margin: 0; padding: 0; }
.todo-list li { border-top: 1px solid var(--border-soft); }
.todo-list a { display: block; padding: var(--space-2) 0; color: var(--fg); text-decoration: none; border-radius: var(--radius-sm); transition: background var(--motion-fast) var(--ease-standard); }
.todo-list a:hover { background: var(--surface-raised); }
.todo-list a:focus-visible { outline: none; box-shadow: var(--focus-ring); }
.todo-list .t1 { font-size: var(--text-sm); }
.todo-list .t2 { font-size: var(--text-xs); color: var(--muted); }
.todo-empty { font-size: var(--text-sm); color: var(--muted); padding: var(--space-2) 0; border-top: 1px solid var(--border-soft); }
.kpi-sub { font-size: var(--text-xs); color: var(--muted); margin-top: var(--space-2); font-variant-numeric: tabular-nums; }
.kpi-row { display: flex; align-items: center; gap: var(--space-3); margin-top: var(--space-3); }
.kpi-card a { color: var(--fg-2); font-size: var(--text-xs); }
.mini { width: 100%; border-collapse: collapse; font-size: var(--text-sm); margin-top: var(--space-2); }
.mini td { padding: var(--space-1) 0; border-top: 1px solid var(--border-soft); }
.mini td.num { text-align: right; font-variant-numeric: tabular-nums; }
.kpi-card .kpi-value.small { font-size: var(--text-2xl); }
</style>
