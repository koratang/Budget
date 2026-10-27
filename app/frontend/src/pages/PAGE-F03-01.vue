<script setup lang="ts">
/** PAGE-F03-01 编制任务列表与发布弹窗（AC-F03-01、AC-F03-02、AC-F03-05） */
import { computed, onMounted, reactive, ref } from 'vue'
import { api, ApiError } from '@/api/client'
import PageState from '@/components/PageState.vue'
import G2Modal from '@/components/g2/G2Modal.vue'
import { errorText, isForbidden, toast } from '@/components/g2/util'
import '@/components/g2/g2.css'

interface TaskRow {
  id: number
  name: string
  year: number
  deadline: string
  status: string
  status_label: string
  unit_count: number
  submit_rate: string | null
  created_by: string | null
  created_at: string | null
}
interface Candidate {
  unit_type: string
  type_label: string
  scope_object_id: number | null
  name: string
  filler: { id: number; name: string } | null
  reviewer: { id: number; name: string } | null
}

const TASK_BADGE: Record<string, string> = { 填报中: 'badge', '待 CEO 审批': 'badge badge-info', 'CEO 已退回': 'badge badge-bad', 已完成: 'badge badge-good' }
const tasks = ref<TaskRow[]>([])
const canPublish = ref(false)
const loading = ref(true)
const error = ref<unknown>(null)

async function load(): Promise<void> {
  loading.value = tasks.value.length === 0
  error.value = null
  try {
    const res = await api.get<{ items: TaskRow[]; can_publish: boolean }>('/api/tasks')
    tasks.value = res.items
    canPublish.value = res.can_publish
  } catch (e) {
    error.value = e
  } finally {
    loading.value = false
  }
}
onMounted(load)

// ---- 发布弹窗 ----
const open = ref(false)
const candidates = ref<Candidate[]>([])
const selected = ref<Set<string>>(new Set())
const form = reactive({ year: '', deadline: '' })
const errs = reactive<Record<string, string>>({})
const busy = ref(false)
const thisYear = new Date().getFullYear()
const years = [thisYear + 1, thisYear + 2]
const keyOf = (c: Candidate) => `${c.unit_type}:${c.scope_object_id ?? ''}`
const groups = computed(() => {
  const map = new Map<string, Candidate[]>()
  for (const c of candidates.value) map.set(c.type_label, [...(map.get(c.type_label) ?? []), c])
  return [...map.entries()]
})
const chosen = computed(() => candidates.value.filter((c) => selected.value.has(keyOf(c))))
const fillerCount = computed(() => new Set(chosen.value.map((c) => c.filler?.id ?? `none-${c.name}`)).size)
const preview = computed(
  () => `【预算管理平台】${form.year || '{预算年度}'} 年度预算编制已发布，截止日期 ${form.deadline || '{截止日期}'}，请在截止前完成填报：<系统链接>`,
)

async function openPublish(): Promise<void> {
  for (const k of Object.keys(errs)) delete errs[k]
  form.year = ''
  form.deadline = ''
  try {
    candidates.value = (await api.get<{ items: Candidate[] }>('/api/tasks/candidates')).items
    selected.value = new Set(candidates.value.map(keyOf))
    open.value = true
  } catch (e) {
    toast(errorText(e))
  }
}
function toggle(c: Candidate): void {
  const s = new Set(selected.value)
  if (s.has(keyOf(c))) s.delete(keyOf(c))
  else s.add(keyOf(c))
  selected.value = s
}
function groupAll(list: Candidate[]): boolean {
  return list.every((c) => selected.value.has(keyOf(c)))
}
function toggleGroup(list: Candidate[]): void {
  const all = groupAll(list)
  const s = new Set(selected.value)
  for (const c of list) {
    if (all) s.delete(keyOf(c))
    else s.add(keyOf(c))
  }
  selected.value = s
}

