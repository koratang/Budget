<script setup lang="ts">
/**
 * PAGE-F11-01 预警中心：关键数、筛选、预警列表、详情弹窗（钉钉通知预览、发送与重试记录、记录变化）、
 * 标记已处理（说明必填）（API-F11-01/02；AC-F11-01~05）。
 */
import { onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { api } from '@/api/client'
import PageState from '@/components/PageState.vue'
import G3Modal from '@/components/g3/G3Modal.vue'
import { errorText, useToast } from '@/components/g3/useG3'
import '@/components/g3/g3.css'

interface Item {
  id: number; rule_name: string; rule_version_no: number; object_name: string; period_text: string
  metric_display: string; metric_parts: string[]; threshold_display: string; status: string; status_label: string
  resolved_by_name: string | null; resolved_at: string | null; resolve_note: string | null
  notify_status: string; notify_status_label: string; updated_after_resolve: boolean; updated_at: string | null; can_resolve: boolean
}
interface Detail extends Item {
  receivers: string[]; changes: { at: string | null; text: string }[]
  attempts: { label: string; at: string; ok: boolean; error: string | null }[]
  notice_preview: { title: string; name: string; object: string; period: string; link_text: string } | null
  report_link: string | null; created_at: string | null
}
interface ListData {
  kpis: { open: number; resolved: number; notify_failed: number }; rules: { id: number; name: string }[]
  total: number; page: number; page_size: number; items: Item[]; has_any: boolean
  last_evaluation: { at: string | null; file_name: string } | null
}

const route = useRoute()
const status = ref<string>('open')
const ruleId = ref<number | ''>('')
const notify = ref<string>('')
const page = ref(1)
const data = ref<ListData | null>(null)
const loading = ref(true)
const error = ref<unknown>(null)
const detail = ref<Detail | null>(null)
const handling = ref<Item | null>(null)
const note = ref('')
const noteError = ref('')
const { toast, show } = useToast()

async function load(): Promise<void> {
  error.value = null
  try {
    data.value = await api.get<ListData>('/api/alerts', {
      status: status.value, rule_id: ruleId.value, notify_status: notify.value, page: page.value, page_size: 50,
    })
  } catch (e) {
    error.value = e
  } finally {
    loading.value = false
  }
}
watch([status, ruleId, notify], () => {
  page.value = 1
  void load()
})
onMounted(async () => {
  if (route.query.id) status.value = ''
  await load()
  if (route.query.id) await openDetail(Number(route.query.id))
})

async function openDetail(id: number): Promise<void> {
  try {
    detail.value = await api.get<Detail>(`/api/alerts/${id}`)
  } catch (e) {
    show(errorText(e))
  }
}
function openHandle(it: Item): void {
  handling.value = it
  note.value = ''
  noteError.value = ''
}
async function resolve(): Promise<void> {
  if (!handling.value) return
  if (!note.value.trim()) {
    noteError.value = '请填写处理说明'
    return
  }
  try {
    await api.post(`/api/alerts/${handling.value.id}/resolve`, { note: note.value })
    show('已标记为已处理')
    handling.value = null
    await load()
  } catch (e) {
    noteError.value = errorText(e)
  }
}
function notifyBadge(s: string): string {
  return s === 'failed' ? 'badge-bad' : s === 'retrying' ? 'badge-warn' : s === 'sent' ? '' : 'badge-info'
}
</script>

<template>
  <div data-page-id="PAGE-F11-01" class="g3">
    <div class="page-head"><h1 class="page-title">预警中心</h1></div>
    <PageState v-if="loading" state="loading" />
    <PageState v-else-if="error" :error="error" @retry="load" />
    <template v-else-if="data">
      <div v-if="!data.has_any" class="card state">
        <div class="state-title">目前没有预警</div>
        <p>每次确认导入金蝶或 BI 实际数后，系统会用规则库中生效的预警规则重新评估，命中的记录会出现在这里。</p>
        <RouterLink class="btn" :to="{ name: 'rules' }">查看预警规则</RouterLink>
      </div>
      <template v-else>
        <div class="grid-3 section">
          <div class="card fade-in"><div class="kpi-label">未处理</div><div class="kpi-value num">{{ data.kpis.open }}</div></div>
          <div class="card fade-in"><div class="kpi-label">已处理</div><div class="kpi-value num">{{ data.kpis.resolved }}</div></div>
          <div class="card fade-in"><div class="kpi-label">钉钉通知失败</div><div class="kpi-value num" :class="{ bad: data.kpis.notify_failed > 0 }">{{ data.kpis.notify_failed }}</div></div>
        </div>
        <div class="row" style="margin-bottom: var(--space-3)">
          <label class="small muted" for="f-st">状态</label>
          <select id="f-st" v-model="status" class="select"><option value="">全部</option><option value="open">未处理</option><option value="resolved">已处理</option></select>
          <label class="small muted" for="f-rule">规则</label>
          <select id="f-rule" v-model="ruleId" class="select"><option value="">全部规则</option><option v-for="r in data.rules" :key="r.id" :value="r.id">{{ r.name }}</option></select>
          <label class="small muted" for="f-nt">通知状态</label>
          <select id="f-nt" v-model="notify" class="select"><option value="">全部</option><option value="sent">已发送</option><option value="retrying">重试中</option><option value="failed">通知失败</option><option value="pending">待发送</option></select>
          <span class="spacer"></span>
          <span v-if="data.last_evaluation" class="small muted">最近评估：{{ data.last_evaluation.at }}（{{ data.last_evaluation.file_name }} 导入后）</span>
        </div>
        <div class="table-wrap">
          <table class="table">
            <thead><tr><th>规则（版本）</th><th>对象</th><th>期间</th><th class="num">指标值</th><th>阈值</th><th>状态</th><th>通知状态</th><th>操作</th></tr></thead>
            <tbody>
              <tr v-for="it in data.items" :key="it.id">
                <td class="wrap">{{ it.rule_name }}（v{{ it.rule_version_no }}）</td>
                <td class="w-n">{{ it.object_name }}</td>
                <td class="num">{{ it.period_text }}</td>
                <td class="num">{{ it.metric_display }}<div v-for="p in it.metric_parts" :key="p" class="small muted">{{ p }}</div></td>
                <td class="w-n">{{ it.threshold_display }}</td>
                <td class="w-n">
                  <span class="badge" :class="it.status === 'open' ? 'badge-warn' : ''">{{ it.status_label }}</span>
                  <div v-if="it.status === 'resolved'" class="small muted">{{ it.resolved_by_name }} · {{ it.resolved_at }}</div>
                  <div v-if="it.updated_after_resolve"><span class="badge badge-info">指标已更新</span> <span class="small muted">{{ it.updated_at }}</span></div>
                </td>
                <td><span class="badge" :class="notifyBadge(it.notify_status)">{{ it.notify_status_label }}</span></td>
                <td class="w-n">
                  <button class="link" type="button" @click="openDetail(it.id)">详情</button>
                  <button v-if="it.can_resolve" class="link" type="button" style="margin-left: var(--space-2)" @click="openHandle(it)">标记已处理</button>
                </td>
              </tr>
            </tbody>
          </table>
          <div v-if="!data.items.length" class="state"><div class="state-title">没有符合筛选条件的预警</div><p>调整状态、规则或通知状态筛选。</p></div>
        </div>
        <div class="pager">
          <span>共 {{ data.total }} 条 · 第 {{ data.page }} 页</span>
          <span>
            <button class="btn" type="button" :disabled="page <= 1" @click="page--; load()">上一页</button>
            <button class="btn" type="button" style="margin-left: var(--space-2)" :disabled="page * data.page_size >= data.total" @click="page++; load()">下一页</button>
          </span>
        </div>
        <p class="small muted">预警只由规则库中当前生效的规则版本生成；同一规则版本、同一对象、同一期间只保留一条记录，再次命中时更新指标值，不重复通知。钉钉通知只包含规则名称、对象、期间和系统链接，不包含金额。</p>
      </template>
    </template>

    <G3Modal :open="!!detail" title="预警详情" wide @close="detail = null">
      <template v-if="detail">
        <dl class="kv">
          <dt>规则与版本</dt><dd>{{ detail.rule_name }}（v{{ detail.rule_version_no }}）</dd>
          <dt>对象</dt><dd>{{ detail.object_name }}</dd>
          <dt>期间</dt><dd class="num">{{ detail.period_text }}</dd>
          <dt>指标值</dt><dd class="num">{{ detail.metric_display }}<span v-if="detail.metric_parts.length">（{{ detail.metric_parts.join('；') }}）</span></dd>
          <dt>阈值</dt><dd>{{ detail.threshold_display }}</dd>
          <dt>接收人</dt><dd>{{ detail.receivers.join('、') || '—' }}</dd>
          <dt>状态</dt><dd>{{ detail.status_label }}<template v-if="detail.status === 'resolved'">（{{ detail.resolved_by_name }} · {{ detail.resolved_at }}：{{ detail.resolve_note }}）</template></dd>
        </dl>
        <h3 class="section-title" style="margin-top: var(--space-4); font-size: var(--text-base)">钉钉通知</h3>
        <div v-if="detail.notice_preview" class="msg">{{ detail.notice_preview.title }}{{ detail.notice_preview.name }}
对象：{{ detail.notice_preview.object }}
期间：{{ detail.notice_preview.period }}
查看详情：{{ detail.notice_preview.link_text }}</div>
        <p v-else class="small muted">没有可通知的接收人。</p>
        <ul class="timeline" style="margin-top: var(--space-2)">
          <li v-for="a in detail.attempts" :key="a.label">{{ a.label }} · {{ a.at }} · {{ a.ok ? '成功' : `失败（${a.error ?? '钉钉返回错误'}）` }}</li>
          <li v-if="!detail.attempts.length" class="muted">{{ detail.notify_status_label }}（调度器每分钟发送）</li>
        </ul>
        <h3 class="section-title" style="margin-top: var(--space-4); font-size: var(--text-base)">记录变化</h3>
        <ul class="timeline">
          <li v-for="(c, i) in detail.changes" :key="i">{{ c.at }} · {{ c.text }}</li>
        </ul>
      </template>
      <template #actions>
        <RouterLink v-if="detail?.report_link" class="btn" :to="detail.report_link">查看相关报表</RouterLink>
        <button class="btn" type="button" @click="detail = null">关闭</button>
      </template>
    </G3Modal>

    <G3Modal :open="!!handling" title="标记为已处理" @close="handling = null">
      <p class="small muted">{{ handling?.rule_name }} · {{ handling?.object_name }} · {{ handling?.period_text }}</p>
      <div class="field">
        <label class="req" for="h-note">处理说明</label>
        <textarea id="h-note" v-model="note" class="input" :aria-invalid="!!noteError" placeholder="说明偏差原因和已采取的措施，例如：4 月一次性预付全年海外仓服务费，5–12 月不再发生"></textarea>
        <div v-if="noteError" class="field-error" role="alert">{{ noteError }}</div>
      </div>
      <template #actions>
        <button class="btn" type="button" @click="handling = null">取消</button>
        <button class="btn btn-primary" type="button" @click="resolve">确认已处理</button>
      </template>
    </G3Modal>
    <div v-if="toast" class="toast" role="status">{{ toast }}</div>
  </div>
</template>

<style>
.g3-modal .msg { white-space: pre-line; background: var(--surface-warm); border: 1px solid var(--border-soft); border-radius: var(--radius-md); padding: var(--space-3); font-size: var(--text-sm); }
.g3-modal .timeline { list-style: none; margin: 0; padding: 0; font-size: var(--text-sm); }
.g3-modal .timeline li { padding: var(--space-1) 0; border-bottom: 1px solid var(--border-soft); }
.g3-modal .timeline li:last-child { border-bottom: 0; }
.g3-modal .section-title { font-weight: 600; margin: 0 0 var(--space-2); }
</style>
