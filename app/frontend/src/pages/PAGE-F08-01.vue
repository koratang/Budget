<script setup lang="ts">
/**
 * PAGE-F08-01 预算版本：版本列表、本季度目标调整与滚动预测、发起调整 / 滚动更新 / 发布快照 / Q1 以原始目标发布；
 * 填报人查看本人负责单位的调整进度并进入填报表格「调整模式」（API-F08-01~04、API-F08-06）。
 */
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, ApiError } from '@/api/client'
import PageState from '@/components/PageState.vue'
import G3Modal from '@/components/g3/G3Modal.vue'
import { errorText, useToast } from '@/components/g3/useG3'
import '@/components/g3/g3.css'

interface VersionRow {
  id: number; label: string; type: string; type_label: string; quarter_label: string; status_label: string
  current: boolean; approver: string; time: string | null; reason: string
}
interface UnitRow {
  id: number; name: string; unit_type: string; status: string; status_label: string; step: string
  submitted_at: string | null; filler_id: number; reviewer_name: string; return_reason: string | null
}
interface Adjustment {
  id: number; year: number; quarter: number; status: string; status_label: string; initiated_by_name: string | null
  initiated_at: string | null; adjustable_months: string[]; result_version: string | null; effective_at: string | null
  ceo_return_reason: string | null
  progress: { total: number; submitted: number; dept_approved: number; finance_approved: number }
}
interface RollingUnit { key: string; name: string; unit_type_label: string; filler_name: string | null; submitted: boolean; submitted_at: string | null }
interface Rolling {
  id: number; quarter: number; type: string; status_label: string; initiated_by_name: string | null; initiated_at: string | null
  published_on: string | null; open_months_text: string; progress: { total: number; submitted: number }
  unsubmitted: RollingUnit[]; basis: string | null
}
interface PageData {
  year: number; years: number[]; today: string; quarter: number | null; actual_through: string | null
  is_finance_head: boolean; versions: VersionRow[]; adjustment: Adjustment | null; adjustable_months: string[]
  rolling: Rolling | null
  actions: { adjust: { enabled: boolean; reason: string | null }; rolling: { enabled: boolean; reason: string | null }; publish_original: { visible: boolean } }
  my_adjustment_units: UnitRow[]
  my_rolling: { id: number; quarter: number; units: RollingUnit[]; open_months_text: string; actual_through: string | null } | null
}

const QUARTER_NAMES = ['', '第一季度', '第二季度', '第三季度', '第四季度']
const router = useRouter()
const data = ref<PageData | null>(null)
const year = ref<number | undefined>(undefined)
const loading = ref(true)
const error = ref<unknown>(null)
const selected = ref<number[]>([])
const modal = ref<'' | 'adj' | 'roll' | 'q1' | 'pub'>('')
const busy = ref(false)
const actionError = ref('')
const { toast, show } = useToast()

async function load(): Promise<void> {
  error.value = null
  try {
    data.value = await api.get<PageData>('/api/versions', { year: year.value })
    year.value = data.value.year
    selected.value = []
  } catch (e) {
    error.value = e
  } finally {
    loading.value = false
  }
}
onMounted(load)

const todayText = computed(() => {
  const d = data.value
  if (!d) return ''
  const q = d.quarter ? ` · ${QUARTER_NAMES[d.quarter]}` : ''
  const a = d.actual_through ? `金蝶实际已导入至 ${d.actual_through}` : `尚未导入 ${d.year} 年金蝶实际`
  return `当前日期 ${d.today}${q} · ${a}`
})
const quarterLabel = computed(() => (data.value?.quarter ? `${data.value.year} Q${data.value.quarter}` : ''))
const adjustMonthsText = computed(() => monthsText(data.value?.adjustable_months ?? []))
const rollMonthsText = computed(() => (data.value?.quarter ? `${data.value.quarter * 3 - 2}–12 月（本季度及以后）` : ''))
const adjustBlock = computed(() => (data.value && !data.value.actions.adjust.enabled ? data.value.actions.adjust.reason : ''))
const rollBlock = computed(() => (data.value && !data.value.actions.rolling.enabled ? data.value.actions.rolling.reason : ''))

