<script setup lang="ts">
/** PAGE-F03-02 编制任务详情：进度看板、提交率、逾期提醒、提交 CEO、CEO 退回后退回指定单位（AC-F03-03/04、AC-F07-04/06） */
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { api, ApiError } from '@/api/client'
import PageState from '@/components/PageState.vue'
import G2Modal from '@/components/g2/G2Modal.vue'
import { errorText, isForbidden, toast, UNIT_STATUS_BADGE, type UnitInfo } from '@/components/g2/util'
import { useUiStore } from '@/stores/ui'
import '@/components/g2/g2.css'

interface ProgressUnit extends UnitInfo {
  reminded: boolean
  return_reason_display: string | null
}
interface Progress {
  task: { id: number; name: string; year: number; deadline: string; status: string; status_label: string; unit_count: number; created_by: string | null; created_at: string | null }
  deadline_passed: boolean
  overdue_notified_at: string | null
  overdue_notified_count: number
  submit_rate: string | null
  submitted_count: number
  unit_count: number
  counts: Record<string, number>
  ceo_return: { reason: string; by: string | null; at: string | null } | null
  can_manage: boolean
  units: ProgressUnit[]
}

const TASK_BADGE: Record<string, string> = { 进行中: 'badge', '待CEO审批': 'badge badge-info', 'CEO 已退回': 'badge badge-bad', 已完成: 'badge badge-good' }
const STATUSES = ['未开始', '填报中', '已提交', '已退回', '已通过']
const TYPES = ['平台渠道', 'B端', '成本比例', '物流比例', '部门费用']

const route = useRoute()
const ui = useUiStore()
const p = ref<Progress | null>(null)
const loading = ref(true)
const error = ref<unknown>(null)
const fStatus = ref('')
const fType = ref('')
const fOverdue = ref(false)

async function load(): Promise<void> {
  loading.value = p.value === null
  error.value = null
  try {
    p.value = await api.get<Progress>(`/api/tasks/${route.params.id}/progress`)
    ui.setCrumbTitle(p.value.task.name)
  } catch (e) {
    error.value = e
  } finally {
    loading.value = false
  }
}
onMounted(load)

const list = computed(() =>
  (p.value?.units ?? []).filter(
    (u) => (!fStatus.value || u.status_label === fStatus.value) && (!fType.value || u.type_label === fType.value) && (!fOverdue.value || u.overdue),
  ),
)
const notSubmitted = computed(() => (p.value ? p.value.counts.not_started + p.value.counts.filling + p.value.counts.returned : 0))
const isCeoReturned = computed(() => p.value?.task.status_label === 'CEO 已退回')

// ---- 提交 CEO ----
const blocked = ref<{ name: string; status_label: string }[] | null>(null)
const confirmCeo = ref(false)
const busy = ref(false)
function startCeo(): void {
  if (!p.value) return
  const notPass = p.value.units.filter((u) => u.status !== 'approved')
  if (notPass.length) blocked.value = notPass.map((u) => ({ name: u.name, status_label: u.status_label }))
  else confirmCeo.value = true
}
async function submitCeo(): Promise<void> {
  if (busy.value) return
  busy.value = true
  try {
    await api.post(`/api/tasks/${route.params.id}/submit-to-ceo`)
    confirmCeo.value = false
    toast('已提交 CEO 审批，已通知 CEO')
    await load()
  } catch (e) {
    confirmCeo.value = false
    if (e instanceof ApiError && Array.isArray(e.details.units)) blocked.value = e.details.units as { name: string; status_label: string }[]
    else toast(errorText(e))
  } finally {
    busy.value = false
  }
}

// ---- 退回给填报人 ----
const retUnit = ref<ProgressUnit | null>(null)
const retReason = ref('')
const retErr = ref('')
function openReturn(u: ProgressUnit): void {
  retUnit.value = u
  retReason.value = ''
  retErr.value = ''
}
async function doReturn(): Promise<void> {
  if (!retUnit.value) return
  if (!retReason.value.trim()) {
    retErr.value = '请填写退回原因'
    return
  }
  try {
    await api.post(`/api/tasks/${route.params.id}/units/${retUnit.value.id}/return`, { reason: retReason.value })
    toast(`已退回给 ${retUnit.value.filler?.name ?? '填报人'}，并发送钉钉工作通知`)
    retUnit.value = null
    await load()
  } catch (e) {
    retErr.value = errorText(e)
  }
}
</script>

