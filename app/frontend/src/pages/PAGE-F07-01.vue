<script setup lang="ts">
/** PAGE-F07-01 待我审批：待处理 / 已处理，按类型筛选（AC-F07-01、AC-F08-04、AC-F12-04） */
import { computed, onMounted, ref, watch } from 'vue'
import { api } from '@/api/client'
import PageState from '@/components/PageState.vue'
import { fmtTime, isForbidden } from '@/components/g2/util'
import '@/components/g2/g2.css'

interface Item {
  type: string
  id: number
  title: string
  kind_label: string
  prev_step?: string
  step?: string
  submitter?: string | null
  submitted_at?: string | null
  result?: string
  reason?: string | null
  handled_at?: string
  link: string
}

const tab = ref<'pending' | 'done'>('pending')
const items = ref<Item[]>([])
const counts = ref({ pending: 0, done: 0 })
const kind = ref('')
const loading = ref(true)
const error = ref<unknown>(null)

async function load(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    const res = await api.get<{ items: Item[]; pending_count: number; done_count: number }>('/api/approvals', { tab: tab.value })
    items.value = res.items
    counts.value = { pending: res.pending_count, done: res.done_count }
  } catch (e) {
    error.value = e
  } finally {
    loading.value = false
  }
}
onMounted(load)
watch(tab, load)

const KIND_GROUP: Record<string, string> = { unit: '预算编制', task: '预算编制', 'adjustment-unit': '目标调整', adjustment: '目标调整', 'rule-version': '规则审批' }
const shown = computed(() => items.value.filter((it) => !kind.value || KIND_GROUP[it.type] === kind.value))
/** 当前环节旁只注明上一级审批结果；「某人 提交」已在提交人列显示，不重复 */
function priorStep(it: Item): string {
  if (!it.prev_step || (it.submitter && it.prev_step.startsWith(it.submitter))) return ''
  return it.prev_step
}
function waited(iso?: string | null): string {
  if (!iso) return '—'
  const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86400000)
  return days <= 0 ? '不到 1 天' : `${days} 天`
}
</script>

<template>
  <div data-page-id="PAGE-F07-01" class="g2 g2-approval">
    <div class="page-head"><h1 class="page-title">待我审批</h1></div>
    <PageState
      v-if="error"
      :error="error"
      :title="isForbidden(error) ? '你没有访问该页面的权限' : '数据加载失败'"
      :description="isForbidden(error) ? '待我审批只对部门负责人、财务负责人和 CEO 开放。如需审核职责，请联系财务负责人在「角色与权限」中分配。' : '服务器暂时无法返回数据，已录入的内容不受影响。请稍后重试。'"
      @retry="load"
    />
    <template v-else>
      <div class="row" style="margin-bottom: var(--space-3)">
        <div class="tabs" role="tablist" style="margin-bottom: 0">
          <a class="tab" href="#" role="tab" :aria-selected="tab === 'pending' ? 'true' : 'false'" @click.prevent="tab = 'pending'">待处理<span class="count">{{ counts.pending }}</span></a>
          <a class="tab" href="#" role="tab" :aria-selected="tab === 'done' ? 'true' : 'false'" @click.prevent="tab = 'done'">已处理<span class="count">{{ counts.done }}</span></a>
        </div>
        <span class="spacer"></span>
        <label class="small muted" for="f-type">类型</label>
        <select id="f-type" v-model="kind" class="select">
          <option value="">全部类型</option>
          <option value="预算编制">预算编制</option>
          <option value="目标调整">目标调整</option>
          <option value="规则审批">规则审批</option>
        </select>
      </div>
      <p class="small muted" style="margin: 0 0 var(--space-3)">新的待审批事项会同时发送钉钉工作通知；点击「审批」进入只读详情页后通过或退回。</p>
      <PageState v-if="loading" state="loading" />
      <div v-else-if="tab === 'pending' && !items.length" class="card state">
        <div class="state-title">当前没有待你审批的事项</div>
        <p>填报单位提交、目标调整提交或规则提交后会出现在这里，同时发送钉钉工作通知。</p>
        <button class="btn" type="button" @click="tab = 'done'">查看已处理</button>
      </div>
      <template v-else>
        <div class="table-wrap">
          <table class="table">
            <thead>
              <tr>
                <th>类型</th><th>审批事项</th>
                <template v-if="tab === 'pending'"><th>提交人</th><th>当前环节</th><th class="num">提交时间</th><th class="num">已等待</th></template>
                <template v-else><th>结果</th><th class="num">处理时间</th></template>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="it in shown" :key="`${it.type}-${it.id}-${it.handled_at ?? ''}`" :data-approval="it.title">
                <td><span class="badge">{{ it.kind_label }}</span></td>
                <td class="wrap">{{ it.title }}</td>
                <template v-if="tab === 'pending'">
                  <td>{{ it.submitter ?? '—' }}</td>
                  <td class="wrap">{{ it.step ?? '审批' }}<span v-if="priorStep(it)" class="muted">（{{ priorStep(it) }}）</span></td>
                  <td class="num">{{ fmtTime(it.submitted_at) }}</td>
                  <td class="num">{{ waited(it.submitted_at) }}</td>
                </template>
                <template v-else>
                  <td class="wrap">
                    <span :class="it.result === '已退回' ? 'badge badge-bad' : 'badge badge-good'">{{ it.result }}</span>
                    <span v-if="it.reason" class="muted"> {{ it.reason }}</span>
                  </td>
                  <td class="num">{{ fmtTime(it.handled_at) }}</td>
                </template>
                <td>
                  <RouterLink :class="tab === 'pending' ? 'btn btn-primary' : 'link'" :to="it.link">{{ tab === 'pending' ? '审批' : '查看' }}</RouterLink>
                </td>
              </tr>
            </tbody>
          </table>
          <div v-if="!shown.length" class="state">
            <div class="state-title">没有符合筛选条件的事项</div>
            <p>换一个类型，或查看全部类型。</p>
          </div>
        </div>
        <div class="pager"><span>共 {{ shown.length }} 条</span><span>每页 50 条</span></div>
      </template>
    </template>
  </div>
</template>
