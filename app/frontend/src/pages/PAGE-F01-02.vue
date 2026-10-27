<script setup lang="ts">
/**
 * PAGE-F01-02 角色与权限（列表 + 分配抽屉）：仅财务负责人（AC-F01-05）。
 * 接口：GET /api/admin/users、GET /api/admin/scope-options、PUT /api/admin/users/{id}/roles（API-F01-07）。
 */
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { api, ApiError } from '@/api/client'
import { ROLE_NAMES, type RoleCode } from '@/api/types'
import PageState from '@/components/PageState.vue'
import G1Drawer from '@/components/g1/G1Drawer.vue'
import G1Modal from '@/components/g1/G1Modal.vue'
import { useToast } from '@/components/g1/useToast'
import '@/components/g1/g1.css'

interface Scopes { departments: number[]; channels: number[]; stores: number[]; customers: number[] }
interface Employee {
  id: number
  name: string
  dingtalk_dept: string | null
  is_active: boolean
  roles: RoleCode[]
  role_names: string[]
  scopes: Scopes
}
interface UserPage {
  items: Employee[]
  total: number
  page: number
  page_size: number
  summary: { employees: number; assigned: number; unassigned: number }
  dingtalk_depts: string[]
}
interface Option { id: number; name: string; is_active: boolean }
interface ScopeOptions {
  roles: { code: RoleCode; name: string }[]
  departments: Option[]
  channels: { id: number; name: string; stores: Option[] }[]
  customers: (Option & { department_name: string; currency: string })[]
}

const ALL_COMPANY: RoleCode[] = ['ceo', 'finance_head', 'finance_bp']
const LAST_FIN = '系统至少保留一位财务负责人：请先为其他员工分配「财务负责人」，再撤销此人的财务负责人角色'

const loading = ref(true)
const error = ref<unknown>(null)
const data = ref<UserPage | null>(null)
const options = ref<ScopeOptions | null>(null)
const filters = reactive({ q: '', dept: '', role: '', unassigned: false, page: 1 })
const { toast, show } = useToast()

async function load(): Promise<void> {
  error.value = null
  try {
    const [page, opts] = await Promise.all([
      api.get<UserPage>('/api/admin/users', {
        q: filters.q.trim(), dept: filters.dept, role: filters.role,
        unassigned: filters.unassigned || undefined, page: filters.page,
      }),
      options.value ? Promise.resolve(options.value) : api.get<ScopeOptions>('/api/admin/scope-options'),
    ])
    data.value = page
    options.value = opts
  } catch (e) {
    error.value = e
  } finally {
    loading.value = false
  }
}

let qTimer: ReturnType<typeof setTimeout> | null = null
watch(() => [filters.dept, filters.role, filters.unassigned], () => { filters.page = 1; void load() })
watch(() => filters.q, () => {
  if (qTimer) clearTimeout(qTimer)
  qTimer = setTimeout(() => { filters.page = 1; void load() }, 250)
})
onMounted(load)

const pages = computed(() => (data.value ? Math.max(1, Math.ceil(data.value.total / data.value.page_size)) : 1))
function goPage(p: number): void {
  filters.page = p
  void load()
}

const deptName = computed(() => new Map((options.value?.departments ?? []).map((d) => [d.id, d.name])))
const custName = computed(() => new Map((options.value?.customers ?? []).map((c) => [c.id, c.name])))

function scopeText(e: Employee): string {
  if (!e.roles.length) return '—'
  const parts: string[] = []
  if (e.roles.some((r) => ALL_COMPANY.includes(r))) parts.push('全公司')
  if (e.scopes.departments.length) parts.push('部门：' + e.scopes.departments.map((id) => deptName.value.get(id)).join('、'))
  const shops: string[] = []
  for (const ch of options.value?.channels ?? []) {
    if (e.scopes.channels.includes(ch.id)) {
      shops.push(`${ch.name}（全部 ${ch.stores.length} 个店铺）`)
      continue
    }
    const own = ch.stores.filter((s) => e.scopes.stores.includes(s.id))
    if (own.length === ch.stores.length && own.length > 1) shops.push(`${ch.name}（全部 ${own.length} 个店铺）`)
    else shops.push(...own.map((s) => s.name))
  }
  if (shops.length) parts.push('店铺：' + shops.join('、'))
  if (e.scopes.customers.length) parts.push('客户：' + e.scopes.customers.map((id) => custName.value.get(id)).join('、'))
  if (e.roles.includes('logistics')) parts.push('物流比例四项')
  return parts.join('；')
}

