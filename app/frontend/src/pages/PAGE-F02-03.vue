<script setup lang="ts">
/**
 * PAGE-F02-03 B端客户与部门（两个标签页 + 新增 / 编辑弹窗）。财务BP 维护；CEO、财务负责人只读（DEC-F02-01）。
 * 接口：GET/POST/PUT /api/master/b-customers、/api/master/departments（API-F02-03）。
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { api, ApiError } from '@/api/client'
import PageState from '@/components/PageState.vue'
import G1Modal from '@/components/g1/G1Modal.vue'
import { fieldOf, useToast } from '@/components/g1/useToast'
import '@/components/g1/g1.css'

interface Person { name: string; is_active: boolean }
interface Customer { id: number; name: string; department_id: number; department_name: string; currency: string; is_active: boolean; owners: Person[] }
interface CustomerPage {
  items: Customer[]; by_department: Record<string, number>; department_options: { id: number; name: string }[]
  currencies: { code: string; name: string }[]; budget_year: number; fx_rated_currencies: string[]; can_edit: boolean
}
interface Dept { id: number; name: string; is_active: boolean; heads: Person[]; budget_staff: Person[] }

const tab = ref<'cust' | 'dept'>('cust')
const loading = ref(true)
const error = ref<unknown>(null)
const cust = ref<CustomerPage | null>(null)
const depts = ref<Dept[]>([])
const { toast, show } = useToast()

async function load(): Promise<void> {
  error.value = null
  try {
    const [c, d] = await Promise.all([
      api.get<CustomerPage>('/api/master/b-customers'),
      api.get<{ items: Dept[] }>('/api/master/departments'),
    ])
    cust.value = c
    depts.value = d.items
  } catch (e) {
    error.value = e
  } finally {
    loading.value = false
  }
}
onMounted(load)

const canEdit = computed(() => cust.value?.can_edit === true)
const names = (ps: Person[]) => ps.map((p) => (p.is_active ? p.name : `${p.name}（已停用）`)).join('、')

// ---- 客户弹窗 ----
const cModal = ref<{ editing: Customer | null } | null>(null)
const cf = reactive({ name: '', department_id: '' as number | '', currency: '', active: true })
const ce = reactive<Record<string, string>>({})
function clear(o: Record<string, string>): void { for (const k of Object.keys(o)) delete o[k] }

function openCustomer(c: Customer | null): void {
  clear(ce)
  cModal.value = { editing: c }
  cf.name = c?.name ?? ''
  cf.department_id = c?.department_id ?? ''
  cf.currency = c?.currency ?? ''
  cf.active = c?.is_active ?? true
}
const fxMissing = computed(() => !!cf.currency && !(cust.value?.fx_rated_currencies ?? []).includes(cf.currency))

async function saveCustomer(): Promise<void> {
  clear(ce)
  const name = cf.name.trim()
  if (!name) ce.name = '请填写客户名称'
  if (!cf.department_id) ce.department_id = '请选择负责部门'
  if (!cf.currency) ce.currency = '请选择结算币种'
  if (Object.keys(ce).length) return
  const editing = cModal.value?.editing ?? null
  const body = { name, department_id: cf.department_id, currency: cf.currency, is_active: cf.active }
  try {
    if (editing) await api.put(`/api/master/b-customers/${editing.id}`, body)
    else await api.post('/api/master/b-customers', body)
    const deptName = cust.value?.department_options.find((d) => d.id === cf.department_id)?.name
    cModal.value = null
    show(editing ? `已保存 ${name}` : `已新增客户 ${name}，已加入${deptName}的 B端填报`)
    await load()
  } catch (e) {
    if (e instanceof ApiError) ce[fieldOf(e.details) ?? 'name'] = e.message
    else ce.name = '保存失败，请重试'
  }
}

// ---- 部门弹窗 ----
const dModal = ref<{ editing: Dept | null } | null>(null)
const df = reactive({ name: '', active: true, err: '' })
function openDept(d: Dept | null): void {
  dModal.value = { editing: d }
  df.name = d?.name ?? ''
  df.active = d?.is_active ?? true
  df.err = ''
}
async function saveDept(): Promise<void> {
  const name = df.name.trim()
  df.err = ''
  if (!name) { df.err = '请填写部门名称'; return }
  const editing = dModal.value?.editing ?? null
  try {
    if (editing) await api.put(`/api/master/departments/${editing.id}`, { name, is_active: df.active })
    else await api.post('/api/master/departments', { name })
    dModal.value = null
    show(editing ? '已保存' : `已新增部门 ${name}，请在角色与权限中指定负责人`)
    await load()
  } catch (e) {
    df.err = e instanceof ApiError ? e.message : '保存失败，请重试'
  }
}
</script>

<template>
  <div class="g1" data-page-id="PAGE-F02-03">
    <div class="page-head"><h1 class="page-title">B端客户与部门</h1></div>

    <div class="tabs" role="tablist">
      <a class="tab" href="#" role="tab" :aria-selected="tab === 'cust' ? 'true' : 'false'" @click.prevent="tab = 'cust'">B端客户</a>
      <a class="tab" href="#" role="tab" :aria-selected="tab === 'dept' ? 'true' : 'false'" @click.prevent="tab = 'dept'">部门</a>
    </div>

    <PageState v-if="loading" state="loading" :rows="3" />
    <PageState v-else-if="error && error instanceof ApiError && error.isForbidden" state="forbidden" description="B端客户与部门清单由财务BP 维护。" />
    <PageState v-else-if="error" state="error" title="数据加载失败" description="网络异常或服务暂时不可用，请重试。" @retry="load" />

    <template v-else-if="cust">
      <section v-if="tab === 'cust'" role="tabpanel">
        <PageState v-if="cust.items.length === 0" title="还没有 B端客户" description="新增客户并指定负责部门与结算币种后，该客户会出现在负责部门的 B端填报中。">
          <template #action><button v-if="canEdit" type="button" class="btn" @click="openCustomer(null)">新增客户</button><span v-else /></template>
        </PageState>
        <template v-else>
          <div class="bar">
            <span class="meta">共 {{ cust.items.length }} 个客户<template v-for="(n, d) in cust.by_department" :key="d"> · {{ d }} {{ n }}</template></span>
            <button v-if="canEdit" type="button" class="btn btn-primary" @click="openCustomer(null)">新增客户</button>
          </div>
          <div class="table-wrap">
            <table class="table" aria-label="B端客户">
              <thead><tr><th>客户名称</th><th>负责部门</th><th>结算币种</th><th>B端业务负责人</th><th>状态</th><th>操作</th></tr></thead>
              <tbody>
                <tr v-for="c in cust.items" :key="c.id" :class="{ off: !c.is_active }">
                  <td>{{ c.name }}</td>
                  <td>{{ c.department_name }}</td>
                  <td class="cur">{{ c.currency }}</td>
                  <td><RouterLink v-if="c.owners.length" class="link" :to="{ name: 'roles' }">{{ names(c.owners) }}</RouterLink><span v-else class="meta">未分配</span></td>
                  <td><span v-if="c.is_active" class="badge badge-good">启用</span><span v-else class="badge">停用</span></td>
                  <td><button v-if="canEdit" type="button" class="link-btn" @click="openCustomer(c)">编辑</button><span v-else class="meta">只读</span></td>
                </tr>
              </tbody>
            </table>
          </div>
          <p class="meta">B端业务负责人取自「角色与权限」中分配了该客户范围的员工。</p>
        </template>
      </section>

      <section v-else role="tabpanel">
        <div class="bar">
          <span class="meta">共 {{ depts.length }} 个部门</span>
          <button v-if="canEdit" type="button" class="btn btn-primary" @click="openDept(null)">新增部门</button>
        </div>
        <div class="table-wrap">
          <table class="table" aria-label="部门清单">
            <thead><tr><th class="num">序号</th><th>部门名称</th><th>部门负责人</th><th>部门预算专员</th><th>状态</th><th>操作</th></tr></thead>
            <tbody>
              <tr v-for="(d, i) in depts" :key="d.id" :class="{ off: !d.is_active }">
                <td class="num">{{ i + 1 }}</td>
                <td>{{ d.name }}</td>
                <td>{{ d.heads.length ? names(d.heads) : '—' }}</td>
                <td>{{ d.budget_staff.length ? names(d.budget_staff) : '—' }}</td>
                <td><span v-if="d.is_active" class="badge badge-good">启用</span><span v-else class="badge">停用</span></td>
                <td><button v-if="canEdit" type="button" class="link-btn" @click="openDept(d)">编辑</button><span v-else class="meta">只读</span></td>
              </tr>
            </tbody>
          </table>
        </div>
        <p class="meta">部门负责人、部门预算专员取自「角色与权限」，在 <RouterLink class="link" :to="{ name: 'roles' }">角色与权限</RouterLink> 中修改。</p>
      </section>
    </template>

    <G1Modal v-if="cModal && cust" :title="cModal.editing ? `编辑 B端客户 · ${cModal.editing.name}` : '新增 B端客户'" @close="cModal = null">
      <div class="field">
        <label for="cm-name"><span class="req">*</span> 客户名称</label>
        <input id="cm-name" v-model="cf.name" class="input" placeholder="如 Home Hardware" :aria-invalid="!!ce.name || undefined">
        <div v-if="ce.name" class="field-error">{{ ce.name }}</div>
        <div class="hint">客户名称不能重复</div>
      </div>
      <div class="field">
        <label for="cm-dept"><span class="req">*</span> 负责部门</label>
        <select id="cm-dept" v-model="cf.department_id" class="select" :aria-invalid="!!ce.department_id || undefined">
          <option value="">请选择</option>
          <option v-for="d in cust.department_options" :key="d.id" :value="d.id">{{ d.name }}</option>
        </select>
        <div v-if="ce.department_id" class="field-error">{{ ce.department_id }}</div>
        <div class="hint">保存后，该客户出现在负责部门的 B端填报中</div>
      </div>
      <div class="field">
        <label for="cm-cur"><span class="req">*</span> 结算币种</label>
        <select id="cm-cur" v-model="cf.currency" class="select" :aria-invalid="!!ce.currency || undefined">
          <option value="">请选择</option>
          <option v-for="c in cust.currencies" :key="c.code" :value="c.code">{{ c.code }}</option>
        </select>
        <div v-if="ce.currency" class="field-error">{{ ce.currency }}</div>
        <div v-if="fxMissing" class="warn-line">{{ cust.budget_year }} 年度尚无该币种的预算汇率，涉及该币种的填报将无法提交。<RouterLink :to="{ name: 'fx' }">去汇率页补录</RouterLink></div>
      </div>
      <div v-if="cModal.editing" class="field">
        <span class="flabel">状态</span>
        <div class="radio">
          <label><input v-model="cf.active" type="radio" :value="true"> 启用</label>
          <label><input v-model="cf.active" type="radio" :value="false"> 停用</label>
        </div>
        <div class="hint">停用后不再出现在新的 B端填报中；已有预算与实际数据保留。客户不可删除</div>
      </div>
      <template #actions>
        <button type="button" class="btn" @click="cModal = null">取消</button>
        <button type="button" class="btn btn-primary" @click="saveCustomer">保存</button>
      </template>
    </G1Modal>

    <G1Modal v-if="dModal" :title="dModal.editing ? `编辑部门 · ${dModal.editing.name}` : '新增部门'" @close="dModal = null">
      <div class="field">
        <label for="dm-name"><span class="req">*</span> 部门名称</label>
        <input id="dm-name" v-model="df.name" class="input" placeholder="如 品牌部" :aria-invalid="!!df.err || undefined">
        <div v-if="df.err" class="field-error">{{ df.err }}</div>
        <div class="hint">部门名称不能重复，且须与金蝶辅助核算中的部门名称一致，否则金蝶导入会校验失败</div>
      </div>
      <div v-if="dModal.editing" class="field">
        <span class="flabel">状态</span>
        <div class="radio">
          <label><input v-model="df.active" type="radio" :value="true"> 启用</label>
          <label><input v-model="df.active" type="radio" :value="false"> 停用</label>
        </div>
        <div class="hint">停用后不再出现在新的编制任务与部门费用填报中；已有预算与实际数据保留。部门不可删除</div>
      </div>
      <template #actions>
        <button type="button" class="btn" @click="dModal = null">取消</button>
        <button type="button" class="btn btn-primary" @click="saveDept">保存</button>
      </template>
    </G1Modal>

    <div v-if="toast" class="toast" role="status">{{ toast }}</div>
  </div>
</template>

<style scoped>
.bar { justify-content: space-between; }
</style>
