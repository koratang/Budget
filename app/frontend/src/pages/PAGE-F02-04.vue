<script setup lang="ts">
/**
 * PAGE-F02-04 科目映射（科目映射 | 预算科目 两个标签）。财务BP 维护；CEO、财务负责人只读（DEC-F02-01）。
 * 接口：GET/POST/PUT /api/master/account-mapping（API-F02-04）；GET/POST/PUT /api/master/budget-accounts（API-F02-06）。
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { api, ApiError } from '@/api/client'
import PageState from '@/components/PageState.vue'
import G1Modal from '@/components/g1/G1Modal.vue'
import { fmtTime, useToast } from '@/components/g1/useToast'
import '@/components/g1/g1.css'

interface Mapping { kingdee_code: string; kingdee_name: string | null; account_id: number; account_name: string; account_active: boolean; updated_at: string | null; updated_by: string | null }
interface Unmapped { kingdee_code: string; kingdee_name: string | null; rows: number }
interface MappingPage {
  items: Mapping[]
  unmapped: { items: Unmapped[]; source: { at: string; file_name: string; status: string } | null }
  account_options: { id: number; name: string }[]
  summary: { mapped: number; accounts: number }
  can_edit: boolean
}
interface Account { id: number; name: string; is_active: boolean; mapped_count: number; last_modified: { at: string; by: string } | null }

const tab = ref<'map' | 'sub'>('map')
const loading = ref(true)
const error = ref<unknown>(null)
const page = ref<MappingPage | null>(null)
const accounts = ref<Account[]>([])
const f = reactive({ q: '', account: '' })
const { toast, show } = useToast()

async function load(): Promise<void> {
  error.value = null
  try {
    const [m, a] = await Promise.all([
      api.get<MappingPage>('/api/master/account-mapping'),
      api.get<{ items: Account[] }>('/api/master/budget-accounts'),
    ])
    page.value = m
    accounts.value = a.items
  } catch (e) {
    error.value = e
  } finally {
    loading.value = false
  }
}
onMounted(load)

const canEdit = computed(() => page.value?.can_edit === true)
const list = computed(() => (page.value?.items ?? []).filter((m) =>
  (!f.q || m.kingdee_code.includes(f.q.trim()) || (m.kingdee_name ?? '').includes(f.q.trim()))
  && (!f.account || String(m.account_id) === f.account)))
const accountCount = computed(() => ({
  total: accounts.value.length,
  on: accounts.value.filter((a) => a.is_active).length,
}))
const modified = (at: string | null | undefined, by: string | null | undefined) => (at ? `${fmtTime(at).slice(0, 10)} ${by ?? ''}`.trim() : '—')

// ---- 未映射区与行内修改 ----
const unmappedPick = reactive<Record<string, number | ''>>({})
const unmappedErr = reactive<Record<string, string>>({})
const editCode = ref<string | null>(null)
const editAccount = ref<number | ''>('')

async function put(code: string, name: string | null, accountId: number): Promise<boolean> {
  try {
    await api.put('/api/master/account-mapping', { kingdee_code: code, kingdee_name: name, account_id: accountId })
    return true
  } catch (e) {
    unmappedErr[code] = e instanceof ApiError ? e.message : '保存失败，请重试'
    return false
  }
}
function accountName(id: number | ''): string {
  return page.value?.account_options.find((a) => a.id === id)?.name ?? ''
}

async function saveUnmapped(u: Unmapped): Promise<void> {
  delete unmappedErr[u.kingdee_code]
  const id = unmappedPick[u.kingdee_code]
  if (!id) { unmappedErr[u.kingdee_code] = '请选择预算科目'; return }
  if (await put(u.kingdee_code, u.kingdee_name, id)) {
    show(`${u.kingdee_code} 已映射到「${accountName(id)}」，下一次金蝶导入起生效`)
    await load()
  }
}

function startEdit(m: Mapping): void {
  editCode.value = m.kingdee_code
  editAccount.value = m.account_active ? m.account_id : ''
}
async function saveEdit(m: Mapping): Promise<void> {
  if (!editAccount.value) return
  if (editAccount.value === m.account_id) { editCode.value = null; return }
  if (await put(m.kingdee_code, m.kingdee_name, editAccount.value)) {
    show(`${m.kingdee_code} 改为映射到「${accountName(editAccount.value)}」，下一次金蝶导入起生效`)
    editCode.value = null
    await load()
  }
}

// ---- 新增映射弹窗 ----
const mModal = ref(false)
const mf = reactive({ code: '', name: '', account: '' as number | '', eCode: '', eAccount: '' })
function openMapping(): void {
  Object.assign(mf, { code: '', name: '', account: '', eCode: '', eAccount: '' })
  mModal.value = true
}
async function saveMapping(): Promise<void> {
  mf.eCode = mf.eAccount = ''
  const code = mf.code.trim()
  if (!code) mf.eCode = '请填写金蝶科目编码'
  if (!mf.account) mf.eAccount = '请选择预算科目'
  if (mf.eCode || mf.eAccount) return
  try {
    await api.post('/api/master/account-mapping', { kingdee_code: code, kingdee_name: mf.name.trim() || null, account_id: mf.account })
    mModal.value = false
    show(`${code} 已映射到「${accountName(mf.account)}」`)
    await load()
  } catch (e) {
    const msg = e instanceof ApiError ? e.message : '保存失败，请重试'
    if (e instanceof ApiError && e.details.field === 'account_id') mf.eAccount = msg
    else mf.eCode = msg
  }
}

// ---- 预算科目：新增 / 改名 / 停用 ----
const sModal = ref<{ editing: Account | null } | null>(null)
const sf = reactive({ name: '', err: '' })
const offTarget = ref<Account | null>(null)
function openAccount(a: Account | null): void {
  sModal.value = { editing: a }
  sf.name = a?.name ?? ''
  sf.err = ''
}
async function saveAccount(): Promise<void> {
  const name = sf.name.trim()
  sf.err = ''
  if (!name) { sf.err = '请填写预算科目名称'; return }
  const editing = sModal.value?.editing ?? null
  try {
    if (editing) await api.put(`/api/master/budget-accounts/${editing.id}`, { name })
    else await api.post('/api/master/budget-accounts', { name })
    sModal.value = null
    show(editing ? `「${editing.name}」已改名为「${name}」，已有预算、实际与映射随之显示新名称`
      : `已新增预算科目「${name}」，部门费用填报与科目映射中可选用`)
    await load()
  } catch (e) {
    sf.err = e instanceof ApiError ? e.message : '保存失败，请重试'
  }
}
async function confirmOff(): Promise<void> {
  const a = offTarget.value
  if (!a) return
  offTarget.value = null
  try {
    await api.put(`/api/master/budget-accounts/${a.id}`, { status: '停用' })
    show(`已停用「${a.name}」`)
    await load()
  } catch (e) {
    show(e instanceof ApiError ? e.message : '停用失败，请重试')
  }
}
</script>

<template>
  <div class="g1" data-page-id="PAGE-F02-04">
    <div class="page-head">
      <h1 class="page-title">科目映射</h1>
      <template v-if="canEdit && !error">
        <button v-if="tab === 'map'" type="button" class="btn btn-primary" @click="openMapping">新增映射</button>
        <button v-else type="button" class="btn btn-primary" @click="openAccount(null)">新增预算科目</button>
      </template>
    </div>

    <div class="tabs" role="tablist">
      <button type="button" class="tab" role="tab" :aria-selected="tab === 'map'" @click="tab = 'map'">科目映射</button>
      <button type="button" class="tab" role="tab" :aria-selected="tab === 'sub'" @click="tab = 'sub'">预算科目</button>
    </div>

    <PageState v-if="loading" state="loading" :rows="4" />
    <PageState v-else-if="error && error instanceof ApiError && error.isForbidden" state="forbidden" description="科目映射由财务BP 维护。" />
    <PageState v-else-if="error" state="error" title="科目映射加载失败" description="网络异常或服务暂时不可用，请重试。" @retry="load" />

    <template v-else-if="page">
      <section v-if="tab === 'map'" role="tabpanel">
        <PageState v-if="!page.items.length && !page.unmapped.items.length" title="还没有科目映射"
                   description="为每个金蝶科目编码选择预算科目后，金蝶导入才能把金额归集到预算科目。">
          <template #action><button v-if="canEdit" type="button" class="btn" @click="openMapping">新增映射</button><span v-else /></template>
        </PageState>
        <template v-else>
          <section v-if="page.unmapped.items.length" class="card unmapped" aria-label="未映射科目">
            <div class="unmapped-head">
              <strong>未映射科目 {{ page.unmapped.items.length }} 个</strong>
              <span v-if="page.unmapped.source" class="meta">来自最近一次金蝶导入校验：{{ fmtTime(page.unmapped.source.at) }} · {{ page.unmapped.source.file_name }}（整份未写入）。映射后请到 <RouterLink class="link" :to="{ name: 'import' }">实际数导入</RouterLink> 重新上传。</span>
            </div>
            <table class="table" aria-label="未映射科目">
              <thead><tr><th>金蝶科目编码</th><th>金蝶科目名称</th><th class="num">出现行数</th><th>预算科目</th><th></th></tr></thead>
              <tbody>
                <tr v-for="u in page.unmapped.items" :key="u.kingdee_code">
                  <td class="code">{{ u.kingdee_code }}</td>
                  <td>{{ u.kingdee_name ?? '—' }}</td>
                  <td class="num">{{ u.rows || '—' }}</td>
                  <template v-if="canEdit">
                    <td>
                      <select v-model="unmappedPick[u.kingdee_code]" class="select" :aria-label="`为 ${u.kingdee_code} 选择预算科目`" :aria-invalid="!!unmappedErr[u.kingdee_code] || undefined">
                        <option value="">请选择预算科目</option>
                        <option v-for="a in page.account_options" :key="a.id" :value="a.id">{{ a.name }}</option>
                      </select>
                      <div v-if="unmappedErr[u.kingdee_code]" class="field-error">{{ unmappedErr[u.kingdee_code] }}</div>
                    </td>
                    <td><button type="button" class="btn" @click="saveUnmapped(u)">保存映射</button></td>
                  </template>
                  <td v-else colspan="2" class="meta">待财务BP 映射</td>
                </tr>
              </tbody>
            </table>
          </section>

          <div class="filters">
            <input v-model="f.q" class="input" type="search" placeholder="搜索金蝶科目编码或名称" aria-label="搜索金蝶科目">
            <select v-model="f.account" class="select" aria-label="预算科目">
              <option value="">全部预算科目</option>
              <option v-for="a in accounts" :key="a.id" :value="String(a.id)">{{ a.name }}</option>
            </select>
            <span class="meta" style="margin-left: auto">保存后从下一次金蝶导入起，按新映射归集到预算科目</span>
          </div>
          <div class="table-wrap">
            <table class="table" aria-label="科目映射">
              <thead><tr><th>金蝶科目编码</th><th>金蝶科目名称</th><th>预算科目</th><th>最近修改</th><th>操作</th></tr></thead>
              <tbody>
                <tr v-for="m in list" :key="m.kingdee_code">
                  <td class="code">{{ m.kingdee_code }}</td>
                  <td>{{ m.kingdee_name ?? '—' }}</td>
                  <template v-if="editCode === m.kingdee_code">
                    <td>
                      <select v-model="editAccount" class="select" aria-label="预算科目">
                        <option value="">请选择预算科目</option>
                        <option v-for="a in page.account_options" :key="a.id" :value="a.id">{{ a.name }}</option>
                      </select>
                      <div v-if="unmappedErr[m.kingdee_code]" class="field-error">{{ unmappedErr[m.kingdee_code] }}</div>
                    </td>
                    <td class="meta">{{ modified(m.updated_at, m.updated_by) }}</td>
                    <td><span class="row-acts"><button type="button" class="btn" @click="saveEdit(m)">保存</button><button type="button" class="link-btn" @click="editCode = null">取消</button></span></td>
                  </template>
                  <template v-else>
                    <td>{{ m.account_name }} <span v-if="!m.account_active" class="badge">已停用</span></td>
                    <td class="meta">{{ modified(m.updated_at, m.updated_by) }}</td>
                    <td><button v-if="canEdit" type="button" class="link-btn" @click="startEdit(m)">修改</button><span v-else class="meta">只读</span></td>
                  </template>
                </tr>
                <tr v-if="!list.length">
                  <td colspan="5"><div class="state" style="padding: var(--space-8)"><div class="state-title">没有符合条件的映射</div><p>调整筛选条件后再试。</p></div></td>
                </tr>
              </tbody>
            </table>
          </div>
          <div class="pager"><span>共 {{ page.summary.mapped }} 个金蝶科目已映射到 {{ page.summary.accounts }} 个预算科目</span><span>第 1 / 1 页</span></div>
        </template>
      </section>

      <section v-else role="tabpanel">
        <div class="filters">
          <span class="meta">共 {{ accountCount.total }} 个预算科目 · 启用 {{ accountCount.on }} · 停用 {{ accountCount.total - accountCount.on }}</span>
          <span class="meta" style="margin-left: auto">停用的预算科目不再出现在新的部门费用填报和科目映射选项中；已有预算与实际数据保留。预算科目不可删除</span>
        </div>
        <div class="table-wrap">
          <table class="table" aria-label="预算科目清单">
            <thead><tr><th>预算科目</th><th class="num">已映射的金蝶科目</th><th>状态</th><th>最近修改</th><th>操作</th></tr></thead>
            <tbody>
              <tr v-for="a in accounts" :key="a.id" :class="{ off: !a.is_active }">
                <td>{{ a.name }}</td>
                <td class="num">{{ a.mapped_count }}</td>
                <td><span v-if="a.is_active" class="badge badge-good">启用</span><span v-else class="badge">已停用</span></td>
                <td class="meta">{{ modified(a.last_modified?.at, a.last_modified?.by) }}</td>
                <td>
                  <span v-if="canEdit" class="row-acts">
                    <button type="button" class="link-btn" @click="openAccount(a)">改名</button>
                    <button v-if="a.is_active" type="button" class="link-btn" @click="offTarget = a">停用</button>
                  </span>
                  <span v-else class="meta">只读</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </template>

    <G1Modal v-if="mModal && page" title="新增映射" @close="mModal = false">
      <div class="field">
        <label for="m-code"><span class="req">*</span> 金蝶科目编码</label>
        <input id="m-code" v-model="mf.code" class="input code" placeholder="如 6602.42" :aria-invalid="!!mf.eCode || undefined">
        <div v-if="mf.eCode" class="field-error">{{ mf.eCode }}</div>
      </div>
      <div class="field">
        <label for="m-name">金蝶科目名称</label>
        <input id="m-name" v-model="mf.name" class="input" placeholder="如 管理费用-咨询费">
      </div>
      <div class="field">
        <label for="m-sub"><span class="req">*</span> 预算科目</label>
        <select id="m-sub" v-model="mf.account" class="select" :aria-invalid="!!mf.eAccount || undefined">
          <option value="">请选择</option>
          <option v-for="a in page.account_options" :key="a.id" :value="a.id">{{ a.name }}</option>
        </select>
        <div v-if="mf.eAccount" class="field-error">{{ mf.eAccount }}</div>
        <div class="hint">保存后从下一次金蝶导入起，该科目金额归集到所选预算科目</div>
      </div>
      <template #actions>
        <button type="button" class="btn" @click="mModal = false">取消</button>
        <button type="button" class="btn btn-primary" @click="saveMapping">保存</button>
      </template>
    </G1Modal>

    <G1Modal v-if="sModal" :title="sModal.editing ? `预算科目改名 · ${sModal.editing.name}` : '新增预算科目'" @close="sModal = null">
      <div class="field">
        <label for="sm-name"><span class="req">*</span> 预算科目名称</label>
        <input id="sm-name" v-model="sf.name" class="input" placeholder="如 咨询服务费" :aria-invalid="!!sf.err || undefined">
        <div v-if="sf.err" class="field-error">{{ sf.err }}</div>
        <div class="hint">保存后，部门费用填报与科目映射的预算科目选项按新清单显示</div>
      </div>
      <template #actions>
        <button type="button" class="btn" @click="sModal = null">取消</button>
        <button type="button" class="btn btn-primary" @click="saveAccount">保存</button>
      </template>
    </G1Modal>

    <G1Modal v-if="offTarget" alert :title="`停用预算科目「${offTarget.name}」？`" @close="offTarget = null">
      <p>停用后，该科目不再出现在新的部门费用填报和科目映射选项中；已有预算与实际数据保留{{ offTarget.mapped_count ? `，已映射到该科目的 ${offTarget.mapped_count} 个金蝶科目映射保留` : '' }}。</p>
      <template #actions>
        <button type="button" class="btn" @click="offTarget = null">取消</button>
        <button type="button" class="btn btn-danger" @click="confirmOff">确认停用</button>
      </template>
    </G1Modal>

    <div v-if="toast" class="toast" role="status">{{ toast }}</div>
  </div>
</template>

<style scoped>
.unmapped { border-color: color-mix(in oklab, var(--warn), white 60%); margin-bottom: var(--space-6); padding: 0; }
.unmapped:hover { border-color: color-mix(in oklab, var(--warn), white 40%); }
.unmapped-head { display: flex; align-items: baseline; gap: var(--space-3); padding: var(--space-3) var(--space-4); border-bottom: 1px solid var(--border-soft); }
.unmapped-head strong { color: var(--warn); }
.unmapped .table td { border-bottom: 1px solid var(--border-soft); }
.unmapped .table tr:last-child td { border-bottom: 0; }
.row-acts { display: inline-flex; gap: var(--space-3); align-items: center; }
</style>