function monthsText(months: string[]): string {
  if (!months.length) return '无（全年均已导入金蝶实际）'
  const first = Number(months[0].slice(5))
  const last = Number(months[months.length - 1].slice(5))
  const locked = first > 1 ? `（1–${first - 1} 月已导入金蝶实际）` : '（尚未导入金蝶实际的月份）'
  return `${first}–${last} 月${locked}`
}

function toggle(id: number, checked: boolean): void {
  if (checked) {
    if (selected.value.length >= 2) return
    selected.value = [...selected.value, id]
  } else {
    selected.value = selected.value.filter((x) => x !== id)
  }
}
function compare(): void {
  if (selected.value.length !== 2) return
  const [a, b] = selected.value
  router.push({ name: 'version-compare', query: { a: String(a), b: String(b) } })
}

function unitLink(u: UnitRow) {
  const map: Record<string, string> = { platform: 'fill-platform', b2b: 'fill-b2b', cost_ratio: 'fill-cost', logistics_ratio: 'fill-logistics' }
  if (u.unit_type === 'dept_expense') return { name: 'dept-expense', query: { unitId: String(u.id), mode: 'adjust' } }
  return { name: map[u.unit_type], params: { unitId: String(u.id) }, query: { mode: 'adjust' } }
}
function unitAction(u: UnitRow): string {
  if (u.status === 'adjusting') return u.submitted_at ? '继续调整' : '开始调整'
  if (u.status === 'returned') return '修改后重新提交'
  return '查看'
}
function unitBadge(u: UnitRow): string {
  if (u.status === 'returned') return 'badge-bad'
  if (u.status === 'approved') return 'badge-good'
  if (u.status === 'submitted' || u.status === 'dept_approved') return 'badge-warn'
  return ''
}

async function run(path: string, body: unknown, message: string): Promise<void> {
  busy.value = true
  actionError.value = ''
  try {
    await api.post(path, body)
    modal.value = ''
    show(message)
    await load()
  } catch (e) {
    actionError.value = errorText(e)
    if (e instanceof ApiError && e.code === 'unsubmitted_units') actionError.value = ''
  } finally {
    busy.value = false
  }
}
function open(kind: typeof modal.value): void {
  actionError.value = ''
  modal.value = kind
}
async function submitRolling(u: RollingUnit): Promise<void> {
  if (!data.value?.my_rolling) return
  try {
    await api.post(`/api/versions/rolling/${data.value.my_rolling.id}/units/${encodeURIComponent(u.key)}/submit`)
    show(`已提交 ${u.name} 的本季度更新`)
    await load()
  } catch (e) {
    show(errorText(e))
  }
}
</script>

