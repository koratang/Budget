<script setup lang="ts">
/**
 * PAGE-F07-02 审批详情：头部卡片 + 审批进度链 + 按单据类型的只读内容 + 吸底操作栏（通过 / 退回，退回原因必填）。
 * 单位填报与全公司预算由 G2 提供内容；目标调整、规则审批按 G3 返回的字段展示。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { api, ApiError } from '@/api/client'
import PageState from '@/components/PageState.vue'
import G2Modal from '@/components/g2/G2Modal.vue'
import { errorText, toast } from '@/components/g2/util'
import { useUiStore } from '@/stores/ui'
import '@/components/g2/g2.css'

interface Col {
  key: string
  label: string
  num: boolean
}
interface ChainStep {
  label: string
  who: string
  result: string
  at: string | null
  state: 'done' | 'current' | 'todo'
}
interface TableContent {
  kind: 'table'
  note: string | null
  columns: Col[]
  rows: Record<string, string>[]
  total: Record<string, string> | null
}
interface CompanyContent {
  kind: 'company'
  note: string
  kpis: Record<string, string>
  quarters: Record<string, string>[]
  segments: Record<string, string>[]
  total: Record<string, string>
}
interface Rec {
  level: string
  action: string
  reason: string | null
  who?: string | null
  approver_name?: string | null
  at: string | null
}
interface Detail {
  type: string
  id: number
  title?: string
  name?: string
  rule_name?: string
  kind_label?: string
  status?: string
  status_label?: string
  submitter?: string | null
  submitted_at?: string | null
  chain?: ChainStep[]
  can_act: boolean
  approve_label?: string
  approve_hint?: string
  reject_hint?: string
  content?: TableContent | CompanyContent
  history?: Rec[]
  records?: Rec[]
  ceo_records?: Rec[]
  // 目标调整（G3）
  adjust_reason?: string | null
  filler_name?: string
  step?: string
  units?: { name: string; status_label: string; adjust_reason: string | null; step?: string }[]
  reasons?: { unit: string; reason: string }[]
  year?: number
  quarter?: number
  // 规则（G3）
  rule_type_label?: string
  needs_ceo?: boolean
  version?: Record<string, unknown> & { version_no?: number }
  effective_version?: (Record<string, unknown> & { version_no?: number }) | null
}

const LEVEL_LABEL: Record<string, string> = { dept_head: '部门负责人', finance_head: '财务负责人', ceo: 'CEO' }
const TYPE_LABEL: Record<string, string> = { unit: '预算编制', task: '预算编制', 'adjustment-unit': '目标调整', adjustment: '目标调整', 'rule-version': '规则审批' }

const route = useRoute()
const ui = useUiStore()
const d = ref<Detail | null>(null)
const loading = ref(true)
const error = ref<unknown>(null)
const result = ref<string | null>(null)

const path = computed(() => `/api/approvals/${route.params.type}/${route.params.id}`)
const title = computed(() => {
  const x = d.value
  if (!x) return ''
  if (x.title) return x.title
  if (x.type === 'rule-version') return `${x.rule_name ?? '规则'}（v${x.version?.version_no ?? ''}）`
  if (x.type === 'adjustment') return `${x.year} Q${x.quarter} 目标调整（整次终审）`
  return x.name ?? `${x.type} #${x.id}`
})
const records = computed<Rec[]>(() => d.value?.history ?? d.value?.records ?? d.value?.ceo_records ?? [])
const approveLabel = computed(() => d.value?.approve_label ?? (d.value?.type === 'adjustment' ? '整次通过' : '通过'))

async function load(): Promise<void> {
  loading.value = d.value === null
  error.value = null
  try {
    d.value = await api.get<Detail>(path.value)
    ui.setCrumbTitle(title.value)
  } catch (e) {
    error.value = e
  } finally {
    loading.value = false
  }
}
onMounted(load)
watch(path, () => {
  d.value = null
  result.value = null
  void load()
})

function fmtContent(v: unknown): string {
  if (v === null || v === undefined) return '—'
  if (typeof v === 'string' || typeof v === 'number') return String(v)
  if (Array.isArray(v)) return v.map(fmtContent).join('、')
  if (typeof v === 'object') {
    const o = v as Record<string, unknown>
    if (typeof o.text === 'string') return o.text
    if (typeof o.summary === 'string') return o.summary
    return Object.entries(o)
      .filter(([, x]) => x !== null && typeof x !== 'object')
      .map(([k, x]) => `${k}：${String(x)}`)
      .join('；')
  }
  return String(v)
}

// ---- 通过 / 退回 ----
const approveOpen = ref(false)
const rejectOpen = ref(false)
const reason = ref('')
const reasonErr = ref('')
const busy = ref(false)
async function doApprove(): Promise<void> {
  if (busy.value) return
  busy.value = true
  try {
    const res = await api.post<{ message?: string; status_label?: string }>(`${path.value}/approve`)
    approveOpen.value = false
    result.value = res.message ?? '已通过'
    toast(result.value)
    await load()
  } catch (e) {
    approveOpen.value = false
    toast(errorText(e))
  } finally {
    busy.value = false
  }
}
async function doReject(): Promise<void> {
  if (!reason.value.trim()) {
    reasonErr.value = '请填写退回原因'
    return
  }
  if (busy.value) return
  busy.value = true
  try {
    const res = await api.post<{ message?: string }>(`${path.value}/reject`, { reason: reason.value })
    rejectOpen.value = false
    result.value = res.message ?? '已退回'
    toast(result.value)
    await load()
  } catch (e) {
    reasonErr.value = e instanceof ApiError ? e.message : errorText(e)
  } finally {
    busy.value = false
  }
}
function openReject(): void {
  reason.value = ''
  reasonErr.value = ''
  rejectOpen.value = true
}
</script>

<template>
  <div data-page-id="PAGE-F07-02" class="g2 g2-approval">
    <div class="page-head"><h1 class="page-title">审批详情</h1></div>
    <PageState v-if="loading" state="loading" />
    <PageState
      v-else-if="error && error instanceof ApiError && error.status === 404"
      state="empty"
      title="该审批事项已不存在或已被处理"
      description="可能已由其他审批人处理，或提交人已撤回后重新提交。"
    >
      <template #action><RouterLink class="btn" :to="{ name: 'approvals' }">返回待我审批</RouterLink></template>
    </PageState>
    <PageState
      v-else-if="error"
      :error="error"
      :title="error instanceof ApiError && error.isForbidden ? '无权限' : '数据加载失败'"
      :description="error instanceof ApiError && error.isForbidden ? '你不是该事项当前环节的审批人，不能查看或处理。' : undefined"
      @retry="load"
    />
    <template v-else-if="d">
      <section class="card head-card" aria-labelledby="h-name">
        <div class="row" style="margin-bottom: var(--space-2)">
          <span class="badge">{{ d.kind_label ?? TYPE_LABEL[d.type] }}</span>
          <span :class="d.can_act ? 'badge badge-warn' : 'badge'" data-detail-status>{{ d.can_act ? '待你审核' : d.status_label }}</span>
          <span class="spacer"></span>
          <span v-if="d.submitter || d.filler_name" class="small muted">提交人：{{ d.submitter ?? d.filler_name }}<template v-if="d.submitted_at"> · 提交时间 {{ d.submitted_at }}</template></span>
        </div>
        <h2 id="h-name">{{ title }}</h2>
        <p class="small muted" style="margin: 0 0 var(--space-4)">审批人只读查看，不能修改数值；如需修改请退回并写明原因。</p>
        <ol v-if="d.chain" class="chain" aria-label="审批进度">
          <li v-for="s in d.chain" :key="s.label" :class="{ done: s.state === 'done', now: s.state === 'current', back: s.result.includes('退回') }">
            <div>{{ s.label }}</div>
            <div class="who">{{ s.who }}</div>
            <div class="when">{{ s.result }}<template v-if="s.at"> · {{ s.at }}</template></div>
          </li>
        </ol>
      </section>

      <!-- 单位填报 / 比例 / 部门费用（只读表） -->
      <section v-if="d.content?.kind === 'table'" class="section" aria-label="填报内容">
        <div class="row" style="margin-bottom: var(--space-3)">
          <h3 class="section-title" style="margin: 0">填报内容（全年合计，只读）</h3>
          <span class="spacer"></span>
          <span v-if="d.content.note" class="small muted">{{ d.content.note }}</span>
        </div>
        <div class="table-wrap">
          <table class="table">
            <thead><tr><th v-for="c in d.content.columns" :key="c.key" :class="{ num: c.num }">{{ c.label }}</th></tr></thead>
            <tbody>
              <tr v-for="(r, i) in d.content.rows" :key="i">
                <td v-for="c in d.content.columns" :key="c.key" :class="{ num: c.num }">{{ r[c.key] ?? '' }}</td>
              </tr>
              <tr v-if="d.content.total" class="total">
                <td v-for="c in d.content.columns" :key="c.key" :class="{ num: c.num }">{{ d.content.total[c.key] ?? '' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <!-- 全公司预算（CEO） -->
      <section v-if="d.content?.kind === 'company'" class="section" aria-label="全公司预算">
        <div class="grid-4 section">
          <div class="card fade-in"><div class="kpi-label">全年收入</div><div class="kpi-value" style="font-size: var(--text-xl)">{{ d.content.kpis.revenue }}</div></div>
          <div class="card fade-in"><div class="kpi-label">全年毛利</div><div class="kpi-value" style="font-size: var(--text-xl)">{{ d.content.kpis.gross_profit }}</div><div class="kpi-sub">毛利率 {{ d.content.kpis.gross_margin }}</div></div>
          <div class="card fade-in"><div class="kpi-label">部门费用</div><div class="kpi-value" style="font-size: var(--text-xl)">{{ d.content.kpis.dept_expense }}</div></div>
          <div class="card fade-in"><div class="kpi-label">净利润</div><div class="kpi-value" style="font-size: var(--text-xl)">{{ d.content.kpis.net_profit }}</div><div class="kpi-sub">净利润率 {{ d.content.kpis.net_margin }}</div></div>
        </div>
        <div class="section">
          <h3 class="section-title">按季度</h3>
          <div class="table-wrap">
            <table class="table">
              <thead><tr><th>项目</th><th v-for="q in d.content.quarters" :key="q.label" class="num">{{ q.label }}</th></tr></thead>
              <tbody>
                <tr v-for="[k, l] in [['revenue_cny', '收入'], ['gross_profit', '毛利'], ['dept_expense', '部门费用'], ['other_pl', '公司层其他损益'], ['net_profit', '净利润'], ['net_margin', '净利润率']]" :key="k">
                  <td>{{ l }}</td>
                  <td v-for="q in d.content.quarters" :key="q.label" class="num">{{ q[k] }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
        <h3 class="section-title">按渠道 / B端（全年）</h3>
        <div class="table-wrap">
          <table class="table">
            <thead><tr><th>渠道 / 客户</th><th class="num">收入</th><th class="num">毛利</th><th class="num">毛利率</th></tr></thead>
            <tbody>
              <tr v-for="s in d.content.segments" :key="s.kind_label + s.name">
                <td>{{ s.kind_label }} · {{ s.name }}</td><td class="num">{{ s.revenue }}</td><td class="num">{{ s.gross_profit }}</td><td class="num">{{ s.gross_margin }}</td>
              </tr>
              <tr class="total"><td>合计</td><td class="num">{{ d.content.total.revenue }}</td><td class="num">{{ d.content.total.gross_profit }}</td><td class="num">{{ d.content.total.gross_margin }}</td></tr>
            </tbody>
          </table>
        </div>
        <p class="small muted">{{ d.content.note }}。公共部门费用与公司层其他损益不分摊到渠道。</p>
      </section>

      <!-- 目标调整（G3） -->
      <section v-if="d.type === 'adjustment-unit'" class="section">
        <div class="notice warn section"><strong>调整原因：</strong>{{ d.adjust_reason ?? '—' }}</div>
        <p class="small muted">当前环节：{{ d.step ?? d.status_label }}。可在 <RouterLink class="link" :to="{ name: 'version-compare' }">版本对比</RouterLink> 查看已生效版本之间的差额。</p>
      </section>
      <section v-if="d.type === 'adjustment'" class="section">
        <div class="notice section">全部调整单位依次经部门负责人、财务负责人审核通过后，CEO 对整次调整一次性审批：通过即生成新的「调整后目标」版本。</div>
        <div class="table-wrap">
          <table class="table">
            <thead><tr><th>调整单位</th><th>调整原因</th><th>状态</th></tr></thead>
            <tbody>
              <tr v-for="u in d.units ?? []" :key="u.name"><td>{{ u.name }}</td><td class="wrap">{{ u.adjust_reason ?? '—' }}</td><td>{{ u.status_label }}</td></tr>
            </tbody>
          </table>
        </div>
      </section>

      <!-- 规则审批（G3） -->
      <section v-if="d.type === 'rule-version' && d.version" class="section">
        <div class="grid-2">
          <div class="card">
            <h3 class="section-title">待审批版本 v{{ d.version.version_no }}</h3>
            <dl class="kv">
              <dt>规则名称</dt><dd>{{ d.rule_name }}</dd>
              <dt>类型</dt><dd>{{ d.rule_type_label }}<template v-if="d.needs_ceo">（财务负责人通过后还需 CEO 审批）</template></dd>
              <dt>可信度状态</dt><dd><span class="badge">{{ fmtContent(d.version.credibility_label) }}</span></dd>
              <dt>规则内容</dt><dd>{{ fmtContent(d.version.content) }}</dd>
              <dt>依据</dt><dd>{{ fmtContent(d.version.basis) }}</dd>
              <dt>提交人</dt><dd>{{ fmtContent(d.version.submitted_by_name) }} · {{ fmtContent(d.version.submitted_at) }}</dd>
            </dl>
          </div>
          <div class="card">
            <h3 class="section-title">当前生效版本</h3>
            <dl v-if="d.effective_version" class="kv">
              <dt>版本</dt><dd>v{{ d.effective_version.version_no }}</dd>
              <dt>规则内容</dt><dd>{{ fmtContent(d.effective_version.content) }}</dd>
            </dl>
            <p v-else class="muted">这是该规则的第 1 版，当前没有生效版本。审批全部通过后本版本生效。</p>
            <p><RouterLink class="link" :to="{ name: 'rules' }">在规则库中查看该规则与版本历史</RouterLink></p>
          </div>
        </div>
      </section>

      <section v-if="records.length" class="section">
        <h3 class="section-title">审批记录</h3>
        <ul class="small" style="padding-left: var(--space-6); margin: 0">
          <li v-for="(r, i) in records" :key="i">
            {{ r.at }} · {{ LEVEL_LABEL[r.level] ?? r.level }} {{ r.who ?? r.approver_name }} {{ r.action === 'approve' ? '通过' : '退回' }}<template v-if="r.reason">：{{ r.reason }}</template>
          </li>
        </ul>
      </section>

      <div v-if="d.can_act" class="actionbar" data-actionbar>
        <span class="small muted">{{ d.approve_hint ?? '通过后进入下一环节。' }}</span>
        <span class="spacer"></span>
        <button class="btn btn-danger" type="button" data-reject @click="openReject">退回</button>
        <button class="btn btn-primary" type="button" data-approve @click="approveOpen = true">{{ approveLabel }}</button>
      </div>
      <div v-else-if="result" class="notice good" role="status" data-result style="margin-top: var(--space-4)">{{ result }}</div>
    </template>

    <G2Modal v-if="approveOpen && d" :title="`${approveLabel}？`" @close="approveOpen = false">
      <p>{{ d.approve_hint ?? '通过后进入下一环节。' }}</p>
      <template #actions>
        <button class="btn" type="button" @click="approveOpen = false">取消</button>
        <button class="btn btn-primary" type="button" data-confirm-approve :disabled="busy" @click="doApprove">{{ approveLabel }}</button>
      </template>
    </G2Modal>
    <G2Modal v-if="rejectOpen && d" title="退回" @close="rejectOpen = false">
      <p class="sub">{{ d.reject_hint ?? '退回后提交人可修改后重新提交。' }}</p>
      <div class="field">
        <label for="rej-reason">退回原因<span class="req">*</span></label>
        <textarea id="rej-reason" v-model="reason" class="input" :aria-invalid="reasonErr ? 'true' : 'false'"></textarea>
        <div v-if="reasonErr" class="field-error" data-reason-error>{{ reasonErr }}</div>
      </div>
      <template #actions>
        <button class="btn" type="button" @click="rejectOpen = false">取消</button>
        <button class="btn btn-danger" type="button" data-confirm-reject :disabled="busy" @click="doReject">确认退回</button>
      </template>
    </G2Modal>
  </div>
</template>
