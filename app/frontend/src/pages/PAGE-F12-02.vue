<script setup lang="ts">
/**
 * PAGE-F12-02 规则详情：查看（生效 / 待审批 / 已退回卡片 + 版本历史）与新建 / 编辑表单（可信度必选）。
 * 路由 /rules/new 为新建；有待审批版本时禁止再提交（API-F12-01/02；AC-F12-01、02、04、06、07）。
 */
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '@/api/client'
import PageState from '@/components/PageState.vue'
import { errorText, fieldErrors, useToast } from '@/components/g3/useG3'
import { useUiStore } from '@/stores/ui'
import '@/components/g3/g3.css'

interface Content {
  kind: string; text?: string; summary: string; metric?: string; metric_label?: string; unit?: string; comparator?: string
  threshold?: string; consecutive_months?: number; applies_to?: { type: string; ids: number[] }; receivers?: string[]
  limits?: string[]
}
interface Version {
  id: number; version_no: number; status: string; status_label: string; content: Content; credibility: string
  credibility_label: string; basis: string | null; submitted_by_name: string; submitted_at: string | null
  approved_by_name: string | null; effective_at: string | null; returned: { reason: string; by: string; at: string | null } | null
}
interface RuleDetail {
  id: number; name: string; type: string; type_label: string; versions: Version[]; can_edit: boolean
  edit_block: string | null; resubmit: boolean; effective_version_no: number | null
}
interface Opt { value: string; label: string; unit?: string }
interface Options {
  types: Opt[]; credibility: Opt[]; metrics: Opt[]; comparators: Opt[]; applies: Opt[]; receivers: Opt[]
  channels: { id: number; name: string }[]; departments: { id: number; name: string }[]; categories: { id: number; name: string }[]
}

const route = useRoute()
const router = useRouter()
const ui = useUiStore()
const isNew = computed(() => route.params.id === 'new')
const rule = ref<RuleDetail | null>(null)
const options = ref<Options | null>(null)
const loading = ref(true)
const error = ref<unknown>(null)
const editing = ref(false)
const errors = ref<Record<string, string>>({})
const submitting = ref(false)
const { toast, show } = useToast()
const form = reactive({
  type: 'alert_rule', name: '', metric: '', comparator: '', threshold: '', consecutive_months: '1',
  applies: '', ids: [] as number[], receivers: ['dept_head', 'operations', 'finance_head'] as string[],
  content_text: '', credibility: '', basis: '',
})

const effective = computed(() => rule.value?.versions.find((v) => v.status === 'effective') ?? null)
const pending = computed(() => rule.value?.versions.find((v) => v.status === 'pending' || v.status === 'pending_ceo') ?? null)
const latestReturned = computed(() => (rule.value?.versions[0]?.status === 'returned' ? rule.value.versions[0] : null))
const unit = computed(() => options.value?.metrics.find((m) => m.value === form.metric)?.unit ?? '—')
const targetList = computed(() => {
  const o = options.value
  if (!o) return []
  return form.applies === 'channel' ? o.channels : form.applies === 'department' ? o.departments : form.applies === 'category' ? o.categories : []
})
const flowText = computed(() => form.type === 'quota_standard'
  ? '保存后状态为「待审批」，财务负责人审批通过后转「待CEO审批」，CEO 通过后生成新版本并生效，原生效版本转为历史版本。'
  : '保存后状态为「待审批」，由财务负责人审批；通过后生成新版本并生效，原生效版本转为历史版本。')

async function load(): Promise<void> {
  error.value = null
  try {
    options.value = await api.get<Options>('/api/rules/options')
    if (isNew.value) {
      rule.value = null
      editing.value = true
      ui.setCrumbTitle('新建规则')
    } else {
      rule.value = await api.get<RuleDetail>(`/api/rules/${route.params.id}`)
      ui.setCrumbTitle(rule.value.name)
      editing.value = false
    }
  } catch (e) {
    error.value = e
  } finally {
    loading.value = false
  }
}
onMounted(load)
watch(() => route.params.id, () => { loading.value = true; void load() })

function startEdit(): void {
  const r = rule.value
  if (!r) return
  const src = latestReturned.value ?? effective.value ?? r.versions[0]
  const c = src?.content
  Object.assign(form, {
    type: r.type, name: r.name, credibility: '', basis: src?.basis ?? '',
    content_text: c?.text ?? '', metric: c?.metric ?? '', comparator: c?.comparator ?? '', threshold: c?.threshold ?? '',
    consecutive_months: String(c?.consecutive_months ?? 1), applies: c?.applies_to?.type ?? '',
    ids: [...(c?.applies_to?.ids ?? [])], receivers: [...(c?.receivers ?? ['dept_head', 'operations', 'finance_head'])],
  })
  errors.value = {}
  editing.value = true
}