<template>
  <div data-page-id="PAGE-F08-01" class="g3">
    <div class="page-head"><h1 class="page-title">预算版本</h1></div>

    <PageState v-if="loading" state="loading" />
    <PageState v-else-if="error" :error="error" @retry="load" />
    <template v-else-if="data">
      <div v-if="!data.versions.length && !data.my_adjustment_units.length" class="card state">
        <div class="state-title">{{ data.year }} 年度还没有预算版本</div>
        <p>CEO 审批通过全公司预算后，系统会自动生成「年初原始目标」版本并显示在这里。</p>
        <RouterLink class="btn" :to="{ name: 'tasks' }">查看编制任务</RouterLink>
      </div>

      <template v-else>
        <!-- 财务负责人：工具行与本季度卡片 -->
        <div class="row section">
          <label class="small muted" for="f-year">预算年度</label>
          <select id="f-year" v-model.number="year" class="select" @change="load">
            <option v-for="y in data.years" :key="y" :value="y">{{ y }}</option>
          </select>
          <span class="small muted">{{ todayText }}</span>
          <span class="spacer"></span>
          <div v-if="data.is_finance_head" class="row" style="gap: var(--space-2)">
            <span v-if="adjustBlock" class="block-note" data-testid="adj-block">{{ adjustBlock }}</span>
            <button class="btn btn-primary" type="button" :disabled="!data.actions.adjust.enabled" @click="open('adj')">发起季度调整</button>
            <button class="btn" type="button" :disabled="!data.actions.rolling.enabled" :title="rollBlock || undefined" @click="open('roll')">发起滚动更新</button>
            <button v-if="data.actions.publish_original.visible" class="btn" type="button" @click="open('q1')">以年初原始目标发布</button>
          </div>
        </div>

        <section v-if="data.is_finance_head && data.quarter" class="section" aria-labelledby="h-q">
          <h2 id="h-q" class="section-title">本季度进行中</h2>
          <div class="grid-2">
            <div class="card q-card">
              <template v-if="data.adjustment">
                <div class="row">
                  <h3>{{ data.adjustment.year }} Q{{ data.adjustment.quarter }} 目标调整</h3>
                  <span class="badge" :class="data.adjustment.status === 'effective' ? 'badge-good' : 'badge-warn'">
                    {{ data.adjustment.status === 'effective' ? `已生效 ${data.adjustment.result_version}` : data.adjustment.status === 'pending_ceo' ? '待CEO终审' : '审批中' }}
                  </span>
                </div>
                <dl class="kv">
                  <dt>发起</dt><dd class="num">{{ data.adjustment.initiated_by_name }} · {{ data.adjustment.initiated_at?.slice(0, 10) }}</dd>
                  <dt>可调整月份</dt><dd>{{ monthsText(data.adjustment.adjustable_months) }}</dd>
                  <dt>进度</dt>
                  <dd class="num">{{ data.adjustment.progress.total }} 个单位中已提交 {{ data.adjustment.progress.submitted }} 个；部门负责人已通过 {{ data.adjustment.progress.dept_approved }} 个；财务负责人已通过 {{ data.adjustment.progress.finance_approved }} 个</dd>
                  <template v-if="data.adjustment.ceo_return_reason && data.adjustment.status === 'in_progress'">
                    <dt>CEO 退回</dt><dd>{{ data.adjustment.ceo_return_reason }}</dd>
                  </template>
                  <dt>下一步</dt>
                  <dd>{{ data.adjustment.status === 'effective' ? `已生成调整后目标 ${data.adjustment.result_version}` : '全部单位经财务负责人通过后，CEO 对整次调整一次性终审' }}</dd>
                </dl>
                <RouterLink v-if="data.adjustment.status !== 'effective'" class="link" :to="{ name: 'approvals' }">去待我审批处理</RouterLink>
              </template>
              <template v-else>
                <h3>{{ quarterLabel }} 目标调整</h3>
                <p class="muted small">本季度尚未发起目标调整。</p>
              </template>
            </div>
            <div class="card q-card">
              <template v-if="data.rolling">
                <div class="row">
                  <h3>{{ data.year }} Q{{ data.rolling.quarter }} 滚动预测</h3>
                  <span class="badge" :class="data.rolling.type === 'snapshot' ? 'badge-good' : ''">{{ data.rolling.status_label }}</span>
                </div>
                <dl class="kv">
                  <dt>{{ data.rolling.type === 'snapshot' ? '发布' : '发起' }}</dt>
                  <dd class="num">{{ data.rolling.initiated_by_name ?? '—' }} · {{ data.rolling.published_on ?? data.rolling.initiated_at?.slice(0, 10) }}</dd>
                  <dt>开放月份</dt><dd>{{ data.rolling.open_months_text }}</dd>
                  <template v-if="data.rolling.type !== 'snapshot'">
                    <dt>提交进度</dt><dd class="num">{{ data.rolling.progress.total }} 个填报单位中已提交 {{ data.rolling.progress.submitted }} 个</dd>
                  </template>
                  <dt>快照口径</dt><dd>{{ data.rolling.basis || '已导入实际月份用实际数，其余月份用最新提交的驱动计算值' }}</dd>
                </dl>
                <button v-if="data.rolling.type !== 'snapshot'" class="btn" type="button" @click="open('pub')">发布快照</button>
              </template>
              <template v-else>
                <h3>{{ quarterLabel }} 滚动预测</h3>
                <p class="muted small">
                  {{ data.actions.publish_original.visible ? '第一季度可直接「以年初原始目标发布」快照，不需要各填报人重新提交；也可发起滚动更新。' : '本季度尚未发起滚动预测更新。' }}
                </p>
              </template>
            </div>
          </div>
        </section>

        <!-- 填报人：我的目标调整 -->
        <section v-if="data.my_adjustment_units.length" class="section" aria-labelledby="h-my">
          <h2 id="h-my" class="section-title">我的目标调整</h2>
          <div class="notice">目标调整在各填报表格中以「调整模式」编辑：已导入金蝶实际的月份锁定，只能修改尚未导入实际的月份；提交时须填写调整原因。每个单位依次经部门负责人、财务负责人审核，全部通过后由 CEO 对整次调整一次性终审。</div>
          <div class="table-wrap" style="margin-top: var(--space-3)">
            <table class="table">
              <thead><tr><th>填报单位</th><th>状态</th><th>提交时间</th><th>当前环节</th><th>操作</th></tr></thead>
              <tbody>
                <tr v-for="u in data.my_adjustment_units" :key="u.id">
                  <td>{{ u.name }}</td>
                  <td><span class="badge" :class="unitBadge(u)">{{ u.status_label }}</span></td>
                  <td class="num">{{ u.submitted_at ?? '—' }}</td>
                  <td class="w-n">{{ u.step }}<span v-if="u.return_reason" class="small muted">（退回原因：{{ u.return_reason }}）</span></td>
                  <td><RouterLink class="link" :to="unitLink(u)">{{ unitAction(u) }}</RouterLink></td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>

        <section v-if="data.my_rolling" class="section">
          <h2 class="section-title">{{ data.year }} Q{{ data.my_rolling.quarter }} 滚动预测更新</h2>
          <div class="notice">财务负责人已发起本季度滚动更新，开放 {{ data.my_rolling.open_months_text }} 驱动{{ data.my_rolling.actual_through ? `；${data.my_rolling.actual_through} 及以前已导入金蝶实际，快照中按实际数计` : '' }}。请在填报表格中更新后提交。</div>
          <div class="table-wrap" style="margin-top: var(--space-3)">
            <table class="table">
              <thead><tr><th>填报单位</th><th>类型</th><th>状态</th><th>提交时间</th><th>操作</th></tr></thead>
              <tbody>
                <tr v-for="u in data.my_rolling.units" :key="u.key">
                  <td>{{ u.name }}</td><td>{{ u.unit_type_label }}</td>
                  <td><span class="badge" :class="u.submitted ? 'badge-good' : ''">{{ u.submitted ? '已提交' : '填报中' }}</span></td>
                  <td class="num">{{ u.submitted_at ?? '—' }}</td>
                  <td><button v-if="!u.submitted" class="btn" type="button" @click="submitRolling(u)">提交本季度更新</button><span v-else class="muted small">—</span></td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>

        <section class="section" aria-labelledby="h-v">
          <div class="row" style="margin-bottom: var(--space-3)">
            <h2 id="h-v" class="section-title" style="margin: 0">版本列表</h2>
            <span class="small muted">版本只增不改；年初原始目标与快照不可修改</span>
            <span class="spacer"></span>
            <span class="small muted">{{ selected.length === 2 ? '已选 2 个版本' : '勾选两个版本后对比' }}</span>
            <button class="btn" type="button" :disabled="selected.length !== 2" @click="compare">对比所选</button>
          </div>
          <div class="table-wrap">
            <table class="table">
              <thead><tr><th style="width: 36px"><span class="sr-only">选择</span></th><th>版本</th><th>类型</th><th>所属季度</th><th>状态</th><th>审批 / 发布</th><th>时间</th><th>调整原因 / 发布方式</th></tr></thead>
              <tbody>
                <tr v-for="v in data.versions" :key="v.id">
                  <td><input type="checkbox" :aria-label="`选择 ${v.label}`" :checked="selected.includes(v.id)"
                    :disabled="!selected.includes(v.id) && selected.length >= 2" @change="toggle(v.id, ($event.target as HTMLInputElement).checked)"></td>
                  <td><strong>{{ v.label }}</strong></td>
                  <td>{{ v.type_label }}</td>
                  <td>{{ v.quarter_label }}</td>
                  <td><span class="badge" :class="v.current ? 'badge-good' : ''">{{ v.status_label }}</span></td>
                  <td>{{ v.approver }}</td>
                  <td class="num">{{ v.time ?? '—' }}</td>
                  <td class="wrap">{{ v.reason || '—' }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>
      </template>
    </template>

    <G3Modal :open="modal === 'adj'" title="发起季度目标调整" @close="modal = ''">
      <dl class="kv">
        <dt>所属季度</dt><dd>{{ quarterLabel }}</dd>
        <dt>可调整月份</dt><dd>{{ adjustMonthsText }}</dd>
        <dt>开放单位</dt><dd>全部填报单位（每个启用店铺、B 端各负责部门、成本比例、物流比例、各部门部门费用），钉钉工作通知各填报人</dd>
        <dt>审批顺序</dt><dd>每个单位：部门负责人 → 财务负责人逐个审核；全部通过后 CEO 对整次调整一次性终审</dd>
      </dl>
      <p class="small muted">每个自然季度最多一次经 CEO 审批通过的目标调整；调整审批结束前不能再发起。填报人在各自填报表格中以「调整模式」修改，提交时须填写调整原因；审批通过后生成新的「调整后目标」版本，年初原始目标和此前版本保持不变。</p>
      <p v-if="actionError" class="field-error" role="alert">{{ actionError }}</p>
      <template #actions>
        <button class="btn" type="button" @click="modal = ''">取消</button>
        <button class="btn btn-primary" type="button" :disabled="busy" @click="run('/api/versions/adjustments', undefined, '已发起目标调整，已通知各填报人')">确认发起</button>
      </template>
    </G3Modal>

    <G3Modal :open="modal === 'roll'" title="发起滚动预测更新" @close="modal = ''">
      <dl class="kv">
        <dt>所属季度</dt><dd>{{ quarterLabel }}</dd>
        <dt>开放月份</dt><dd>{{ rollMonthsText }}</dd>
        <dt>通知对象</dt><dd>运营、B端业务、物流物控、财务BP（钉钉工作通知）</dd>
      </dl>
      <p class="small muted">已导入金蝶实际的月份在快照中直接使用实际数；其余月份使用最新提交的驱动计算值。</p>
      <p v-if="actionError" class="field-error" role="alert">{{ actionError }}</p>
      <template #actions>
        <button class="btn" type="button" @click="modal = ''">取消</button>
        <button class="btn btn-primary" type="button" :disabled="busy" @click="run('/api/versions/rolling', undefined, '已发起滚动预测更新，已通知相关填报人')">确认发起</button>
      </template>
    </G3Modal>

    <G3Modal :open="modal === 'q1'" :title="`以年初原始目标发布 ${data?.year} Q1 快照`" @close="modal = ''">
      <p>系统将直接用年初原始目标 V1 的月度数据生成「{{ data?.year }} Q1 滚动预测快照」，不需要各填报人重新提交。快照发布后不可修改，用于预测准确度计算。</p>
      <p v-if="actionError" class="field-error" role="alert">{{ actionError }}</p>
      <template #actions>
        <button class="btn" type="button" @click="modal = ''">取消</button>
        <button class="btn btn-primary" type="button" :disabled="busy" @click="run('/api/versions/rolling/publish-original', undefined, '已发布 Q1 快照')">确认发布</button>
      </template>
    </G3Modal>

    <G3Modal :open="modal === 'pub'" :title="`发布 ${data?.year} Q${data?.rolling?.quarter} 滚动预测快照`" @close="modal = ''">
      <p>{{ data?.actual_through ? `${data.actual_through} 及以前已导入金蝶实际的月份使用实际数；` : '' }}其余月份使用各填报人最新提交的驱动计算值。</p>
      <p v-if="data?.rolling?.unsubmitted.length" class="small muted">
        仍有 {{ data.rolling.unsubmitted.length }} 个填报单位未提交本季度更新：{{ data.rolling.unsubmitted.map((u) => `${u.name}（${u.filler_name ?? '—'}）`).join('、') }}。未提交者按其最近一次提交的驱动计算。
      </p>
      <p class="small muted">快照发布后不可修改，标注发布日期 {{ data?.today }} 和所属季度 {{ quarterLabel }}。</p>
      <p v-if="actionError" class="field-error" role="alert">{{ actionError }}</p>
      <template #actions>
        <button class="btn" type="button" @click="modal = ''">取消</button>
        <button class="btn btn-primary" type="button" :disabled="busy" @click="run(`/api/versions/rolling/${data?.rolling?.id}/publish`, { confirm_unsubmitted: true }, '已发布滚动预测快照')">确认发布</button>
      </template>
    </G3Modal>

    <div v-if="toast" class="toast" role="status">{{ toast }}</div>
  </div>
</template>

<style scoped>
.q-card h3 { font-size: var(--text-base); margin: 0 0 var(--space-2); }
.q-card .kv { grid-template-columns: 112px 1fr; margin-bottom: var(--space-3); }
</style>
