<script setup lang="ts">
/**
 * PAGE-F02-01 渠道与店铺（列表 + 编辑抽屉）。财务BP 维护；财务负责人设置新渠道标记；CEO 只读（DEC-F02-01）。
 * 接口：GET/POST/PUT /api/master/stores、/api/master/channels，PUT …/new-channel（API-F02-01）。
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { api, ApiError } from '@/api/client'
import PageState from '@/components/PageState.vue'
import G1Drawer from '@/components/g1/G1Drawer.vue'
import G1Modal from '@/components/g1/G1Modal.vue'
import { addMonths, fieldOf, useToast } from '@/components/g1/useToast'
import '@/components/g1/g1.css'

interface NewChannel { start: string; end: string; regular_from: string; level: 'store' | 'channel'; status: 'upcoming' | 'active' | 'expired'; is_new: boolean }
interface StoreRow {
  id: number; name: string; channel_id: number; channel_name: string; site_id: number; site_name: string
  currency: string; is_active: boolean; used: boolean; store_new_channel: boolean; store_new_channel_start: string | null
  new_channel: NewChannel | null
}
interface ChannelRow { id: number; name: string; new_channel: NewChannel | null }
interface StorePage {
  month: string; budget_year: number; channels: ChannelRow[]; stores: StoreRow[]
  sites: { id: number; code: string; name: string }[]; currencies: { code: string; name: string }[]
  fx_rated_currencies: string[]; summary: { channels: number; stores: number; active: number; inactive: number }
  can_edit: boolean; can_mark_new_channel: boolean
}

const loading = ref(true)
const error = ref<unknown>(null)
const data = ref<StorePage | null>(null)
const f = reactive({ channel: '', status: '', onlyNew: false })
const { toast, show } = useToast()

async function load(): Promise<void> {
  error.value = null
  try {
    data.value = await api.get<StorePage>('/api/master/stores')
  } catch (e) {
    error.value = e
  } finally {
    loading.value = false
  }
}
onMounted(load)

const rows = computed(() => (data.value?.stores ?? []).filter((s) =>
  (!f.channel || String(s.channel_id) === f.channel)
  && (!f.status || (f.status === 'on') === s.is_active)
  && (!f.onlyNew || s.new_channel?.is_new === true)))

function firstOfChannel(i: number): boolean {
  return i === 0 || rows.value[i - 1].channel_id !== rows.value[i].channel_id
}

// ---- 店铺抽屉 ----
const drawer = ref<{ mode: 'new' | 'edit' | 'mark'; store: StoreRow | null } | null>(null)
const form = reactive({ channel_id: '' as number | '', name: '', site_id: '' as number | '', currency: '', active: true, isNew: false, start: '' })
const fe = reactive<Record<string, string>>({})
const saving = ref(false)
const confirm = ref<{ kind: 'rename' | 'off'; body: string; next: () => void } | null>(null)

function resetErrors(): void {
  for (const k of Object.keys(fe)) delete fe[k]
}

function openStore(store: StoreRow | null): void {
  resetErrors()
  const mode = store === null ? 'new' : data.value?.can_mark_new_channel ? 'mark' : 'edit'
  drawer.value = { mode, store }
  form.channel_id = store?.channel_id ?? ''
  form.name = store?.name ?? ''
  form.site_id = store?.site_id ?? ''
  form.currency = store?.currency ?? ''
  form.active = store?.is_active ?? true
  form.isNew = store?.store_new_channel ?? false
  form.start = store?.store_new_channel_start ?? ''
}

const drawerTitle = computed(() => {
  const d = drawer.value
  if (!d) return ''
  if (d.mode === 'new') return '新增店铺'
  return (d.mode === 'mark' ? '新渠道标记 · ' : '编辑店铺 · ') + d.store?.name
})
const lock = computed(() => drawer.value?.mode === 'mark')
const currencyLocked = computed(() => drawer.value?.mode === 'edit' && !!drawer.value.store?.used)
const fxMissing = computed(() => !!form.currency && !(data.value?.fx_rated_currencies ?? []).includes(form.currency))
const channelMarked = computed(() => {
  const s = drawer.value?.store
  return !!s && !s.store_new_channel && s.new_channel?.level === 'channel'
})
const newReadonly = computed(() => {
  const s = drawer.value?.store
  const info = s?.new_channel
  const bp = drawer.value?.mode !== 'mark'
  if (!info) return bp ? '未标记。新渠道由财务负责人设置' : ''
  return `新渠道：${info.start} 起至 ${info.end}${info.level === 'channel' ? `（随渠道 ${s?.channel_name} 标记）` : ''}${bp ? '。由财务负责人设置' : ''}`
})
const startHint = computed(() => form.start
  ? `将于 ${form.start} 至 ${addMonths(form.start, 11)} 按新渠道处理，${addMonths(form.start, 12)} 起自动转为常规渠道`
  : '起始月起 12 个月内按新渠道处理，满 12 个月自动转为常规渠道')

function applyError(e: unknown, fallbackField = 'name'): void {
  if (e instanceof ApiError) {
    const fields = e.details.fields as Record<string, string> | undefined
    if (fields) Object.assign(fe, fields)
    else fe[fieldOf(e.details) ?? fallbackField] = e.message
  } else {
    fe[fallbackField] = '保存失败，请重试'
  }
}

async function commitStore(): Promise<void> {
  const d = drawer.value
  if (!d) return
  saving.value = true
  const body = { channel_id: form.channel_id, name: form.name.trim(), site_id: form.site_id, currency: form.currency, is_active: form.active }
  try {
    if (d.mode === 'new') await api.post('/api/master/stores', body)
    else await api.put(`/api/master/stores/${d.store?.id}`, body)
    drawer.value = null
    show(d.mode === 'new' ? `已新增店铺 ${body.name}，填报与导入中可选用` : `已保存 ${body.name}`)
    await load()
  } catch (e) {
    applyError(e)
  } finally {
    saving.value = false
  }
}

async function saveMark(): Promise<void> {
  const s = drawer.value?.store
  if (!s) return
  if (form.isNew && !form.start) {
    fe.start = '请选择起始月'
    return
  }
  saving.value = true
  try {
    await api.put(`/api/master/stores/${s.id}/new-channel`, { is_new: form.isNew, start: form.isNew ? form.start : null })
    drawer.value = null
    show(form.isNew ? `${s.name} 已标记为新渠道，${form.start} 起 12 个月` : `已取消 ${s.name} 的新渠道标记`)
    await load()
  } catch (e) {
    applyError(e, 'start')
  } finally {
    saving.value = false
  }
}

function saveStore(): void {
  resetErrors()
  if (drawer.value?.mode === 'mark') {
    void saveMark()
    return
  }
  const name = form.name.trim()
  if (!form.channel_id) fe.channel_id = '请选择所属渠道'
  if (!name) fe.name = '请填写店铺名称'
  else if ((data.value?.stores ?? []).some((s) => s.id !== drawer.value?.store?.id && s.name.toLowerCase() === name.toLowerCase())) fe.name = '店铺名称已存在'
  if (!form.site_id) fe.site_id = '请选择站点'
  if (!form.currency) fe.currency = '请选择结算币种'
  if (Object.keys(fe).length) return
  const s = drawer.value?.store
  const stepOff = () => {
    if (s && s.is_active && !form.active) {
      confirm.value = { kind: 'off', body: `停用后，${name} 不再出现在新预算填报中；历史实际导入仍接受该店铺的数据。`, next: commitStore }
      return
    }
    void commitStore()
  }
  if (s && s.used && s.name !== name) {
    confirm.value = {
      kind: 'rename',
      body: `将「${s.name}」改名为「${name}」？该店铺已被填报或导入使用，新名称须与金蝶辅助核算、BI 中的店铺名称一致，否则之后的导入无法匹配该店铺。`,
      next: stepOff,
    }
    return
  }
  stepOff()
}

function confirmOk(): void {
  const next = confirm.value?.next
  confirm.value = null
  next?.()
}

// ---- 新增渠道（财务BP） ----
const chModal = ref(false)
const chName = ref('')
const chErr = ref('')
async function saveChannel(): Promise<void> {
  const n = chName.value.trim()
  chErr.value = ''
  if (!n) { chErr.value = '请填写渠道名称'; return }
  try {
    await api.post('/api/master/channels', { name: n })
    chModal.value = false
    show(`已新增渠道 ${n}，请在其下新增店铺`)
    await load()
  } catch (e) {
    chErr.value = e instanceof ApiError ? e.message : '保存失败，请重试'
  }
}
function openChannel(): void {
  chName.value = ''
  chErr.value = ''
  chModal.value = true
}

// ---- 渠道级新渠道标记（财务负责人） ----
const chMark = ref<ChannelRow | null>(null)
const chMarkForm = reactive({ on: false, start: '', err: '' })
function openChMark(ch: ChannelRow): void {
  chMark.value = ch
  chMarkForm.on = !!ch.new_channel
  chMarkForm.start = ch.new_channel?.start ?? ''
  chMarkForm.err = ''
}
async function saveChMark(): Promise<void> {
  const ch = chMark.value
  if (!ch) return
  if (chMarkForm.on && !chMarkForm.start) { chMarkForm.err = '请选择起始月'; return }
  try {
    await api.put(`/api/master/channels/${ch.id}/new-channel`, { is_new: chMarkForm.on, start: chMarkForm.on ? chMarkForm.start : null })
    chMark.value = null
    show(chMarkForm.on ? `${ch.name} 已标记为新渠道，${chMarkForm.start} 起 12 个月` : `已取消 ${ch.name} 的新渠道标记`)
    await load()
  } catch (e) {
    chMarkForm.err = e instanceof ApiError ? e.message : '保存失败，请重试'
  }
}
function channelOf(id: number): ChannelRow | undefined {
  return data.value?.channels.find((c) => c.id === id)
}
</script>

<template>
  <div class="g1" data-page-id="PAGE-F02-01">
    <div class="page-head">
      <h1 class="page-title">渠道与店铺</h1>
      <div v-if="data?.can_edit && !error" class="actions">
        <button type="button" class="btn" @click="openChannel">新增渠道</button>
        <button type="button" class="btn btn-primary" @click="openStore(null)">新增店铺</button>
      </div>
    </div>

    <PageState v-if="loading" state="loading" :rows="4" />
    <PageState v-else-if="error && error instanceof ApiError && error.isForbidden" state="forbidden"
               description="渠道与店铺由财务BP 维护，新渠道标记由财务负责人设置。" />
    <PageState v-else-if="error" state="error" title="渠道与店铺加载失败" description="网络异常或服务暂时不可用，请重试。" @retry="load" />
    <PageState v-else-if="data && data.channels.length === 0" title="还没有渠道和店铺"
               description="先新增渠道，再在渠道下新增店铺；店铺会出现在预算填报和实际数导入的校验中。">
      <template #action><button v-if="data.can_edit" type="button" class="btn" @click="openChannel">新增渠道</button><span v-else /></template>
    </PageState>

    <div v-else-if="data">
      <div class="filters">
        <select v-model="f.channel" class="select" aria-label="渠道">
          <option value="">全部渠道</option>
          <option v-for="c in data.channels" :key="c.id" :value="String(c.id)">{{ c.name }}</option>
        </select>
        <select v-model="f.status" class="select" aria-label="状态">
          <option value="">全部状态</option><option value="on">启用</option><option value="off">停用</option>
        </select>
        <label><input v-model="f.onlyNew" type="checkbox"> 只看新渠道</label>
        <span class="meta" style="margin-left: auto">店铺名称须与金蝶辅助核算、BI 中的店铺名称一致</span>
      </div>
      <div class="table-wrap">
        <table class="table" aria-label="渠道与店铺">
          <thead><tr><th>渠道</th><th>店铺名称</th><th>站点</th><th>结算币种</th><th>状态</th><th>新渠道</th><th>操作</th></tr></thead>
          <tbody>
            <tr v-for="(s, i) in rows" :key="s.id" :class="{ off: !s.is_active }">
              <td class="ch">
                <template v-if="firstOfChannel(i)">
                  {{ s.channel_name }}
                  <button v-if="data.can_mark_new_channel" type="button" class="link-btn ch-mark"
                          @click="openChMark(channelOf(s.channel_id)!)">渠道标记</button>
                </template>
              </td>
              <td class="code">{{ s.name }}</td>
              <td>{{ s.site_name }}</td>
              <td class="cur">{{ s.currency }}</td>
              <td><span v-if="s.is_active" class="badge badge-good">启用</span><span v-else class="badge">停用</span></td>
              <td>
                <template v-if="s.new_channel?.status === 'active'">
                  <span class="badge badge-warn">新渠道</span>
                  <span class="meta"> {{ s.new_channel.start }}～{{ s.new_channel.end }}{{ s.new_channel.level === 'channel' ? '（渠道级）' : '' }}</span>
                </template>
                <span v-else-if="s.new_channel?.status === 'expired'" class="meta">已转常规（{{ s.new_channel.end }} 满 12 个月）</span>
                <span v-else-if="s.new_channel?.status === 'upcoming'" class="meta">{{ s.new_channel.start }} 起按新渠道处理{{ s.new_channel.level === 'channel' ? '（渠道级）' : '' }}</span>
                <template v-else>—</template>
              </td>
              <td>
                <button v-if="data.can_mark_new_channel" type="button" class="link-btn" @click="openStore(s)">设置新渠道</button>
                <button v-else-if="data.can_edit" type="button" class="link-btn" @click="openStore(s)">编辑</button>
                <span v-else class="meta">只读</span>
              </td>
            </tr>
            <tr v-if="!rows.length">
              <td colspan="7"><div class="state" style="padding: var(--space-8)"><div class="state-title">没有符合条件的店铺</div><p>调整筛选条件后再试。</p></div></td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="pager">
        <span>共 {{ data.summary.channels }} 个渠道 · {{ data.summary.stores }} 个店铺（启用 {{ data.summary.active }}，停用 {{ data.summary.inactive }}）</span>
        <span>第 1 / 1 页</span>
      </div>
    </div>

    <G1Drawer v-if="drawer && data" :title="drawerTitle" @close="drawer = null">
      <div class="field">
        <label for="s-ch"><span class="req">*</span> 所属渠道</label>
        <select id="s-ch" v-model="form.channel_id" class="select" :disabled="lock || currencyLocked" :aria-invalid="!!fe.channel_id || undefined">
          <option value="">请选择</option>
          <option v-for="c in data.channels" :key="c.id" :value="c.id">{{ c.name }}</option>
        </select>
        <div v-if="fe.channel_id" class="field-error">{{ fe.channel_id }}</div>
      </div>
      <div class="field">
        <label for="s-name"><span class="req">*</span> 店铺名称</label>
        <input id="s-name" v-model="form.name" class="input" :readonly="lock" :aria-invalid="!!fe.name || undefined"
               placeholder="与金蝶、BI 中的店铺名称一致，如 Amazon-US-02">
        <div v-if="fe.name" class="field-error">{{ fe.name }}</div>
      </div>
      <div class="field">
        <label for="s-site"><span class="req">*</span> 站点</label>
        <select id="s-site" v-model="form.site_id" class="select" :disabled="lock || currencyLocked" :aria-invalid="!!fe.site_id || undefined">
          <option value="">请选择</option>
          <option v-for="s in data.sites" :key="s.id" :value="s.id">{{ s.name }}</option>
        </select>
        <div v-if="fe.site_id" class="field-error">{{ fe.site_id }}</div>
      </div>
      <div class="field">
        <label for="s-cur"><span class="req">*</span> 结算币种</label>
        <select id="s-cur" v-model="form.currency" class="select" :disabled="lock || currencyLocked" :aria-invalid="!!fe.currency || undefined">
          <option value="">请选择</option>
          <option v-for="c in data.currencies" :key="c.code" :value="c.code">{{ c.code }}</option>
        </select>
        <div v-if="fe.currency" class="field-error">{{ fe.currency }}</div>
        <div v-if="currencyLocked" class="hint">该店铺已被填报或导入使用，结算币种不可修改</div>
        <div v-if="!lock && fxMissing" class="warn-line">{{ data.budget_year }} 年度尚无该币种的预算汇率，涉及该币种的填报将无法提交。<RouterLink :to="{ name: 'fx' }">去汇率页补录</RouterLink></div>
      </div>
      <div class="field">
        <span class="flabel">状态</span>
        <div class="radio">
          <label><input v-model="form.active" type="radio" :value="true" :disabled="lock"> 启用</label>
          <label><input v-model="form.active" type="radio" :value="false" :disabled="lock"> 停用</label>
        </div>
        <div class="hint">停用后新预算填报不再列出该店铺；历史实际导入仍接受该店铺的数据</div>
      </div>
      <div class="box">
        <h3>新渠道标记</h3>
        <div v-if="newReadonly && (!lock || channelMarked)" class="hint" style="margin: 0">{{ newReadonly }}</div>
        <div v-if="lock && !channelMarked">
          <label class="check-line"><input v-model="form.isNew" type="checkbox"> 标记为新渠道</label>
          <div v-if="form.isNew" class="field" style="margin: var(--space-3) 0 0">
            <label for="s-start"><span class="req">*</span> 起始月</label>
            <input id="s-start" v-model="form.start" class="input" type="month" min="2026-01" :aria-invalid="!!fe.start || undefined">
            <div v-if="fe.start" class="field-error">{{ fe.start }}</div>
            <div class="hint">{{ startHint }}</div>
          </div>
        </div>
      </div>
      <template #footer>
        <button type="button" class="btn" @click="drawer = null">取消</button>
        <button v-if="!(lock && channelMarked)" type="button" class="btn btn-primary" :disabled="saving" @click="saveStore">保存</button>
      </template>
    </G1Drawer>

    <G1Modal v-if="chModal" title="新增渠道" @close="chModal = false">
      <div class="field">
        <label for="c-name"><span class="req">*</span> 渠道名称</label>
        <input id="c-name" v-model="chName" class="input" placeholder="如 Temu" :aria-invalid="!!chErr || undefined">
        <div v-if="chErr" class="field-error">{{ chErr }}</div>
      </div>
      <template #actions>
        <button type="button" class="btn" @click="chModal = false">取消</button>
        <button type="button" class="btn btn-primary" @click="saveChannel">保存</button>
      </template>
    </G1Modal>

    <G1Modal v-if="chMark" :title="`新渠道标记 · ${chMark.name}`" @close="chMark = null">
      <p class="hint" style="margin: 0 0 var(--space-3)">标记在渠道上时，该渠道下全部店铺按新渠道处理</p>
      <label class="check-line" style="margin-bottom: var(--space-3)"><input v-model="chMarkForm.on" type="checkbox"> 标记为新渠道</label>
      <div v-if="chMarkForm.on" class="field">
        <label for="cn-start"><span class="req">*</span> 起始月</label>
        <input id="cn-start" v-model="chMarkForm.start" class="input" type="month" :aria-invalid="!!chMarkForm.err || undefined">
        <div v-if="chMarkForm.err" class="field-error">{{ chMarkForm.err }}</div>
        <div class="hint">起始月起 12 个月内按新渠道处理，满 12 个月自动转为常规渠道</div>
      </div>
      <template #actions>
        <button type="button" class="btn" @click="chMark = null">取消</button>
        <button type="button" class="btn btn-primary" @click="saveChMark">保存</button>
      </template>
    </G1Modal>

    <G1Modal v-if="confirm" alert :title="confirm.kind === 'rename' ? '修改店铺名称？' : '停用店铺？'" @close="confirm = null">
      <p>{{ confirm.body }}</p>
      <template #actions>
        <button type="button" class="btn" @click="confirm = null">取消</button>
        <button v-if="confirm.kind === 'rename'" type="button" class="btn btn-primary" @click="confirmOk">确认改名</button>
        <button v-else type="button" class="btn btn-danger" @click="confirmOk">确认停用</button>
      </template>
    </G1Modal>

    <div v-if="toast" class="toast" role="status">{{ toast }}</div>
  </div>
</template>

<style scoped>
.table td.ch { font-weight: 600; }
.ch-mark { font-weight: 400; font-size: var(--text-xs); margin-left: var(--space-1); }
.check-line { display: flex; gap: var(--space-2); align-items: center; font-size: var(--text-sm); }
</style>