function validate(): Record<string, string> {
  const e: Record<string, string> = {}
  if (isNew.value && !form.name.trim()) e.name = '请填写规则名称'
  if (form.type === 'alert_rule') {
    if (!form.metric) e.metric = '请选择指标'
    if (!form.comparator) e.comparator = '请选择比较方式'
    if (!/^[-−]?\d+(\.\d+)?$/.test(form.threshold.trim())) e.threshold = '请填写阈值（数字）'
    if (!/^\d+$/.test(form.consecutive_months.trim()) || Number(form.consecutive_months) < 1) e.consecutive_months = '请填写不小于 1 的整数'
    if (!form.applies || (['channel', 'department', 'category'].includes(form.applies) && !form.ids.length)) e.applies_to = '请选择适用对象'
    if (!form.receivers.length) e.receivers = '请至少选择一个接收角色'
  } else if (!form.content_text.trim()) {
    e.content_text = '请填写规则内容'
  }
  if (!form.credibility) e.credibility = '请选择可信度状态'
  if (!form.basis.trim()) e.basis = '请填写依据'
  return e
}

async function submit(): Promise<void> {
  errors.value = validate()
  if (Object.keys(errors.value).length) {
    document.querySelector<HTMLElement>('[aria-invalid="true"], .field-error')?.scrollIntoView({ block: 'center' })
    return
  }
  const body: Record<string, unknown> = {
    type: form.type, name: form.name.trim(), credibility: form.credibility, basis: form.basis.trim(),
  }
  if (form.type === 'alert_rule') {
    body.alert = {
      metric: form.metric, comparator: form.comparator, threshold: form.threshold.trim().replace('−', '-'),
      consecutive_months: Number(form.consecutive_months),
      applies_to: { type: form.applies, ids: ['channel', 'department', 'category'].includes(form.applies) ? form.ids : [] },
      receivers: form.receivers,
    }
  } else {
    body.content_text = form.content_text.trim()
  }
  submitting.value = true
  try {
    const d = isNew.value
      ? await api.post<RuleDetail>('/api/rules', body)
      : await api.post<RuleDetail>(`/api/rules/${rule.value!.id}/versions`, body)
    show('已提交审批，状态为「待审批」')
    if (isNew.value) {
      await router.replace({ name: 'rule-detail', params: { id: String(d.id) } })
    } else {
      rule.value = d
      editing.value = false
    }
  } catch (e) {
    const f = fieldErrors(e)
    errors.value = Object.keys(f).length ? f : { _: errorText(e) }
  } finally {
    submitting.value = false
  }
}
function cancel(): void {
  if (isNew.value) router.push({ name: 'rules' })
  else editing.value = false
}
function credBadge(c: string): string {
  return c === 'unverified' ? 'badge-warn' : c === 'verified' ? 'badge-good' : ''
}
</script>