<template>
  <div data-page-id="PAGE-F03-02" class="g2">
    <PageState v-if="loading" state="loading" :rows="8" />
    <PageState
      v-else-if="error"
      :error="error"
      :title="isForbidden(error) ? undefined : '编制任务加载失败'"
      :description="isForbidden(error) ? '编制任务只对财务负责人开放。如需查看填报进度，请联系财务负责人。' : undefined"
      @retry="load"
    />
    <template v-else-if="p">
      <div class="page-head">
        <div>
          <h1 class="page-title">{{ p.task.name }}</h1>
          <p class="sub">{{ p.task.created_by }} 发布于 {{ p.task.created_at }} · 截止日期 {{ p.task.deadline }} · 参与单位 {{ p.unit_count }} 个</p>
        </div>
        <div class="toolbar">
          <span :class="TASK_BADGE[p.task.status_label] ?? 'badge'" data-task-status>{{ p.task.status_label }}</span>
          <button
            v-if="p.can_manage && p.task.status !== 'completed'"
            class="btn btn-primary"
            type="button"
            data-submit-ceo
            :disabled="p.task.status === 'pending_ceo'"
            @click="startCeo"
          >
            {{ p.task.status === 'pending_ceo' ? '已提交 CEO 审批' : '提交 CEO 审批' }}
          </button>
        </div>
      </div>

      <div v-if="p.deadline_passed && p.overdue_notified_at && p.task.status === 'in_progress'" class="notice notice-warn" role="status">
        <span class="t">已过截止日期</span> · {{ p.overdue_notified_at }} 已向 <b>{{ p.overdue_notified_count }}</b> 个未提交单位的填报人及其部门负责人发送钉钉逾期提醒。
      </div>
      <div v-if="p.ceo_return" class="notice notice-bad" role="status" data-ceo-return>
        <span class="t">CEO 已退回</span> · {{ p.ceo_return.by }} {{ p.ceo_return.at }}：{{ p.ceo_return.reason }}<br />
        你可以把需要修改的单位退回给其填报人；修改后须重新经部门审核通过，再提交 CEO 审批。
      </div>

      <div class="kpis">
        <div class="card fade-in">
          <div class="kpi-label">提交率（已提交 + 已通过）</div>
          <div class="kpi-value tnum" data-submit-rate>{{ p.submit_rate ? `${p.submit_rate}%` : '—' }}</div>
          <div class="kpi-foot">{{ p.submitted_count }} / {{ p.unit_count }} 个单位</div>
        </div>
        <div class="card fade-in"><div class="kpi-label">已通过部门审核</div><div class="kpi-value tnum">{{ p.counts.approved }}</div><div class="kpi-foot">提交 CEO 审批需全部通过</div></div>
        <div class="card fade-in"><div class="kpi-label">已提交待审核</div><div class="kpi-value tnum">{{ p.counts.submitted }}</div><div class="kpi-foot">等待部门负责人审核</div></div>
        <div class="card fade-in">
          <div class="kpi-label">未提交</div>
          <div class="kpi-value tnum" :class="{ bad: notSubmitted > 0 && p.deadline_passed }">{{ notSubmitted }}</div>
          <div class="kpi-foot">未开始 {{ p.counts.not_started }} · 填报中 {{ p.counts.filling }} · 已退回 {{ p.counts.returned }}</div>
        </div>
      </div>

      <div class="toolbar filters" style="margin-bottom: var(--space-3)">
        <label class="sub" style="margin: 0">状态 <select v-model="fStatus" class="select"><option value="">全部</option><option v-for="s in STATUSES" :key="s">{{ s }}</option></select></label>
        <label class="sub" style="margin: 0">类型 <select v-model="fType" class="select"><option value="">全部</option><option v-for="t in TYPES" :key="t">{{ t }}</option></select></label>
        <label class="sub" style="margin: 0"><input v-model="fOverdue" type="checkbox" /> 只看逾期</label>
        <span class="sub" style="margin: 0 0 0 auto">共 {{ list.length }} 个单位</span>
      </div>
      <PageState v-if="!p.units.length" state="empty" title="该编制任务没有参与单位" description="发布任务时未选择填报单位。请返回编制任务列表重新发布。">
        <template #action><RouterLink class="btn" :to="{ name: 'tasks' }">返回编制任务</RouterLink></template>
      </PageState>
      <div v-else class="table-wrap">
        <table class="table" aria-label="填报单位进度">
          <thead>
            <tr><th>填报单位</th><th>类型</th><th>填报人</th><th>状态</th><th class="num">最后更新</th><th>逾期</th><th>退回原因</th><th>操作</th></tr>
          </thead>
          <tbody>
            <tr v-if="!list.length">
              <td colspan="8"><div class="state"><div class="state-title">没有符合条件的填报单位</div><div>调整状态、类型或逾期筛选后再看。</div></div></td>
            </tr>
            <tr v-for="u in list" :key="u.id" :data-unit="u.name">
              <td>{{ u.name }}</td>
              <td>{{ u.type_label }}</td>
              <td>{{ u.filler?.name }}</td>
              <td><span :class="UNIT_STATUS_BADGE[u.status] ?? 'badge'" data-unit-status>{{ u.status_label }}</span></td>
              <td class="num">{{ u.updated_at ?? '—' }}</td>
              <td>
                <span v-if="u.overdue" class="badge badge-warn">{{ u.reminded ? '逾期 · 已提醒' : '逾期' }}</span>
                <span v-else class="muted">—</span>
              </td>
              <td class="wrap">{{ u.return_reason_display ?? '' }}<span v-if="!u.return_reason_display" class="muted">—</span></td>
              <td>
                <button v-if="p.can_manage && isCeoReturned && u.status === 'approved'" class="btn" type="button" data-return-unit @click="openReturn(u)">退回给填报人</button>
                <RouterLink v-else class="link" :to="{ name: 'approval-detail', params: { type: 'unit', id: String(u.id) } }">查看</RouterLink>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>

    <G2Modal v-if="blocked" title="还不能提交 CEO 审批" @close="blocked = null">
      <p>以下 {{ blocked.length }} 个单位尚未通过部门审核：</p>
      <ul class="err-list" data-blocked-units>
        <li v-for="u in blocked" :key="u.name">{{ u.name }}（{{ u.status_label }}）</li>
      </ul>
      <template #actions><button class="btn btn-primary" type="button" @click="blocked = null">知道了</button></template>
    </G2Modal>
    <G2Modal v-if="confirmCeo && p" title="提交 CEO 审批？" @close="confirmCeo = false">
      <p>全部 {{ p.unit_count }} 个单位已通过部门审核。提交后由 CEO 审批，审批通过即锁定为「年初原始目标」。</p>
      <template #actions>
        <button class="btn" type="button" @click="confirmCeo = false">取消</button>
        <button class="btn btn-primary" type="button" data-confirm-ceo :disabled="busy" @click="submitCeo">确认提交</button>
      </template>
    </G2Modal>
    <G2Modal v-if="retUnit" :title="`把「${retUnit.name}」退回给填报人？`" @close="retUnit = null">
      <p class="sub">退回后该单位状态变为「已退回」并解除锁定，系统通过钉钉通知填报人 {{ retUnit.filler?.name }}。</p>
      <div class="field">
        <label for="ret-reason">退回原因<span class="req">*</span></label>
        <textarea id="ret-reason" v-model="retReason" class="input" :aria-invalid="retErr ? 'true' : 'false'" placeholder="例如：按 CEO 意见复核灯镜采购成本占比与广告费率"></textarea>
        <div v-if="retErr" class="field-error">{{ retErr }}</div>
      </div>
      <template #actions>
        <button class="btn" type="button" @click="retUnit = null">取消</button>
        <button class="btn btn-danger" type="button" data-confirm-return @click="doReturn">确认退回</button>
      </template>
    </G2Modal>
  </div>
</template>
