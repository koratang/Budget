<script setup lang="ts">
/** PAGE-F05-02 专项预留额度：新增专项（AC-F05-03）、上年同科目实际（AC-F05-04）、财务BP 登记使用（AC-F05-05） */
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '@/api/client'
import PageState from '@/components/PageState.vue'
import G2Modal from '@/components/g2/G2Modal.vue'
import { errorText, isForbidden, toast, type UnitInfo } from '@/components/g2/util'
import '@/components/g2/g2.css'

interface Usage {
  id: number
  amount_display: string
  used_on: string
  voucher_no: string
}
interface ReserveRow {
  id: number
  name: string
  account: string
  plan_month: string
  amount_display: string
  used_display: string
  remaining: string
  remaining_display: string
  prior_year_actual_display: string
  usages: Usage[]
}
interface ReserveList {
  department: { id: number; name: string }
  unit: UnitInfo | null
  year?: number
  reserves: ReserveRow[]
  accounts: { id: number; name: string; prior_year_actual_display: string }[]
  departments: { id: number; name: string }[]
  prior_label: string | null
  prior_range: string | null
  can_create: boolean
  can_register: boolean
  totals: { amount_display: string; used_display: string; remaining: string; remaining_display: string } | null
}

const route = useRoute()
const router = useRouter()
const data = ref<ReserveList | null>(null)
const loading = ref(true)
const error = ref<unknown>(null)
const expanded = ref<number | null>(null)
const deptId = computed(() => (route.query.departmentId ? Number(route.query.departmentId) : undefined))

async function load(): Promise<void> {
  loading.value = data.value === null
  error.value = null
  try {
    data.value = await api.get<ReserveList>('/api/reserves', { department_id: deptId.value })
  } catch (e) {
    error.value = e
  } finally {
    loading.value = false
  }
}
onMounted(load)
watch(deptId, load)

function switchDept(ev: Event): void {
  void router.replace({ name: 'reserves', query: { departmentId: (ev.target as HTMLSelectElement).value } })
}

const isNeg = (v: string) => v.trim().startsWith('-')

// ---- 新增专项 ----
const createOpen = ref(false)
const form = reactive({ name: '', account_id: '', plan_month: '', amount: '' })
const formErr = reactive<Record<string, string>>({})
const months = computed(() => {
  const y = data.value?.year ?? new Date().getFullYear() + 1
  return Array.from({ length: 12 }, (_, i) => `${y}-${String(i + 1).padStart(2, '0')}`)
})
const accountRef = computed(() => {
  const a = data.value?.accounts.find((x) => String(x.id) === form.account_id)
  if (!a) return ''
  return `参考：${a.name} ${data.value?.prior_range ? `${data.value.prior_range} ` : ''}实际 ${a.prior_year_actual_display}`
})
function openCreate(): void {
  Object.assign(form, { name: '', account_id: '', plan_month: '', amount: '' })
  for (const k of Object.keys(formErr)) delete formErr[k]
  createOpen.value = true
}
async function doCreate(): Promise<void> {
  for (const k of Object.keys(formErr)) delete formErr[k]
  if (!form.name.trim()) formErr.name = '请填写专项名称'
  if (!form.account_id) formErr.account_id = '请选择所属预算科目'
  if (!form.plan_month) formErr.plan_month = '请选择计划月份'
  if (!form.amount.trim()) formErr.amount = '请填写预留金额'
  if (Object.keys(formErr).length || !data.value) return
  try {
    const res = await api.post<{ message: string }>('/api/reserves', {
      department_id: data.value.department.id,
      name: form.name.trim(),
      account_id: Number(form.account_id),
      plan_month: form.plan_month,
      amount: form.amount.trim(),
    })
    createOpen.value = false
    toast(res.message)
    await load()
  } catch (e) {
    formErr.submit = errorText(e)
  }
}