// ---- 分配抽屉 ----
const current = ref<Employee | null>(null)
const form = reactive({
  roles: [] as RoleCode[],
  departments: [] as number[],
  channels: [] as number[],
  stores: [] as number[],
  customers: [] as number[],
})
const errs = reactive({ roles: '', dept: false, shop: false, cust: false })
const saving = ref(false)
const confirmRevoke = ref(false)

const showAll = computed(() => form.roles.some((r) => ALL_COMPANY.includes(r)))
const showDept = computed(() => form.roles.includes('dept_head') || form.roles.includes('dept_budget'))
const showShop = computed(() => form.roles.includes('operations'))
const showCust = computed(() => form.roles.includes('b2b'))
const showLogi = computed(() => form.roles.includes('logistics'))

function clearErrs(): void {
  errs.roles = ''
  errs.dept = errs.shop = errs.cust = false
}

function openDrawer(e: Employee): void {
  current.value = e
  form.roles = [...e.roles]
  form.departments = [...e.scopes.departments]
  form.channels = [...e.scopes.channels]
  form.stores = [...e.scopes.stores]
  form.customers = [...e.scopes.customers]
  clearErrs()
}

function closeDrawer(): void {
  current.value = null
  confirmRevoke.value = false
}

function storeChecked(chId: number, storeId: number): boolean {
  return form.channels.includes(chId) || form.stores.includes(storeId)
}

function toggleChannel(ch: ScopeOptions['channels'][number], checked: boolean): void {
  const ids = ch.stores.map((s) => s.id)
  form.stores = form.stores.filter((id) => !ids.includes(id))
  form.channels = checked ? [...form.channels, ch.id] : form.channels.filter((id) => id !== ch.id)
}

function toggleStore(ch: ScopeOptions['channels'][number], storeId: number, checked: boolean): void {
  if (form.channels.includes(ch.id)) {
    // 取消整渠道中的一个店铺：改为逐个店铺
    form.channels = form.channels.filter((id) => id !== ch.id)
    form.stores = [...form.stores, ...ch.stores.map((s) => s.id).filter((id) => id !== storeId)]
    return
  }
  form.stores = checked ? [...form.stores, storeId] : form.stores.filter((id) => id !== storeId)
  if (ch.stores.length > 1 && ch.stores.every((s) => form.stores.includes(s.id))) toggleChannel(ch, true)
}

async function submit(roles: RoleCode[]): Promise<boolean> {
  if (!current.value) return false
  saving.value = true
  try {
    await api.put(`/api/admin/users/${current.value.id}/roles`, {
      roles,
      departments: showDept.value ? form.departments : [],
      channels: showShop.value ? form.channels : [],
      stores: showShop.value ? form.stores : [],
      customers: showCust.value ? form.customers : [],
    })
    return true
  } catch (e) {
    if (e instanceof ApiError && e.code === 'last_finance_head') errs.roles = LAST_FIN
    else errs.roles = e instanceof ApiError ? e.message : '保存失败，请重试'
    return false
  } finally {
    saving.value = false
  }
}

async function save(): Promise<void> {
  clearErrs()
  if (!form.roles.length) {
    errs.roles = '请至少选择一个角色；如需取消此人的全部权限，请点「撤销全部角色」'
    return
  }
  errs.dept = showDept.value && !form.departments.length
  errs.shop = showShop.value && !form.channels.length && !form.stores.length
  errs.cust = showCust.value && !form.customers.length
  if (errs.dept || errs.shop || errs.cust) return
  const name = current.value?.name
  if (await submit([...form.roles])) {
    closeDrawer()
    show(`已保存。${name} 下一次打开页面时按新角色和范围生效`)
    await load()
  }
}

async function revoke(): Promise<void> {
  const name = current.value?.name
  confirmRevoke.value = false
  if (await submit([])) {
    closeDrawer()
    show(`已撤销 ${name} 的全部角色`)
    await load()
  }
}

const roleOptions = computed(() => (Object.keys(ROLE_NAMES) as RoleCode[]).map((code) => ({ code, name: ROLE_NAMES[code] })))
</script>