<template>
  <div data-page-id="PAGE-F12-02" class="g3">
    <div class="page-head"><h1 class="page-title">{{ isNew ? '新建规则' : '规则详情' }}</h1></div>
    <PageState v-if="loading" state="loading" />
    <PageState v-else-if="error" :error="error" @retry="load">
      <template v-if="(error as { status?: number }).status === 404" #action>
        <RouterLink class="btn" :to="{ name: 'rules' }">返回规则库</RouterLink>
      </template>
    </PageState>

    <template v-else>
      <!-- 查看 -->
      <div v-if="rule && !editing">
        <div class="card section">
          <div class="row" style="margin-bottom: var(--space-2)">
            <span class="badge">{{ rule.type_label }}</span>
            <span v-if="effective" class="badge badge-good">生效 v{{ effective.version_no }}</span>
            <span v-if="pending" class="badge badge-warn">{{ pending.status_label }} v{{ pending.version_no }}</span>
            <span v-if="latestReturned" class="badge badge-bad">已退回 v{{ latestReturned.version_no }}</span>
            <span class="spacer"></span>
            <span v-if="rule.edit_block" class="small muted">{{ rule.edit_block }}</span>
            <button v-if="rule.can_edit" class="btn" type="button" :disabled="!!rule.edit_block" @click="startEdit">
              {{ rule.resubmit ? '修改后重新提交' : '编辑并提交新版本' }}
            </button>
          </div>
          <h2 style="font-size: var(--text-xl); margin: 0 0 var(--space-2)">{{ rule.name }}</h2>
          <p class="small muted" style="margin: 0">
            {{ effective ? `预警评估只使用生效版本 v${effective.version_no}` : '尚无生效版本，审批通过前不参与评估' }}{{ pending ? `；待审批的 v${pending.version_no} 在审批通过前不参与评估` : '' }}。
          </p>
        </div>
        <div class="grid-2 section">
          <div v-for="v in [effective, pending ?? latestReturned].filter(Boolean) as Version[]" :key="v.id" class="card">
            <div class="row" style="margin-bottom: var(--space-2)">
              <h3 class="section-title" style="margin: 0">{{ v.status === 'effective' ? '生效版本' : v.status === 'returned' ? '已退回版本' : '待审批版本' }} v{{ v.version_no }}</h3>
              <span class="badge" :class="credBadge(v.credibility)">{{ v.credibility_label }}</span>
            </div>
            <dl class="kv">
              <dt>内容</dt><dd>{{ v.content.summary }}</dd>
              <dt>依据</dt><dd>{{ v.basis || '—' }}</dd>
              <dt>提交</dt><dd class="num">{{ v.submitted_by_name }} · {{ v.submitted_at }}</dd>
              <template v-if="v.status === 'effective'"><dt>生效</dt><dd class="num">{{ v.approved_by_name }} 审批 · {{ v.effective_at }}</dd></template>
              <template v-else-if="v.returned">
                <dt>退回</dt><dd class="num">{{ v.returned.by }} · {{ v.returned.at }}</dd>
                <dt>退回原因</dt><dd class="bad">{{ v.returned.reason }}</dd>
                <dt>状态</dt><dd>已退回，不生效{{ effective ? `；v${effective.version_no} 继续生效` : '' }}</dd>
              </template>
              <template v-else><dt>审批</dt><dd>待{{ v.status === 'pending_ceo' ? ' CEO ' : '财务负责人' }}审批</dd></template>
            </dl>
          </div>
          <div v-if="!effective && !pending && !latestReturned" class="card"><p class="muted small">暂无版本。</p></div>
        </div>
        <section aria-labelledby="h-his">
          <h3 id="h-his" class="section-title">版本历史</h3>
          <div class="table-wrap">
            <table class="table">
              <thead><tr><th>版本</th><th>状态</th><th>内容</th><th>可信度</th><th>依据</th><th>提交人</th><th>审批人</th><th>生效时间</th></tr></thead>
              <tbody>
                <tr v-for="v in rule.versions" :key="v.id">
                  <td>v{{ v.version_no }}</td>
                  <td><span class="badge" :class="{ 'badge-good': v.status === 'effective', 'badge-warn': v.status.startsWith('pending'), 'badge-bad': v.status === 'returned' }">{{ v.status_label }}</span></td>
                  <td class="wrap">{{ v.content.summary }}<div v-if="v.returned" class="small muted">退回原因：{{ v.returned.reason }}</div></td>
                  <td>{{ v.credibility_label }}</td>
                  <td class="wrap">{{ v.basis || '—' }}</td>
                  <td>{{ v.submitted_by_name }}</td>
                  <td>{{ v.approved_by_name || (v.returned?.by ?? '—') }}</td>
                  <td class="num">{{ v.effective_at ?? '—' }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>
      </div>

      <!-- 新建 / 编辑 -->
      <form v-else-if="editing && options" novalidate @submit.prevent="submit">
        <div class="card section">
          <h2 class="section-title">{{ isNew ? '新建规则' : `编辑并提交新版本 · ${rule?.name}` }}</h2>
          <fieldset v-if="isNew" class="field">
            <legend class="req">类型</legend>
            <div class="radio-row">
              <label v-for="t in options.types" :key="t.value"><input v-model="form.type" type="radio" name="type" :value="t.value"> {{ t.label }}</label>
            </div>
          </fieldset>
          <div v-if="isNew" class="field">
            <label class="req" for="f-name">规则名称</label>
            <input id="f-name" v-model="form.name" class="input" style="width: 100%; box-sizing: border-box" :aria-invalid="!!errors.name" placeholder="例如：品类毛利率比预算低 3 个百分点以上">
            <div v-if="errors.name" class="field-error">{{ errors.name }}</div>
          </div>
          <div v-if="form.type === 'alert_rule'">
            <div class="form-grid">
              <div class="field">
                <label class="req" for="f-metric">指标</label>
                <select id="f-metric" v-model="form.metric" class="select" :aria-invalid="!!errors.metric">
                  <option value="">请选择</option>
                  <option v-for="m in options.metrics" :key="m.value" :value="m.value">{{ m.label }}</option>
                </select>
                <div v-if="errors.metric" class="field-error">{{ errors.metric }}</div>
              </div>
              <div class="field">
                <label class="req" for="f-cmp">比较方式</label>
                <select id="f-cmp" v-model="form.comparator" class="select" :aria-invalid="!!errors.comparator">
                  <option value="">请选择</option>
                  <option v-for="c in options.comparators" :key="c.value" :value="c.value">{{ c.label }}</option>
                </select>
                <div v-if="errors.comparator" class="field-error">{{ errors.comparator }}</div>
              </div>
              <div class="field">
                <label class="req" for="f-th">阈值</label>
                <div class="unit-wrap"><input id="f-th" v-model="form.threshold" class="input num" inputmode="decimal" placeholder="例如 3" :aria-invalid="!!errors.threshold"><span class="small muted">{{ unit }}</span></div>
                <div v-if="errors.threshold" class="field-error">{{ errors.threshold }}</div>
              </div>
              <div class="field">
                <label class="req" for="f-months">连续月数</label>
                <div class="unit-wrap"><input id="f-months" v-model="form.consecutive_months" class="input num" inputmode="numeric" :aria-invalid="!!errors.consecutive_months"><span class="small muted">个月</span></div>
                <div v-if="errors.consecutive_months" class="field-error">{{ errors.consecutive_months }}</div>
              </div>
              <div class="field">
                <label class="req" for="f-obj">适用对象</label>
                <select id="f-obj" v-model="form.applies" class="select" :aria-invalid="!!errors.applies_to" @change="form.ids = []">
                  <option value="">请选择</option>
                  <option v-for="a in options.applies" :key="a.value" :value="a.value">{{ a.label }}</option>
                </select>
                <div v-if="targetList.length" class="radio-row" style="margin-top: var(--space-2)">
                  <label v-for="t in targetList" :key="t.id"><input v-model="form.ids" type="checkbox" :value="t.id"> {{ t.name }}</label>
                </div>
                <div v-if="errors.applies_to" class="field-error">{{ errors.applies_to }}</div>
              </div>
            </div>
            <fieldset class="field">
              <legend class="req">接收角色</legend>
              <div class="radio-row">
                <label v-for="r in options.receivers" :key="r.value"><input v-model="form.receivers" type="checkbox" :value="r.value"> {{ r.label }}{{ r.value === 'ceo' ? '（部门费用超额度时）' : '' }}</label>
              </div>
              <div v-if="errors.receivers" class="field-error">{{ errors.receivers }}</div>
            </fieldset>
          </div>
          <div v-else class="field">
            <label class="req" for="f-content">规则内容</label>
            <textarea id="f-content" v-model="form.content_text" class="input" :aria-invalid="!!errors.content_text" placeholder="例如：Amazon 美国站 11 月单 SPU 平均销量按 10 月的 1.6 倍填报"></textarea>
            <div v-if="errors.content_text" class="field-error">{{ errors.content_text }}</div>
          </div>
          <fieldset class="field">
            <legend class="req">可信度状态</legend>
            <div class="radio-row">
              <label v-for="c in options.credibility" :key="c.value"><input v-model="form.credibility" type="radio" name="cred" :value="c.value"> {{ c.label }}</label>
            </div>
            <div v-if="errors.credibility" class="field-error">{{ errors.credibility }}</div>
          </fieldset>
          <div class="field">
            <label class="req" for="f-basis">依据</label>
            <textarea id="f-basis" v-model="form.basis" class="input" :aria-invalid="!!errors.basis" placeholder="写明数据来源与观察结论"></textarea>
            <div v-if="errors.basis" class="field-error">{{ errors.basis }}</div>
          </div>
          <div class="notice">{{ flowText }}</div>
          <p v-if="errors._" class="field-error" role="alert">{{ errors._ }}</p>
        </div>
        <div class="row">
          <span class="spacer"></span>
          <button class="btn" type="button" @click="cancel">取消</button>
          <button class="btn btn-primary" type="submit" :disabled="submitting">提交审批</button>
        </div>
      </form>
    </template>
    <div v-if="toast" class="toast" role="status">{{ toast }}</div>
  </div>
</template>

<style scoped>
.radio-row { display: flex; gap: var(--space-4); flex-wrap: wrap; font-size: var(--text-sm); }
.radio-row label { display: inline-flex; align-items: center; gap: var(--space-1); cursor: pointer; }
.form-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 0 var(--space-4); }
.form-grid .input, .form-grid .select { width: 100%; box-sizing: border-box; }
.unit-wrap { display: flex; align-items: center; gap: var(--space-2); }
.unit-wrap .input { width: 120px; }
fieldset.field { border: 0; padding: 0; margin: 0 0 var(--space-4); min-width: 0; }
fieldset.field legend { font-size: var(--text-sm); color: var(--fg-2); margin-bottom: var(--space-1); padding: 0; }
</style>