// ---- 登记使用 ----
const usageFor = ref<ReserveRow | null>(null)
const usage = reactive({ amount: '', used_on: '', voucher_no: '' })
const usageErr = ref('')
function openUsage(r: ReserveRow): void {
  usageFor.value = r
  Object.assign(usage, { amount: '', used_on: '', voucher_no: '' })
  usageErr.value = ''
}
async function doUsage(): Promise<void> {
  if (!usageFor.value) return
  if (!usage.amount.trim()) return void (usageErr.value = '请填写使用金额')
  if (!usage.used_on) return void (usageErr.value = '请选择使用日期')
  if (!usage.voucher_no.trim()) return void (usageErr.value = '请填写金蝶凭证号')
  try {
    const res = await api.post<{ message: string }>(`/api/reserves/${usageFor.value.id}/usages`, { ...usage })
    usageFor.value = null
    toast(res.message)
    await load()
  } catch (e) {
    usageErr.value = errorText(e)
  }
}
</script>

<template>
  <div data-page-id="PAGE-F05-02" class="g2">
    <PageState v-if="loading" state="loading" />
    <PageState
      v-else-if="error"
      :error="error"
      :title="isForbidden(error) ? undefined : '专项预留额度加载失败'"
      :description="isForbidden(error) ? '你只能查看被分配部门的专项预留额度。如需开通，请联系财务负责人。' : undefined"
      @retry="load"
    />
    <template v-else-if="data">
      <div class="page-head">
        <div>
          <h1 class="page-title">专项预留额度 · {{ data.department.name }}</h1>
          <p class="sub">专项金额计入所属科目在计划月份的部门预算（见 <RouterLink v-if="data.unit" class="link" :to="{ name: 'dept-expense', query: { unitId: String(data.unit.id) } }">部门费用填报</RouterLink>）。剩余金额 = 预留金额 − 已用金额；已用金额由财务BP 按金蝶凭证登记。</p>
        </div>
        <div class="toolbar">
          <label v-if="data.departments.length > 1" class="sub" style="margin: 0">
            部门
            <select class="select" :value="String(data.department.id)" @change="switchDept">
              <option v-for="d in data.departments" :key="d.id" :value="String(d.id)">{{ d.name }}</option>
            </select>
          </label>
          <button v-if="data.can_create" class="btn btn-primary" type="button" data-new-reserve @click="openCreate">新增专项</button>
        </div>
      </div>

      <div v-if="data.unit && data.unit.locked" class="notice notice-info" role="status">
        {{ data.department.name }} {{ data.year }} 年度费用预算已提交，内容已锁定，被退回之前不能新增专项。
      </div>

      <div v-if="data.totals" class="kpis k3">
        <div class="card fade-in"><div class="kpi-label">预留金额合计</div><div class="kpi-value sm tnum">¥ {{ data.totals.amount_display }}</div></div>
        <div class="card fade-in"><div class="kpi-label">已用金额合计</div><div class="kpi-value sm tnum">¥ {{ data.totals.used_display }}</div></div>
        <div class="card fade-in">
          <div class="kpi-label">剩余金额合计</div>
          <div class="kpi-value sm tnum" :class="{ bad: isNeg(data.totals.remaining) }">¥ {{ data.totals.remaining_display }}</div>
        </div>
      </div>

      <PageState
        v-if="!data.reserves.length"
        state="empty"
        title="还没有专项预留额度"
        description="培训、年会、团建等临时活动可以提前预留额度，金额会计入所属科目当月预算。"
      >
        <template #action>
          <button v-if="data.can_create" class="btn btn-primary" type="button" @click="openCreate">新增专项</button>
        </template>
      </PageState>
      <div v-else class="table-wrap">
        <table class="table" aria-label="专项预留额度">
          <thead>
            <tr>
              <th>专项名称</th><th>所属预算科目</th><th class="num">计划月份</th><th class="num">预留金额</th><th class="num">已用金额</th>
              <th class="num">剩余金额</th><th class="num">{{ data.prior_label }}</th><th>操作</th>
            </tr>
          </thead>
          <tbody>
            <template v-for="r in data.reserves" :key="r.id">
              <tr :data-reserve="r.name">
                <td>{{ r.name }}</td>
                <td>{{ r.account }}</td>
                <td class="num">{{ r.plan_month }}</td>
                <td class="num">{{ r.amount_display }}</td>
                <td class="num">{{ r.used_display }}</td>
                <td class="num" :class="{ neg: isNeg(r.remaining) }">{{ r.remaining_display }}</td>
                <td class="num">{{ r.prior_year_actual_display }}</td>
                <td>
                  <template v-if="data.can_register">
                    <button class="btn" type="button" @click="openUsage(r)">登记使用</button>
                    <button class="link" type="button" style="margin-left: var(--space-2)" @click="expanded = expanded === r.id ? null : r.id">明细（{{ r.usages.length }}）</button>
                  </template>
                  <span v-else class="muted">—</span>
                </td>
              </tr>
              <tr v-if="expanded === r.id">
                <td colspan="8">
                  <span v-if="!r.usages.length" class="muted">暂无使用登记</span>
                  <span v-for="u in r.usages" :key="u.id" style="margin-right: var(--space-6)">{{ u.used_on }} · {{ u.amount_display }} · {{ u.voucher_no }}</span>
                </td>
              </tr>
            </template>
          </tbody>
        </table>
      </div>
    </template>

    <G2Modal v-if="createOpen" title="新增专项" @close="createOpen = false">
      <div class="field">
        <label for="r-name">专项名称<span class="req">*</span></label>
        <input id="r-name" v-model="form.name" class="input" placeholder="例如：管理层领导力训练营" />
        <div v-if="formErr.name" class="field-error">{{ formErr.name }}</div>
      </div>
      <div class="field">
        <label for="r-acc">所属预算科目<span class="req">*</span></label>
        <select id="r-acc" v-model="form.account_id" class="select">
          <option value="">请选择</option>
          <option v-for="a in data?.accounts ?? []" :key="a.id" :value="String(a.id)">{{ a.name }}</option>
        </select>
        <div v-if="accountRef" class="sub">{{ accountRef }}</div>
        <div v-if="formErr.account_id" class="field-error">{{ formErr.account_id }}</div>
      </div>
      <div class="field">
        <label for="r-month">计划月份<span class="req">*</span></label>
        <select id="r-month" v-model="form.plan_month" class="select">
          <option value="">请选择</option>
          <option v-for="m in months" :key="m" :value="m">{{ m }}</option>
        </select>
        <div v-if="formErr.plan_month" class="field-error">{{ formErr.plan_month }}</div>
      </div>
      <div class="field">
        <label for="r-amount">预留金额（人民币）<span class="req">*</span></label>
        <input id="r-amount" v-model="form.amount" class="input" inputmode="decimal" placeholder="例如 180000.00" />
        <div v-if="formErr.amount" class="field-error">{{ formErr.amount }}</div>
      </div>
      <div v-if="formErr.submit" class="field-error" role="alert">{{ formErr.submit }}</div>
      <template #actions>
        <button class="btn" type="button" @click="createOpen = false">取消</button>
        <button class="btn btn-primary" type="button" data-save-reserve @click="doCreate">保存并计入预算</button>
      </template>
    </G2Modal>

    <G2Modal v-if="usageFor" :title="`登记使用 · ${usageFor.name}`" @close="usageFor = null">
      <p class="sub">预留 {{ usageFor.amount_display }} · 已用 {{ usageFor.used_display }} · 剩余 {{ usageFor.remaining_display }}</p>
      <div class="field">
        <label for="u-amount">使用金额（人民币）<span class="req">*</span></label>
        <input id="u-amount" v-model="usage.amount" class="input" inputmode="decimal" />
      </div>
      <div class="field">
        <label for="u-date">使用日期<span class="req">*</span></label>
        <input id="u-date" v-model="usage.used_on" class="input" type="date" />
      </div>
      <div class="field">
        <label for="u-voucher">金蝶凭证号<span class="req">*</span></label>
        <input id="u-voucher" v-model="usage.voucher_no" class="input" placeholder="例如：记-2027-04-0233" />
      </div>
      <div v-if="usageErr" class="field-error" role="alert">{{ usageErr }}</div>
      <template #actions>
        <button class="btn" type="button" @click="usageFor = null">取消</button>
        <button class="btn btn-primary" type="button" @click="doUsage">登记</button>
      </template>
    </G2Modal>
  </div>
</template>