<template>
  <div class="g1" data-page-id="PAGE-F01-02">
    <div class="page-head">
      <h1 class="page-title">角色与权限</h1>
      <span class="meta">员工来自钉钉通讯录 · 保存后对方下一次打开页面即按新范围生效</span>
    </div>

    <PageState v-if="loading" state="loading" :rows="5" />
    <PageState v-else-if="error && error instanceof ApiError && error.isForbidden" state="forbidden"
               description="角色分配仅财务负责人可用。" />
    <PageState v-else-if="error" state="error" title="员工列表加载失败"
               description="钉钉通讯录暂时无法读取，请稍后重试。" @retry="load" />
    <PageState v-else-if="data && data.summary.employees === 0" title="还没有读到钉钉通讯录员工"
               description="钉钉企业内部应用的通讯录权限开通后，这里会列出全部员工，供你分配预算角色。">
      <template #action><button type="button" class="btn" @click="load">重新同步通讯录</button></template>
    </PageState>

    <div v-else-if="data">
      <div class="filters" role="search">
        <input v-model="filters.q" class="input" type="search" placeholder="搜索姓名" aria-label="搜索姓名">
        <select v-model="filters.dept" class="select" aria-label="钉钉部门">
          <option value="">全部部门</option>
          <option v-for="d in data.dingtalk_depts" :key="d" :value="d">{{ d }}</option>
        </select>
        <select v-model="filters.role" class="select" aria-label="角色">
          <option value="">全部角色</option>
          <option v-for="r in roleOptions" :key="r.code" :value="r.code">{{ r.name }}</option>
        </select>
        <label><input v-model="filters.unassigned" type="checkbox"> 只看未分配角色</label>
      </div>

      <div class="table-wrap">
        <table class="table" aria-label="员工角色列表">
          <thead>
            <tr><th>姓名</th><th>钉钉部门</th><th>角色</th><th>数据范围</th><th>钉钉账号</th><th>操作</th></tr>
          </thead>
          <tbody>
            <tr v-for="e in data.items" :key="e.id">
              <td>{{ e.name }}</td>
              <td>{{ e.dingtalk_dept ?? '—' }}</td>
              <td>
                <template v-if="e.role_names.length"><span v-for="r in e.role_names" :key="r" class="badge">{{ r }}</span></template>
                <span v-else class="badge badge-warn">未分配</span>
              </td>
              <td class="scope" :title="scopeText(e)">{{ scopeText(e) }}</td>
              <td><span v-if="!e.is_active" class="badge badge-bad">已停用</span><template v-else>正常</template></td>
              <td>
                <span v-if="!e.is_active" class="meta">账号停用，无法登录</span>
                <button v-else type="button" class="link-btn" @click="openDrawer(e)">分配</button>
              </td>
            </tr>
            <tr v-if="!data.items.length">
              <td colspan="6">
                <div class="state" style="padding: var(--space-8)">
                  <div class="state-title">没有符合条件的员工</div>
                  <p>调整筛选条件后再试。</p>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="pager">
        <span>共 {{ data.summary.employees }} 名员工 · 已分配角色 {{ data.summary.assigned }} 人 · 未分配 {{ data.summary.unassigned }} 人</span>
        <span>
          <button v-if="pages > 1" type="button" class="btn" :disabled="filters.page <= 1" @click="goPage(filters.page - 1)">上一页</button>
          第 {{ filters.page }} / {{ pages }} 页 · 每页 50 条
          <button v-if="pages > 1" type="button" class="btn" :disabled="filters.page >= pages" @click="goPage(filters.page + 1)">下一页</button>
        </span>
      </div>
    </div>

    <G1Drawer v-if="current && options" wide :title="`分配角色 · ${current.name}`"
              :sub="`钉钉部门：${current.dingtalk_dept ?? '—'}`" @close="closeDrawer">
      <div class="fgroup">
        <span class="flabel">角色（可多选）</span>
        <div class="checks">
          <label v-for="r in roleOptions" :key="r.code"><input v-model="form.roles" type="checkbox" :value="r.code"> {{ r.name }}</label>
        </div>
        <div v-if="errs.roles" class="field-error" role="alert">{{ errs.roles }}</div>
      </div>

      <div v-if="showAll" class="fgroup">
        <span class="flabel">数据范围</span>
        <div class="info-line">CEO、财务负责人、财务BP 查看全公司全部部门、渠道和 B端客户，无需设置范围</div>
      </div>

      <div v-if="showDept" class="fgroup">
        <span class="flabel"><span class="req">*</span> 部门范围</span>
        <div class="scope-box" :aria-invalid="errs.dept || undefined">
          <div class="checks cols-3">
            <label v-for="d in options.departments" :key="d.id"><input v-model="form.departments" type="checkbox" :value="d.id"> {{ d.name }}</label>
          </div>
        </div>
        <div class="note">适用于部门负责人、部门预算专员：只见所选部门的费用预算、实际与报表</div>
        <div v-if="errs.dept" class="field-error">请选择至少一个部门</div>
      </div>

      <div v-if="showShop" class="fgroup">
        <span class="flabel"><span class="req">*</span> 渠道 / 店铺范围</span>
        <div class="scope-box" :aria-invalid="errs.shop || undefined">
          <template v-for="ch in options.channels" :key="ch.id">
            <div class="tree-ch">
              <label><input type="checkbox" :checked="form.channels.includes(ch.id)"
                            @change="toggleChannel(ch, ($event.target as HTMLInputElement).checked)"> {{ ch.name }}</label>
            </div>
            <div class="tree-shops checks">
              <label v-for="s in ch.stores" :key="s.id">
                <input type="checkbox" :checked="storeChecked(ch.id, s.id)"
                       @change="toggleStore(ch, s.id, ($event.target as HTMLInputElement).checked)"> {{ s.name }}
                <span v-if="!s.is_active" class="meta">（已停用）</span>
              </label>
            </div>
          </template>
        </div>
        <div class="note">适用于运营：勾选渠道即包含该渠道下全部店铺</div>
        <div v-if="errs.shop" class="field-error">请选择至少一个渠道或店铺</div>
      </div>

      <div v-if="showCust" class="fgroup">
        <span class="flabel"><span class="req">*</span> B端客户范围</span>
        <div class="scope-box" :aria-invalid="errs.cust || undefined">
          <div class="checks">
            <label v-for="c in options.customers" :key="c.id"><input v-model="form.customers" type="checkbox" :value="c.id"> {{ c.name }}（{{ c.department_name }} · {{ c.currency }}）</label>
          </div>
        </div>
        <div class="note">适用于 B端业务：只见所选客户的 B 端预算、实际与报表</div>
        <div v-if="errs.cust" class="field-error">请选择至少一个 B端客户</div>
      </div>

      <div v-if="showLogi" class="fgroup">
        <span class="flabel">物流物控</span>
        <div class="info-line">只展示并允许编辑头程费率、尾程费率、仓储费率、关税率四项及其渠道 / 站点 / 品类维度，不展示收入金额与利润</div>
      </div>

      <template #footer>
        <button v-if="current.roles.length" type="button" class="btn btn-danger" :disabled="saving" @click="confirmRevoke = true">撤销全部角色</button>
        <span style="flex: 1"></span>
        <button type="button" class="btn" @click="closeDrawer">取消</button>
        <button type="button" class="btn btn-primary" :disabled="saving" @click="save">保存</button>
      </template>
    </G1Drawer>

    <G1Modal v-if="confirmRevoke && current" alert title="撤销全部角色？" @close="confirmRevoke = false">
      <p>撤销后，{{ current.name }} 下一次打开页面或登录时将看到「未开通预算权限，请联系财务负责人」，无法再查看任何预算数据。</p>
      <template #actions>
        <button type="button" class="btn" @click="confirmRevoke = false">取消</button>
        <button type="button" class="btn btn-danger" @click="revoke">确认撤销</button>
      </template>
    </G1Modal>

    <div v-if="toast" class="toast" role="status">{{ toast }}</div>
  </div>
</template>

<style scoped>
.scope { color: var(--fg-2); max-width: 360px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.fgroup { margin-bottom: var(--space-5); }
.checks { display: grid; grid-template-columns: repeat(2, 1fr); gap: var(--space-2) var(--space-4); font-size: var(--text-sm); }
.checks label { display: flex; gap: var(--space-2); align-items: center; }
.checks.cols-3 { grid-template-columns: repeat(3, 1fr); }
.scope-box { border: 1px solid var(--border-soft); border-radius: var(--radius-md); padding: var(--space-3); background: var(--surface-warm); }
.scope-box[aria-invalid="true"] { border-color: var(--danger); }
.tree-ch { font-weight: 600; margin-top: var(--space-2); font-size: var(--text-sm); }
.tree-ch:first-child { margin-top: 0; }
.tree-shops { padding-left: var(--space-6); margin-top: var(--space-1); }
.note { font-size: var(--text-xs); color: var(--muted); margin-top: var(--space-1); }
.info-line { font-size: var(--text-sm); color: var(--fg-2); padding: var(--space-2) var(--space-3); background: var(--surface-warm); border-radius: var(--radius-md); }
</style>