async function publish(): Promise<void> {
  for (const k of Object.keys(errs)) delete errs[k]
  const today = new Date().toISOString().slice(0, 10)
  if (!form.year) errs.year = '请选择预算年度'
  if (!form.deadline) errs.deadline = '请选择截止日期'
  else if (form.deadline <= today) errs.deadline = `截止日期须晚于今天（${today}）`
  if (!chosen.value.length) errs.units = '请至少选择 1 个参与填报单位'
  if (Object.keys(errs).length || busy.value) return
  busy.value = true
  try {
    const res = await api.post<{ task: TaskRow; filler_count: number }>('/api/tasks', {
      year: Number(form.year),
      deadline: form.deadline,
      units: chosen.value.map((c) => ({ unit_type: c.unit_type, scope_object_id: c.scope_object_id })),
    })
    open.value = false
    toast(`已发布「${res.task.name}」，已向 ${res.filler_count} 位填报人发送钉钉工作通知`)
    await load()
  } catch (e) {
    if (e instanceof ApiError && Array.isArray(e.details.units)) errs.dup = e.message
    else errs.dup = errorText(e)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div data-page-id="PAGE-F03-01" class="g2">
    <div class="page-head">
      <div>
        <h1 class="page-title">编制任务</h1>
        <p class="sub">发布年度预算编制任务，系统通过钉钉通知每个参与单位的填报人。同一预算年度只能有一个未完成 CEO 审批的任务。</p>
      </div>
      <button v-if="canPublish && !loading && !error" class="btn btn-primary" type="button" data-publish @click="openPublish">发布编制任务</button>
    </div>
    <PageState v-if="loading" state="loading" />
    <PageState
      v-else-if="error"
      :error="error"
      :title="isForbidden(error) ? undefined : '编制任务加载失败'"
      :description="isForbidden(error) ? '编制任务只对财务负责人开放。' : undefined"
      @retry="load"
    />
    <PageState
      v-else-if="!tasks.length"
      state="empty"
      title="还没有编制任务"
      description="发布后，系统会通过钉钉通知每个参与单位的填报人，你可以在这里跟踪填报进度。"
    >
      <template #action>
        <button v-if="canPublish" class="btn btn-primary" type="button" @click="openPublish">发布编制任务</button>
      </template>
    </PageState>
    <div v-else class="table-wrap">
      <table class="table" aria-label="编制任务列表">
        <thead>
          <tr>
            <th>任务名称</th><th class="num">预算年度</th><th class="num">截止日期</th><th class="num">参与单位</th><th class="num">提交率</th>
            <th>状态</th><th>发布人</th><th class="num">发布时间</th><th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="t in tasks" :key="t.id" :data-task="t.name">
            <td><RouterLink class="link" :to="{ name: 'task-detail', params: { id: String(t.id) } }">{{ t.name }}</RouterLink></td>
            <td class="num">{{ t.year }}</td>
            <td class="num">{{ t.deadline }}</td>
            <td class="num">{{ t.unit_count }}</td>
            <td class="num">{{ t.submit_rate ? `${t.submit_rate}%` : '—' }}</td>
            <td><span :class="TASK_BADGE[t.status_label] ?? 'badge'" data-task-status>{{ t.status_label }}</span></td>
            <td>{{ t.created_by }}</td>
            <td class="num">{{ t.created_at }}</td>
            <td><RouterLink class="link" :to="{ name: 'task-detail', params: { id: String(t.id) } }">查看进度</RouterLink></td>
          </tr>
        </tbody>
      </table>
    </div>

    <G2Modal v-if="open" title="发布编制任务" wide @close="open = false">
      <div style="display: grid; grid-template-columns: 1fr 1fr; gap: var(--space-3)">
        <div class="field">
          <label for="p-year">预算年度<span class="req">*</span></label>
          <select id="p-year" v-model="form.year" class="select" :aria-invalid="errs.year ? 'true' : 'false'">
            <option value="">请选择</option>
            <option v-for="y in years" :key="y" :value="String(y)">{{ y }}</option>
          </select>
          <div v-if="errs.year" class="field-error">{{ errs.year }}</div>
        </div>
        <div class="field">
          <label for="p-dl">截止日期<span class="req">*</span></label>
          <input id="p-dl" v-model="form.deadline" class="input" type="date" :aria-invalid="errs.deadline ? 'true' : 'false'" />
          <div v-if="errs.deadline" class="field-error">{{ errs.deadline }}</div>
        </div>
      </div>
      <div class="field">
        <span class="lbl">参与填报单位<span class="req">*</span> <span class="muted">已选 {{ chosen.length }} 个单位，涉及 {{ fillerCount }} 位填报人</span></span>
        <div style="max-height: 300px; overflow: auto; border: 1px solid var(--border); border-radius: var(--radius-md); padding: var(--space-3)">
          <fieldset v-for="[label, list] in groups" :key="label" style="border: 0; padding: 0; margin: 0 0 var(--space-3)">
            <legend style="font-weight: 600; font-size: var(--text-sm)">
              <label><input type="checkbox" :checked="groupAll(list)" @change="toggleGroup(list)" /> {{ label }}（{{ list.length }}）</label>
            </legend>
            <div style="display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: var(--space-1) var(--space-3); font-size: var(--text-sm)">
              <label v-for="c in list" :key="keyOf(c)">
                <input type="checkbox" :checked="selected.has(keyOf(c))" @change="toggle(c)" />
                {{ c.name }} <span class="muted">· {{ c.filler?.name ?? '缺填报人' }}</span>
              </label>
            </div>
          </fieldset>
        </div>
        <div v-if="errs.units" class="field-error">{{ errs.units }}</div>
      </div>
      <div class="notice" style="margin: 0">
        <div class="kpi-label">钉钉工作通知预览（不含金额）</div>
        <div class="tnum">{{ preview }}</div>
      </div>
      <div v-if="errs.dup" class="field-error" role="alert" style="font-size: var(--text-sm); margin-top: var(--space-3)">{{ errs.dup }}</div>
      <template #actions>
        <button class="btn" type="button" @click="open = false">取消</button>
        <button class="btn btn-primary" type="button" data-publish-ok :disabled="busy" @click="publish">发布并通知</button>
      </template>
    </G2Modal>
  </div>
</template>
