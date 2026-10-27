<script setup lang="ts">
/** PAGE-F04-01 我的填报：本人负责的填报单位、状态、退回原因与入口（AC-F04-09、AC-F07-03） */
import { computed, onMounted, ref } from 'vue'
import { api } from '@/api/client'
import PageState from '@/components/PageState.vue'
import { fillRoute, isForbidden, UNIT_STATUS_BADGE, type UnitInfo } from '@/components/g2/util'
import '@/components/g2/g2.css'

const items = ref<UnitInfo[]>([])
const loading = ref(true)
const error = ref<unknown>(null)

async function load(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    items.value = (await api.get<{ items: UnitInfo[] }>('/api/filling-units', { mine: 1 })).items
  } catch (e) {
    error.value = e
  } finally {
    loading.value = false
  }
}
onMounted(load)

const pending = computed(() => items.value.filter((u) => ['not_started', 'filling', 'adjusting', 'returned'].includes(u.status)))
const overdue = computed(() => items.value.filter((u) => u.overdue))
const deadline = computed(() => overdue.value[0]?.task?.deadline ?? '')

function action(u: UnitInfo): string {
  if (!u.editable) return '查看 · 已锁定'
  if (u.status === 'not_started') return '开始填报'
  if (u.status === 'returned') return '修改后重新提交'
  return '继续填报'
}
</script>

<template>
  <div data-page-id="PAGE-F04-01" class="g2">
    <div class="page-head">
      <div>
        <h1 class="page-title">我的填报</h1>
        <p v-if="!loading && !error && items.length" class="sub">
          你负责 {{ items.length }} 个填报单位，待处理 {{ pending.length }} 个（未开始、填报中或已退回）。
        </p>
      </div>
    </div>
    <PageState v-if="loading" state="loading" />
    <PageState
      v-else-if="error"
      :error="error"
      :title="isForbidden(error) ? undefined : '我的填报加载失败'"
      :description="isForbidden(error) ? '你的账号没有任何填报角色。如需填报，请联系财务负责人分配。' : undefined"
      @retry="load"
    />
    <PageState
      v-else-if="!items.length"
      state="empty"
      title="你目前没有需要填报的单位"
      description="财务负责人发布编制任务后，你负责的填报单位会出现在这里，同时你会收到钉钉工作通知。"
    />
    <template v-else>
      <div v-if="overdue.length" class="notice notice-warn" role="status">
        已过截止日期 {{ deadline }} · 还有 {{ overdue.length }} 个单位未提交，请尽快完成。
      </div>
      <div class="table-wrap">
        <table class="table" aria-label="我负责的填报单位">
          <thead>
            <tr><th>填报单位</th><th>类型</th><th>编制任务</th><th class="num">截止日期</th><th>状态</th><th>退回原因</th><th class="num">最后保存</th><th>操作</th></tr>
          </thead>
          <tbody>
            <tr v-for="u in items" :key="`${u.id}-${u.rolling?.key ?? ''}`" :data-unit="u.name">
              <td>{{ u.name }}</td>
              <td>{{ u.type_label }}</td>
              <td>{{ u.adjustment?.name ?? u.rolling?.name ?? u.task?.name }}</td>
              <td class="num">{{ u.task?.deadline ?? '—' }}</td>
              <td>
                <span :class="UNIT_STATUS_BADGE[u.status] ?? 'badge'">{{ u.status_label }}</span>
                <span v-if="u.overdue" class="badge badge-warn" style="margin-left: var(--space-1)">逾期</span>
              </td>
              <td class="wrap">
                <template v-if="u.return_reason">{{ u.returned_by }}：{{ u.return_reason }}</template>
                <span v-else class="muted">—</span>
              </td>
              <td class="num">{{ u.updated_at ?? '—' }}</td>
              <td>
                <RouterLink :class="u.editable ? 'btn' : 'link'" :to="fillRoute(u)" :data-action="action(u)">{{ action(u) }}</RouterLink>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p class="sub">已提交、已通过的单位内容已锁定，被退回之前任何人都不能修改，只能查看。</p>
    </template>
  </div>
</template>
